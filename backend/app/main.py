from datetime import datetime, timezone
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Any, cast
from uuid import uuid4

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
import logging
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_token, get_subject, hash_password, verify_password
from app.db.session import Base, engine, get_db
from app.models import Notification, RequestNote, Role, ServiceRequest, StatusHistory, User, UserRole
from app.schemas.common import AuthIn, NoteIn, RegisterIn, RequestIn, RoleUpdateIn, StatusUpdateIn, UserOut
from app.core.dependencies import require_admin, require_agent, require_manager, user_roles
from app.services.bottleneck_engine import summarize_bottlenecks
from app.services.csv_service import validate_csv
from app.services.demo_data import generate_demo
from app.services.explanation_engine import explain
from app.services.recommendation_engine import recommend
from app.services.risk_engine import calculate_risk
from app.services.sla_engine import calculate_sla

@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    with Session(engine) as db:
        for name in ("ADMIN", "MANAGER", "AGENT", "USER"):
            if not db.scalar(select(Role).where(Role.name == name)):
                db.add(Role(name=name))
        db.commit()
    yield


app = FastAPI(title="DelayGuard API", version="1.0.0", lifespan=lifespan)
limiter: Any = cast(Any, Limiter(key_func=get_remote_address, default_limits=["120/minute"]))
app.state.limiter = limiter


async def rate_limit_error(_: Request, __: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(status_code=429, content={"success": False, "error": {"code": "RATE_LIMITED", "message": "Too many requests"}})


app.add_exception_handler(RateLimitExceeded, cast(Any, rate_limit_error))
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("delayguard")
app.add_middleware(CORSMiddleware, allow_origins=[item.strip() for item in settings.cors_origins.split(",")], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
oauth2 = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
upload_jobs: dict[str, dict[str, Any]] = {}


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Invalid request data"}})


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
    code = "UNAUTHORIZED" if exc.status_code == 401 else "NOT_FOUND" if exc.status_code == 404 else "CONFLICT" if exc.status_code == 409 else "REQUEST_ERROR"
    return JSONResponse(status_code=exc.status_code, content={"success": False, "error": {"code": code, "message": str(exc.detail)}})


@app.exception_handler(Exception)
async def server_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled request error: %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"success": False, "error": {"code": "INTERNAL_ERROR", "message": "An unexpected server error occurred"}})


def current_user(token: str = Depends(oauth2), db: Session = Depends(get_db)) -> User:
    subject = get_subject(token)
    user = db.scalar(select(User).where(User.email == subject)) if subject else None
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user


def ensure_role(user: User, role_name: str, db: Session) -> None:
    role = db.scalar(select(Role).where(Role.name == role_name))
    if role and not db.scalar(select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == role.id)):
        db.add(UserRole(user_id=user.id, role_id=role.id))


def notify(db: Session, user_id: int, title: str, message: str, notification_type: str = "INFO") -> None:
    db.add(Notification(user_id=user_id, title=title, message=message, type=notification_type))


def record_status(db: Session, item: ServiceRequest, user: User, new_status: str, reason: str = "") -> None:
    if item.workflow_status != new_status:
        db.add(StatusHistory(request_id=item.id, old_status=item.workflow_status, new_status=new_status, changed_by=user.id, reason=reason))
        item.workflow_status = new_status
        notify(db, user.id, "Request status changed", f"{item.request_id} changed to {new_status}.", "STATUS")


