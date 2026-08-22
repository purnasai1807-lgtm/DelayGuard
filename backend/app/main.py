from datetime import datetime, timezone
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_token, get_subject, hash_password, verify_password
from app.db.session import Base, engine, get_db
from app.models import ServiceRequest, User
from app.schemas.common import AuthIn, RegisterIn, UserOut
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
    yield


app = FastAPI(title="DelayGuard API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[item.strip() for item in settings.cors_origins.split(",")], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
oauth2 = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def current_user(token: str = Depends(oauth2), db: Session = Depends(get_db)) -> User:
    subject = get_subject(token)
    user = db.scalar(select(User).where(User.email == subject)) if subject else None
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user


def request_payload(item: ServiceRequest) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    sla = calculate_sla(item.request_date, item.sla_deadline, item.stage_start_time, now)
    risk = calculate_risk({"sla_remaining_hours": sla["remaining_hours"], "sla_duration_hours": sla["duration_hours"], "current_stage_hours": max((now - item.stage_start_time).total_seconds() / 3600, 0), "historical_stage_avg_hours": item.historical_stage_avg_hours, "historical_stage_delay_rate": item.historical_stage_delay_rate, "department_delay_rate": item.department_delay_rate, "previous_delays": item.previous_delays, "priority": item.priority})
    item.risk_score, item.risk_level = risk["risk_score"], risk["risk_level"]
    item.status = sla["status"]
    item.recommended_action = recommend(item.risk_level, item.priority, item.current_stage, item.department_delay_rate)["action"]
    reasons = explain({"current_stage": item.current_stage, "current_stage_hours": max((now - item.stage_start_time).total_seconds() / 3600, 0), "historical_stage_avg_hours": item.historical_stage_avg_hours, "historical_stage_delay_rate": item.historical_stage_delay_rate, "priority": item.priority}, sla, risk)
    return {"request_id": item.request_id, "department": item.department, "service_type": item.service_type, "request_date": item.request_date.isoformat(), "sla_deadline": item.sla_deadline.isoformat(), "current_stage": item.current_stage, "priority": item.priority, "status": item.status, "risk_score": item.risk_score, "risk_level": item.risk_level, "bottleneck": item.bottleneck or item.current_stage, "recommended_action": item.recommended_action, "explanation": reasons, "sla": sla, "recommendation": recommend(item.risk_level, item.priority, item.current_stage, item.department_delay_rate)}


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, Any]:
    db.execute(text("SELECT 1"))
    return {"status": "healthy"}


@app.post("/api/auth/register")
def register(payload: RegisterIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    if payload.password != payload.confirm_password or len(payload.password) < 8:
        raise HTTPException(status_code=422, detail="Invalid registration data")
    if db.scalar(select(User).where(User.email == payload.email.lower())):
        raise HTTPException(status_code=409, detail="Unable to create account")
    user = User(name=payload.name, email=payload.email.lower(), password_hash=hash_password(payload.password))
    db.add(user); db.commit(); db.refresh(user)
    return {"success": True, "data": {"user": UserOut.model_validate(user), "access_token": create_token(user.email), "token_type": "bearer"}}


@app.post("/api/auth/login")
def login(payload: AuthIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"success": True, "data": {"user": UserOut.model_validate(user), "access_token": create_token(user.email), "token_type": "bearer"}}


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


@app.get("/api/requests")
def list_requests(page: int = 1, limit: int = 20, search: str = "", department: str = "", risk_level: str = "", status_filter: str = "", db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    limit = min(max(limit, 20), 100)
    query = select(ServiceRequest)
    if search:
        query = query.where(or_(ServiceRequest.request_id.ilike(f"%{search}%"), ServiceRequest.service_type.ilike(f"%{search}%")))
    if department: query = query.where(ServiceRequest.department == department)
    if risk_level: query = query.where(ServiceRequest.risk_level == risk_level)
    if status_filter: query = query.where(ServiceRequest.status == status_filter)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(ServiceRequest.risk_score.desc()).offset((page - 1) * limit).limit(limit)).all()
    return {"success": True, "data": {"items": [request_payload(row) for row in rows], "pagination": {"page": page, "limit": limit, "total": total, "pages": (total + limit - 1) // limit}}}


@app.get("/api/requests/{request_id}")
def get_request(request_id: str, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    item = db.scalar(select(ServiceRequest).where(ServiceRequest.request_id == request_id))
    if not item: raise HTTPException(status_code=404, detail="Request not found")
    return {"success": True, "data": request_payload(item)}


@app.post("/api/requests/{request_id}/analyze")
def analyze(request_id: str, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    item = db.scalar(select(ServiceRequest).where(ServiceRequest.request_id == request_id))
    if not item: raise HTTPException(status_code=404, detail="Request not found")
    data = request_payload(item); db.commit()
    return {"success": True, "data": data}


@app.post("/api/requests/upload")
def upload(file: UploadFile = File(...), db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    if not file.filename or Path(file.filename).suffix.lower() != ".csv": raise HTTPException(status_code=400, detail="Unsupported file type")
    valid, errors = validate_csv(file.file)
    created = 0
    for row in valid:
        if db.scalar(select(ServiceRequest).where(ServiceRequest.request_id == row["request_id"])): continue
        db.add(ServiceRequest(**row, risk_score=0, risk_level="LOW", status="ON_TRACK", bottleneck=row["current_stage"], recommended_action="MONITOR")); created += 1
    db.commit()
    return {"success": True, "data": {"total_rows": len(valid) + len(errors), "valid_rows": created, "invalid_rows": len(errors), "errors": errors[:50]}}


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


@app.get("/api/analytics/bottlenecks")
def bottlenecks(db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    return {"success": True, "data": summarize_bottlenecks([request_payload(row) for row in db.scalars(select(ServiceRequest)).all()])}


@app.get("/api/analytics/departments")
def departments(db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict[str, Any]:
    data = dashboard(db)["data"]["departments"]
    return {"success": True, "data": data}
