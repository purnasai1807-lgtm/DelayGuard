def recommend(risk_level: str, priority: str, stage: str, department_delay_rate: float) -> dict[str, str]:
    if risk_level == "CRITICAL":
        return {"action": "ESCALATE", "reason": "Critical breach risk requires immediate intervention by an owner."}
    if risk_level in {"HIGH", "CRITICAL"} and stage == "Approval":
        return {"action": "ESCALATE", "reason": "Approval is a high-impact bottleneck and needs immediate escalation."}
    if risk_level in {"HIGH", "CRITICAL"} and department_delay_rate >= 30:
        return {"action": "REASSIGN", "reason": "The department is overloaded; move work to available capacity."}
    if risk_level in {"HIGH", "CRITICAL"} and priority in {"High", "Urgent"}:
        return {"action": "PRIORITIZE", "reason": "High-priority work is approaching an SLA breach."}
    if risk_level == "MEDIUM":
        return {"action": "FOLLOW_UP", "reason": "A proactive follow-up can prevent the request from becoming critical."}
    return {"action": "MONITOR", "reason": "The request is on track and should remain under routine monitoring."}