def request_payload(item: ServiceRequest) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    sla = calculate_sla(item.request_date, item.sla_deadline, item.stage_start_time, now)
    risk = calculate_risk({"sla_remaining_hours": sla["remaining_hours"], "sla_duration_hours": sla["duration_hours"], "current_stage_hours": max((now - item.stage_start_time).total_seconds() / 3600, 0), "historical_stage_avg_hours": item.historical_stage_avg_hours, "historical_stage_delay_rate": item.historical_stage_delay_rate, "department_delay_rate": item.department_delay_rate, "previous_delays": item.previous_delays, "priority": item.priority})
    item.risk_score, item.risk_level = risk["risk_score"], risk["risk_level"]
    item.status = sla["status"]
    item.recommended_action = recommend(item.risk_level, item.priority, item.current_stage, item.department_delay_rate)["action"]
    reasons = explain({"current_stage": item.current_stage, "current_stage_hours": max((now - item.stage_start_time).total_seconds() / 3600, 0), "historical_stage_avg_hours": item.historical_stage_avg_hours, "historical_stage_delay_rate": item.historical_stage_delay_rate, "priority": item.priority}, sla, risk)
    return {"request_id": item.request_id, "department": item.department, "service_type": item.service_type, "request_date": item.request_date.isoformat(), "sla_deadline": item.sla_deadline.isoformat(), "current_stage": item.current_stage, "priority": item.priority, "status": item.status, "workflow_status": item.workflow_status, "risk_score": item.risk_score, "risk_level": item.risk_level, "bottleneck": item.bottleneck or item.current_stage, "recommended_action": item.recommended_action, "explanation": reasons, "sla": sla, "recommendation": recommend(item.risk_level, item.priority, item.current_stage, item.department_delay_rate)}


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, Any]:
    db.execute(text("SELECT 1"))
    return {"status": "healthy"}


