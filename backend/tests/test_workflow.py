from datetime import datetime, timedelta, timezone

from app.models import Notification, RequestNote, Role, ServiceRequest, StatusHistory, User, UserRole


def test_workflow_models_can_persist(db_session):
    user = User(name="Agent", email="agent@test.local", password_hash="test-hash")
    role = Role(name="AGENT")
    db_session.add_all([user, role]); db_session.flush()
    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    request = ServiceRequest(request_id="REQ-TEST", department="Revenue", service_type="Permit", request_date=datetime.now(timezone.utc), sla_deadline=datetime.now(timezone.utc) + timedelta(hours=24), current_stage="Review", stage_start_time=datetime.now(timezone.utc), priority="High", historical_stage_avg_hours=4, historical_stage_delay_rate=10, department_delay_rate=10, previous_delays=0)
    db_session.add(request); db_session.flush()
    db_session.add(StatusHistory(request_id=request.id, old_status="NEW", new_status="ASSIGNED", changed_by=user.id, reason="Assigned"))
    db_session.add(RequestNote(request_id=request.id, author_id=user.id, content="Review started"))
    db_session.add(Notification(user_id=user.id, title="Assigned", message="Request assigned", type="ASSIGNMENT"))
    db_session.commit()
    assert db_session.query(StatusHistory).count() == 1
    assert db_session.query(RequestNote).count() == 1
    assert db_session.query(Notification).count() == 1
