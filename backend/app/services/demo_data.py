from datetime import datetime, timedelta, timezone
import random
from typing import Any

from app.services.risk_engine import calculate_risk
from app.services.sla_engine import calculate_sla
from app.services.recommendation_engine import recommend

DEPARTMENTS = ["Revenue", "Municipal Services", "Transport", "Public Works", "Health Services", "Licensing", "Water Services"]
STAGES = ["Submitted", "Document Verification", "Review", "Approval", "Field Inspection", "Payment Processing"]
SERVICES = ["Permit renewal", "Property assessment", "Road repair", "Health inspection", "Water connection", "Business license"]


def generate_demo(count: int = 1000) -> list[dict[str, Any]]:
    random.seed(42)
    now = datetime.now(timezone.utc)
    rows = []
    for index in range(count):
        is_hero = index == 41
        department = "Revenue" if is_hero else random.choice(DEPARTMENTS)
        stage = "Document Verification" if is_hero else random.choice(STAGES)
        request_date = now - timedelta(hours=(30 if is_hero else random.randint(2, 160)))
        deadline = now + timedelta(hours=5) if is_hero else request_date + timedelta(hours=random.choice([24, 48, 72]))
        avg = 6 if is_hero else random.uniform(3, 18)
        current = 10 if is_hero else avg * random.uniform(.3, 2.0)
        hist = 35 if is_hero else random.uniform(5, 45)
        dept = 100 if is_hero else random.uniform(5, 45)
        previous = 8 if is_hero else random.randint(0, 3)
        priority = "High" if is_hero else random.choice(["Low", "Medium", "High", "Urgent"])
        sla = calculate_sla(request_date, deadline, now - timedelta(hours=current), now)
        risk = calculate_risk({"sla_remaining_hours": sla["remaining_hours"], "sla_duration_hours": sla["duration_hours"], "current_stage_hours": current, "historical_stage_avg_hours": avg, "historical_stage_delay_rate": hist, "department_delay_rate": dept, "previous_delays": previous, "priority": priority})
        action = recommend(risk["risk_level"], priority, stage, dept)
        rows.append({"request_id": "REQ-1042" if is_hero else f"REQ-{1001 + index}", "department": department, "service_type": "Property assessment" if is_hero else random.choice(SERVICES), "request_date": request_date, "sla_deadline": deadline, "current_stage": stage, "stage_start_time": now - timedelta(hours=current), "priority": priority, "historical_stage_avg_hours": round(avg, 1), "historical_stage_delay_rate": round(hist, 1), "department_delay_rate": round(dept, 1), "previous_delays": previous, "risk_score": risk["risk_score"], "risk_level": risk["risk_level"], "status": "BREACHED" if sla["status"] == "BREACHED" else risk["risk_level"], "bottleneck": stage, "recommended_action": action["action"], "explanation": "", "updated_at": now})
    return rows
