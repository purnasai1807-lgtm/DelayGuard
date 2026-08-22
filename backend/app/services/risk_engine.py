from typing import TypedDict


class RiskInput(TypedDict):
    sla_remaining_hours: float
    sla_duration_hours: float
    current_stage_hours: float
    historical_stage_avg_hours: float
    historical_stage_delay_rate: float
    department_delay_rate: float
    previous_delays: int
    priority: str


class RiskResult(TypedDict):
    risk_score: float
    risk_level: str


def _priority_score(priority: str) -> float:
    return {"Low": 20, "Medium": 50, "High": 80, "Urgent": 100}.get(priority.title(), 50)


def calculate_risk(values: RiskInput) -> RiskResult:
    proximity_ratio = 1 - values["sla_remaining_hours"] / max(values["sla_duration_hours"], 0.01)
    proximity = 100 if values["sla_remaining_hours"] <= 5 else min(max(proximity_ratio, 0), 1) * 100
    stage_delay = min(max(values["current_stage_hours"] / max(values["historical_stage_avg_hours"], 0.01), 0), 1) * 100
    historical = min(max(values["historical_stage_delay_rate"], 0), 100)
    department = min(max(values["department_delay_rate"], 0), 100)
    previous = min(max(values["previous_delays"] * 25, 0), 100)
    priority = _priority_score(values["priority"])
    score = min(max(proximity * .30 + stage_delay * .25 + historical * .20 + department * .15 + previous * .05 + priority * .05, 0), 100)
    level = "LOW" if score < 40 else "MEDIUM" if score < 70 else "HIGH" if score < 85 else "CRITICAL"
    return {"risk_score": round(score, 1), "risk_level": level}