@app.post("/api/auth/register")
@limiter.limit("5/minute")
def register(request: Request, payload: RegisterIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    if payload.password != payload.confirm_password or len(payload.password) < 8:
        raise HTTPException(status_code=422, detail="Invalid registration data")
    if db.scalar(select(User).where(User.email == payload.email.lower())):
        raise HTTPException(status_code=409, detail="Unable to create account")
    user = User(name=payload.name, email=payload.email.lower(), password_hash=hash_password(payload.password))
    db.add(user); db.flush(); ensure_role(user, "USER", db); db.commit(); db.refresh(user)
    return {"success": True, "data": {"user": UserOut.model_validate(user), "access_token": create_token(user.email), "token_type": "bearer"}}


@app.post("/api/auth/login")
@limiter.limit("10/minute")
def login(request: Request, payload: AuthIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user_roles(user, db):
        ensure_role(user, "USER", db); db.commit()
    return {"success": True, "data": {"user": UserOut.model_validate(user), "access_token": create_token(user.email), "token_type": "bearer"}}


@app.post("/api/auth/logout")
def logout(_: User = Depends(current_user)) -> dict[str, Any]:
    return {"success": True, "data": {"message": "Logged out"}}


@app.post("/api/auth/refresh")
def refresh(user: User = Depends(current_user)) -> dict[str, Any]:
    return {"success": True, "data": {"access_token": create_token(user.email), "token_type": "bearer"}}


@app.get("/api/auth/me")
def me(user: User = Depends(current_user)) -> dict[str, Any]:
    return {"success": True, "data": UserOut.model_validate(user)}


@app.post("/api/demo-data")
def load_demo(db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    existing = db.scalar(select(func.count()).select_from(ServiceRequest))
    if existing:
        return {"success": True, "data": {"created": 0, "message": "Demo data already loaded"}}
    rows = [ServiceRequest(**row) for row in generate_demo()]
    db.add_all(rows); db.commit()
    return {"success": True, "data": {"created": len(rows), "message": "Demo data loaded"}}


@app.get("/api/demo-data")
def demo_status(db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    return {"success": True, "data": {"count": db.scalar(select(func.count()).select_from(ServiceRequest)) or 0}}


@app.post("/api/demo-data/load")
def demo_load(db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    return load_demo(db, _)


@app.delete("/api/demo-data")
def demo_delete(db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    deleted = db.query(ServiceRequest).delete()
    db.commit()
    return {"success": True, "data": {"deleted": deleted}}


@app.get("/api/requests")
def list_requests(page: int = 1, limit: int = 20, page_size: int | None = None, search: str = "", department: str = "", service_type: str = "", risk_level: str = "", current_stage: str = "", priority: str = "", status: str = "", status_filter: str = "", start_date: str = "", end_date: str = "", sort_by: str = "risk_score", sort_order: str = "desc", db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    if page_size is not None: limit = page_size
    limit = min(max(limit, 20), 100)
    query = select(ServiceRequest)
    if search:
        query = query.where(or_(ServiceRequest.request_id.ilike(f"%{search}%"), ServiceRequest.service_type.ilike(f"%{search}%")))
    if department: query = query.where(ServiceRequest.department == department)
    if service_type: query = query.where(ServiceRequest.service_type == service_type)
    if risk_level: query = query.where(ServiceRequest.risk_level == risk_level)
    if current_stage: query = query.where(ServiceRequest.current_stage == current_stage)
    if priority: query = query.where(ServiceRequest.priority == priority)
    if status or status_filter: query = query.where(ServiceRequest.status == (status or status_filter))
    if start_date: query = query.where(ServiceRequest.request_date >= start_date)
    if end_date: query = query.where(ServiceRequest.request_date <= end_date)
    sort_column = getattr(ServiceRequest, sort_by, ServiceRequest.risk_score)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(sort_column.asc() if sort_order.lower() == "asc" else sort_column.desc()).offset((page - 1) * limit).limit(limit)).all()
    return {"success": True, "data": {"items": [request_payload(row) for row in rows], "pagination": {"page": page, "limit": limit, "total": total, "pages": (total + limit - 1) // limit}}}


@app.get("/api/requests/risk-summary")
def risk_summary(db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    rows = [request_payload(row) for row in db.scalars(select(ServiceRequest)).all()]
    return {"success": True, "data": {level: sum(row["risk_level"] == level for row in rows) for level in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]}}


@app.get("/api/requests/{request_id}")
def get_request(request_id: str, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    item = db.scalar(select(ServiceRequest).where(ServiceRequest.request_id == request_id))
    if not item: raise HTTPException(status_code=404, detail="Request not found")
    return {"success": True, "data": request_payload(item)}


def find_request(request_id: str, db: Session) -> ServiceRequest:
    item = db.scalar(select(ServiceRequest).where(ServiceRequest.request_id == request_id))
    if not item:
        raise HTTPException(status_code=404, detail="Request not found")
    return item


@app.post("/api/requests")
def create_request(payload: RequestIn, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    if db.scalar(select(ServiceRequest).where(ServiceRequest.request_id == payload.request_id)):
        raise HTTPException(status_code=409, detail="Request ID already exists")
    item = ServiceRequest(**payload.model_dump(), bottleneck=payload.current_stage, recommended_action="MONITOR", explanation="")
    db.add(item); db.commit(); db.refresh(item)
    return {"success": True, "data": request_payload(item)}


@app.put("/api/requests/{request_id}")
def update_request(request_id: str, payload: RequestIn, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    item = find_request(request_id, db)
    for key, value in payload.model_dump().items():
        if key != "request_id": setattr(item, key, value)
    db.commit()
    return {"success": True, "data": request_payload(item)}


@app.delete("/api/requests/{request_id}")
def delete_request(request_id: str, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    item = find_request(request_id, db)
    db.delete(item); db.commit()
    return {"success": True, "data": {"request_id": request_id, "deleted": True}}


@app.patch("/api/requests/{request_id}/status")
def update_status(request_id: str, payload: StatusUpdateIn, db: Session = Depends(get_db), user: User = Depends(require_agent)) -> dict[str, Any]:
    allowed = {"NEW", "ASSIGNED", "IN_PROGRESS", "PENDING", "RESOLVED", "CLOSED", "ESCALATED"}
    if payload.status not in allowed:
        raise HTTPException(status_code=422, detail="Invalid status")
    item = find_request(request_id, db)
    record_status(db, item, user, payload.status, payload.reason)
    if payload.status == "RESOLVED":
        notify(db, user.id, "Request resolved", f"{item.request_id} was resolved.", "RESOLVED")
    db.commit()
    return {"success": True, "data": request_payload(item)}


@app.get("/api/requests/{request_id}/history")
def request_history(request_id: str, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    item = find_request(request_id, db)
    rows = db.scalars(select(StatusHistory).where(StatusHistory.request_id == item.id).order_by(StatusHistory.changed_at.asc())).all()
    return {"success": True, "data": [{"id": row.id, "old_status": row.old_status, "new_status": row.new_status, "changed_by": row.changed_by, "reason": row.reason, "changed_at": row.changed_at.isoformat()} for row in rows]}


@app.post("/api/requests/{request_id}/assign")
def assign_request(request_id: str, officer_id: int, db: Session = Depends(get_db), user: User = Depends(require_manager)) -> dict[str, Any]:
    item = find_request(request_id, db)
    officer = db.get(User, officer_id)
    if not officer: raise HTTPException(status_code=404, detail="Officer not found")
    item.assigned_user_id = officer.id
    record_status(db, item, user, "ASSIGNED", "Assigned to officer")
    notify(db, officer.id, "Request assigned", f"{item.request_id} was assigned to you.", "ASSIGNMENT")
    db.commit()
    return {"success": True, "data": request_payload(item)}


@app.post("/api/requests/{request_id}/resolve")
def resolve_request(request_id: str, db: Session = Depends(get_db), user: User = Depends(require_agent)) -> dict[str, Any]:
    item = find_request(request_id, db)
    record_status(db, item, user, "RESOLVED", "Resolved by operator")
    item.updated_at = datetime.now(timezone.utc); db.commit()
    return {"success": True, "data": request_payload(item)}


@app.post("/api/requests/{request_id}/escalate")
def escalate_request(request_id: str, db: Session = Depends(get_db), user: User = Depends(require_agent)) -> dict[str, Any]:
    item = find_request(request_id, db)
    record_status(db, item, user, "ESCALATED", "Escalated for SLA risk")
    db.commit()
    return {"success": True, "data": request_payload(item)}


@app.post("/api/requests/{request_id}/notes")
def add_note(request_id: str, payload: NoteIn, db: Session = Depends(get_db), user: User = Depends(require_agent)) -> dict[str, Any]:
    item = find_request(request_id, db)
    note = RequestNote(request_id=item.id, author_id=user.id, content=payload.content)
    db.add(note); notify(db, user.id, "New request note", f"A note was added to {item.request_id}.", "NOTE"); db.commit(); db.refresh(note)
    return {"success": True, "data": {"id": note.id, "request_id": request_id, "author_id": note.author_id, "content": note.content, "created_at": note.created_at.isoformat()}}


@app.get("/api/requests/{request_id}/notes")
def request_notes(request_id: str, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    item = find_request(request_id, db)
    rows = db.scalars(select(RequestNote).where(RequestNote.request_id == item.id).order_by(RequestNote.created_at.desc())).all()
    return {"success": True, "data": [{"id": row.id, "author_id": row.author_id, "content": row.content, "created_at": row.created_at.isoformat()} for row in rows]}


@app.post("/api/requests/{request_id}/analyze")
@limiter.limit("30/minute")
def analyze(request: Request, request_id: str, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    item = db.scalar(select(ServiceRequest).where(ServiceRequest.request_id == request_id))
    if not item: raise HTTPException(status_code=404, detail="Request not found")
    data = request_payload(item); db.commit()
    return {"success": True, "data": data}


@app.get("/api/requests/{request_id}/sla")
def request_sla(request_id: str, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    item = find_request(request_id, db); data = request_payload(item)["sla"]
    return {"success": True, "data": {"sla_duration": data["duration_hours"], "elapsed_time": data["elapsed_hours"], "remaining_time": data["remaining_hours"], "sla_consumed_percentage": data["consumed_percent"], "sla_status": data["status"]}}


@app.post("/api/requests/{request_id}/calculate-sla")
def calculate_request_sla(request_id: str, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    return request_sla(request_id, db, _)


@app.get("/api/requests/{request_id}/risk")
def request_risk(request_id: str, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    data = request_payload(find_request(request_id, db))
    return {"success": True, "data": {"risk_score": data["risk_score"], "risk_level": data["risk_level"]}}


@app.get("/api/requests/{request_id}/explanation")
def request_explanation(request_id: str, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    return {"success": True, "data": {"reasons": request_payload(find_request(request_id, db))["explanation"]}}


@app.post("/api/requests/{request_id}/explain")
def explain_request(request_id: str, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    return request_explanation(request_id, db, _)


@app.get("/api/requests/{request_id}/bottleneck")
def request_bottleneck(request_id: str, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    item = find_request(request_id, db)
    matches = summarize_bottlenecks([request_payload(row) for row in db.scalars(select(ServiceRequest).where(ServiceRequest.current_stage == item.current_stage)).all()])
    fallback: dict[str, Any] = {"stage": item.current_stage, "delay_rate": item.historical_stage_delay_rate, "affected_requests": 0}
    result: dict[str, Any] = next((row for row in matches if row["stage"] == item.current_stage), fallback)
    return {"success": True, "data": result}


@app.get("/api/requests/{request_id}/recommendation")
def request_recommendation(request_id: str, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    return {"success": True, "data": request_payload(find_request(request_id, db))["recommendation"]}


@app.post("/api/requests/{request_id}/recommend")
def recommend_request(request_id: str, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    return request_recommendation(request_id, db, _)


@app.post("/api/requests/upload")
@limiter.limit("10/minute")
def upload(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    if request.headers.get("content-length") and int(request.headers["content-length"]) > settings.max_upload_size:
        raise HTTPException(status_code=413, detail="Upload exceeds configured size limit")
    if not file.filename or Path(file.filename).suffix.lower() != ".csv": raise HTTPException(status_code=400, detail="Unsupported file type")
    valid, errors = validate_csv(file.file)
    created = 0
    for row in valid:
        if db.scalar(select(ServiceRequest).where(ServiceRequest.request_id == row["request_id"])): continue
        db.add(ServiceRequest(**row, risk_score=0, risk_level="LOW", status="ON_TRACK", bottleneck=row["current_stage"], recommended_action="MONITOR")); created += 1
    db.commit()
    job_id = str(uuid4())
    upload_jobs[job_id] = {"status": "completed", "total_rows": len(valid) + len(errors), "valid_rows": created, "invalid_rows": len(errors), "errors": errors[:50]}
    return {"success": True, "data": {"job_id": job_id, **upload_jobs[job_id]}}


@app.get("/api/requests/upload/{job_id}")
def upload_status(job_id: str, _: User = Depends(current_user)) -> dict[str, Any]:
    job = upload_jobs.get(job_id)
    if not job: raise HTTPException(status_code=404, detail="Upload job not found")
    return {"success": True, "data": {"job_id": job_id, **job}}


@app.get("/api/dashboard")
def dashboard(db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    rows = db.scalars(select(ServiceRequest)).all()
    payloads = [request_payload(row) for row in rows]
    counts = {key: sum(1 for row in payloads if row["status"] == key) for key in ["ON_TRACK", "AT_RISK", "CRITICAL", "BREACHED"]}
    risk_distribution: list[dict[str, str | int]] = [{"name": key, "value": sum(1 for row in payloads if row["risk_level"] == key)} for key in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]]
    departments: list[dict[str, str | int | float]] = []
    for department in sorted({row["department"] for row in payloads}):
        group = [row for row in payloads if row["department"] == department]
        departments.append({"department": department, "request_count": len(group), "average_risk": round(sum(row["risk_score"] for row in group) / len(group), 1), "sla_compliance": round(sum(row["status"] == "ON_TRACK" for row in group) / len(group) * 100, 1)})
    return {"success": True, "data": {"stats": {"total": len(payloads), **counts, "at_risk": counts["AT_RISK"] + counts["CRITICAL"]}, "risk_distribution": risk_distribution, "departments": departments, "bottlenecks": summarize_bottlenecks(payloads)[:6], "urgent_requests": sorted(payloads, key=lambda row: row["risk_score"], reverse=True)[:10]}}


@app.post("/api/predictions/run")
def refresh_predictions(db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    rows = db.scalars(select(ServiceRequest).where(ServiceRequest.status != "BREACHED")).all()
    for item in rows:
        request_payload(item)
    db.commit()
    return {"success": True, "data": {"updated": len(rows), "message": "Risk predictions refreshed"}}


@app.get("/api/alerts")
def alerts(db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    alerts_data: list[dict[str, Any]] = []
    alert_query = select(ServiceRequest).where(ServiceRequest.status.in_(["CRITICAL", "AT_RISK", "BREACHED"])).order_by(ServiceRequest.risk_score.desc()).limit(50)
    for item in db.scalars(alert_query).all():
        data = request_payload(item)
        alert_type = "OVERDUE" if data["status"] == "BREACHED" else "CRITICAL_RISK" if data["risk_level"] == "CRITICAL" else "DEADLINE_APPROACHING"
        alerts_data.append({"type": alert_type, "request_id": data["request_id"], "risk_level": data["risk_level"], "risk_score": data["risk_score"], "message": f"{data['request_id']} requires attention before its SLA is breached.", "action": data["recommended_action"]})
    return {"success": True, "data": alerts_data}


@app.get("/api/dashboard/summary")
def dashboard_summary(db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    return {"success": True, "data": dashboard(db, _)["data"]["stats"]}


@app.get("/api/dashboard/risk-distribution")
def dashboard_risk_distribution(db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    return {"success": True, "data": dashboard(db, _)["data"]["risk_distribution"]}


@app.get("/api/dashboard/urgent-requests")
def dashboard_urgent(db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    return {"success": True, "data": dashboard(db, _)["data"]["urgent_requests"]}


@app.get("/api/dashboard/sla-compliance")
def dashboard_compliance(db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    stats = dashboard(db, _)["data"]["stats"]
    return {"success": True, "data": {"compliance_percentage": round(stats["ON_TRACK"] / stats["total"] * 100, 1) if stats["total"] else 0}}


@app.get("/api/analytics/bottlenecks")
def bottlenecks(db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    return {"success": True, "data": summarize_bottlenecks([request_payload(row) for row in db.scalars(select(ServiceRequest)).all()])}


@app.get("/api/analytics/departments")
def departments(db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    data = dashboard(db)["data"]["departments"]
    return {"success": True, "data": data}


@app.get("/api/analytics")
def analytics(db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    data = dashboard(db, _)["data"]
    return {"success": True, "data": {"stats": data["stats"], "risk": data["risk_distribution"], "stages": data["bottlenecks"], "departments": data["departments"]}}


@app.get("/api/analytics/risk")
def analytics_risk(db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    return dashboard_risk_distribution(db, _)


@app.get("/api/analytics/sla")
def analytics_sla(db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    return dashboard_compliance(db, _)


@app.get("/api/analytics/stages")
def analytics_stages(db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    return bottlenecks(db, _)


@app.get("/api/analytics/priorities")
def analytics_priorities(db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    rows = db.execute(select(ServiceRequest.priority, func.count()).group_by(ServiceRequest.priority)).all()
    return {"success": True, "data": [{"priority": row[0], "count": row[1]} for row in rows]}


@app.get("/api/analytics/departments/{department}")
def department_detail(department: str, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    data = [row for row in dashboard(db, _)["data"]["departments"] if row["department"] == department]
    if not data: raise HTTPException(status_code=404, detail="Department not found")
    return {"success": True, "data": data[0]}


@app.get("/api/analytics/bottlenecks/stages")
def stage_bottlenecks(db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    return bottlenecks(db, _)


@app.get("/api/analytics/bottlenecks/departments")
def department_bottlenecks(db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    rows = [request_payload(row) for row in db.scalars(select(ServiceRequest)).all()]
    grouped: list[dict[str, Any]] = []
    for department in sorted({row["department"] for row in rows}):
        group = [row for row in rows if row["department"] == department]
        delayed = sum(row["status"] in {"AT_RISK", "CRITICAL", "BREACHED"} for row in group)
        grouped.append({"department": department, "delay_rate": round(delayed / len(group) * 100, 1), "affected_requests": delayed})
    return {"success": True, "data": sorted(grouped, key=lambda row: row["delay_rate"], reverse=True)}


@app.post("/api/ai/explain")
def ai_explain(payload: dict[str, Any], _: User = Depends(current_user)) -> dict[str, Any]:
    return {"success": True, "data": {"provider": "deterministic-fallback", "reasons": payload.get("reasons", ["AI enhancement is unavailable; deterministic explanation is active."])}}


@app.post("/api/ai/analyze")
def ai_analyze(payload: dict[str, Any], _: User = Depends(current_user)) -> dict[str, Any]:
    return {"success": True, "data": {"provider": "deterministic-fallback", "analysis": "Core analysis completed without an external AI dependency.", "input": payload}}


@app.get("/api/health")
def api_health(db: Session = Depends(get_db)) -> dict[str, Any]:
    return health(db)


@app.get("/api/system/status")
def system_status(db: Session = Depends(get_db)) -> dict[str, Any]:
    health(db)
    return {"success": True, "data": {"status": "operational", "database": "connected", "ai": "optional"}}


@app.get("/api/notifications")
def notifications(db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    rows = db.scalars(select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at.desc()).limit(100)).all()
    return {"success": True, "data": [{"id": row.id, "title": row.title, "message": row.message, "type": row.type, "is_read": row.is_read, "created_at": row.created_at.isoformat()} for row in rows]}


@app.get("/api/notifications/unread")
def unread_notifications(db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    rows = db.scalars(select(Notification).where(Notification.user_id == user.id, Notification.is_read.is_(False)).order_by(Notification.created_at.desc())).all()
    return {"success": True, "data": [{"id": row.id, "title": row.title, "message": row.message, "type": row.type, "is_read": row.is_read, "created_at": row.created_at.isoformat()} for row in rows]}


@app.patch("/api/notifications/{notification_id}/read")
def mark_notification_read(notification_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    row = db.scalar(select(Notification).where(Notification.id == notification_id, Notification.user_id == user.id))
    if not row: raise HTTPException(status_code=404, detail="Notification not found")
    row.is_read = True; db.commit()
    return {"success": True, "data": {"id": row.id, "is_read": True}}


@app.patch("/api/notifications/read-all")
def mark_all_notifications_read(db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    rows = db.scalars(select(Notification).where(Notification.user_id == user.id, Notification.is_read.is_(False))).all()
    for row in rows: row.is_read = True
    db.commit()
    return {"success": True, "data": {"updated": len(rows)}}


@app.get("/api/users")
def users(db: Session = Depends(get_db), _: User = Depends(require_manager)) -> dict[str, Any]:
    rows = db.scalars(select(User).order_by(User.created_at.asc())).all()
    return {"success": True, "data": [{"id": row.id, "name": row.name, "email": row.email, "roles": sorted(user_roles(row, db))} for row in rows]}


@app.patch("/api/users/{user_id}")
def update_user_role(user_id: int, payload: RoleUpdateIn, db: Session = Depends(get_db), _: User = Depends(require_admin)) -> dict[str, Any]:
    if payload.role not in {"ADMIN", "MANAGER", "AGENT", "USER"}: raise HTTPException(status_code=422, detail="Invalid role")
    target = db.get(User, user_id)
    if not target: raise HTTPException(status_code=404, detail="User not found")
    ensure_role(target, payload.role, db); db.commit()
    return {"success": True, "data": {"id": target.id, "roles": sorted(user_roles(target, db))}}
