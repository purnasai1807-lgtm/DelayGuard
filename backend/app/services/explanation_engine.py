from typing import Any, Mapping


def explain(request: Mapping[str, Any], sla: Mapping[str, Any], risk: Mapping[str, Any]) -> list[str]:
    if risk["risk_level"] not in {"HIGH", "CRITICAL"}:
        return ["The request is currently within its expected processing window."]
    reasons: list[str] = []
    if request["current_stage_hours"] > request["historical_stage_avg_hours"]:
        reasons.append(f"Current stage duration is {request['current_stage_hours']:.1f} hours compared with a historical average of {request['historical_stage_avg_hours']:.1f} hours.")
    if request["historical_stage_delay_rate"] >= 25:
        reasons.append(f"{request['current_stage']} has a historical delay rate of {request['historical_stage_delay_rate']:.0f}%.")
    if sla["remaining_hours"] <= 12:
        reasons.append(f"Only {max(sla['remaining_hours'], 0):.1f} hours remain before the SLA deadline.")
    if request["priority"] in {"High", "Urgent"}:
        reasons.append(f"The request has {request['priority'].lower()} priority.")
    return reasons[:4]
