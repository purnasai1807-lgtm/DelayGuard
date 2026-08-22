from datetime import datetime, timezone
from typing import TypedDict


class SLAResult(TypedDict):
    duration_hours: float
    elapsed_hours: float
    remaining_hours: float
    consumed_percent: float
    status: str


def calculate_sla(request_date: datetime, deadline: datetime, stage_start: datetime, now: datetime | None = None) -> SLAResult:
    now = now or datetime.now(timezone.utc)
    request_date = request_date.astimezone(timezone.utc)
    deadline = deadline.astimezone(timezone.utc)
    stage_start = stage_start.astimezone(timezone.utc)
    total = max((deadline - request_date).total_seconds() / 3600, 0.01)
    elapsed = max((now - request_date).total_seconds() / 3600, 0)
    remaining = (deadline - now).total_seconds() / 3600
    consumed = min(max(elapsed / total * 100, 0), 100)
    if now > deadline:
        status = "BREACHED"
    elif remaining <= total * 0.15:
        status = "CRITICAL"
    elif remaining <= total * 0.35 or now > stage_start:
        status = "AT_RISK"
    else:
        status = "ON_TRACK"
    return {"duration_hours": round(total, 2), "elapsed_hours": round(elapsed, 2), "remaining_hours": round(remaining, 2), "consumed_percent": round(consumed, 1), "status": status}
