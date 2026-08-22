"""Create DelayGuard users and service requests tables."""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("users", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("name", sa.String(120), nullable=False), sa.Column("email", sa.String(255), nullable=False), sa.Column("password_hash", sa.String(255), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_table("service_requests", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("request_id", sa.String(50), nullable=False), sa.Column("department", sa.String(100), nullable=False), sa.Column("service_type", sa.String(100), nullable=False), sa.Column("request_date", sa.DateTime(timezone=True), nullable=False), sa.Column("sla_deadline", sa.DateTime(timezone=True), nullable=False), sa.Column("current_stage", sa.String(100), nullable=False), sa.Column("stage_start_time", sa.DateTime(timezone=True), nullable=False), sa.Column("priority", sa.String(20), nullable=False), sa.Column("historical_stage_avg_hours", sa.Float(), nullable=False), sa.Column("historical_stage_delay_rate", sa.Float(), nullable=False), sa.Column("department_delay_rate", sa.Float(), nullable=False), sa.Column("previous_delays", sa.Integer(), nullable=False), sa.Column("risk_score", sa.Float(), nullable=False, server_default="0"), sa.Column("risk_level", sa.String(20), nullable=False, server_default="LOW"), sa.Column("status", sa.String(20), nullable=False, server_default="ON_TRACK"), sa.Column("bottleneck", sa.String(100), nullable=False, server_default=""), sa.Column("recommended_action", sa.String(30), nullable=False, server_default="MONITOR"), sa.Column("explanation", sa.Text(), nullable=False, server_default=""), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    for column in ["request_id", "department", "service_type", "sla_deadline", "current_stage", "priority", "risk_score", "risk_level", "status"]:
        op.create_index(f"ix_service_requests_{column}", "service_requests", [column], unique=column == "request_id")
    op.create_index("ix_requests_priority_risk", "service_requests", ["priority", "risk_score"])


def downgrade() -> None:
    op.drop_table("service_requests")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
