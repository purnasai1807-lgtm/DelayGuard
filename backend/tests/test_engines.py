from datetime import datetime, timedelta, timezone

from app.services.csv_service import validate_csv
from app.services.recommendation_engine import recommend
from app.services.risk_engine import calculate_risk
from app.services.sla_engine import calculate_sla


def test_risk_classification():
    result = calculate_risk({"sla_remaining_hours": 1, "sla_duration_hours": 24, "current_stage_hours": 12, "historical_stage_avg_hours": 4, "historical_stage_delay_rate": 80, "department_delay_rate": 70, "previous_delays": 3, "priority": "Urgent"})
    assert result["risk_level"] == "CRITICAL"


def test_breached_sla_cannot_be_at_risk():
    now = datetime.now(timezone.utc)
    result = calculate_sla(now - timedelta(hours=25), now - timedelta(hours=1), now - timedelta(hours=4), now)
    assert result["status"] == "BREACHED"


def test_recommendation_escalates_critical():
    assert recommend("CRITICAL", "High", "Review", 10)["action"] == "ESCALATE"


def test_csv_validation_rejects_bad_row():
    from io import BytesIO
    csv = b"request_id,department,service_type,request_date,sla_deadline,current_stage,stage_start_time,priority,historical_stage_avg_hours,historical_stage_delay_rate,department_delay_rate,previous_delays\nREQ-1,Revenue,Permit,not-a-date,2026-01-01T00:00:00+00:00,Review,2026-01-01T00:00:00+00:00,High,4,10,10,0\n"
    valid, errors = validate_csv(BytesIO(csv))
    assert not valid and errors
