"""Add roles, workflow history, notes, notifications, and assignment."""
from alembic import op
import sqlalchemy as sa

revision = "0002_workflow_models"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("roles", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("name", sa.String(30), nullable=False))
    op.create_index("ix_roles_name", "roles", ["name"], unique=True)
    op.create_table("user_roles", sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True), sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True))
    op.add_column("service_requests", sa.Column("assigned_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True))
    op.add_column("service_requests", sa.Column("workflow_status", sa.String(30), nullable=False, server_default="NEW"))
    op.create_index("ix_service_requests_assigned_user_id", "service_requests", ["assigned_user_id"])
    op.create_table("status_history", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("request_id", sa.Integer(), sa.ForeignKey("service_requests.id", ondelete="CASCADE"), nullable=False), sa.Column("old_status", sa.String(30), nullable=False), sa.Column("new_status", sa.String(30), nullable=False), sa.Column("changed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False), sa.Column("reason", sa.Text(), nullable=False), sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_status_history_request_id", "status_history", ["request_id"])
    op.create_index("ix_status_history_changed_by", "status_history", ["changed_by"])
    op.create_table("request_notes", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("request_id", sa.Integer(), sa.ForeignKey("service_requests.id", ondelete="CASCADE"), nullable=False), sa.Column("author_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False), sa.Column("content", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_request_notes_request_id", "request_notes", ["request_id"])
    op.create_index("ix_request_notes_author_id", "request_notes", ["author_id"])
    op.create_table("notifications", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("title", sa.String(150), nullable=False), sa.Column("message", sa.Text(), nullable=False), sa.Column("type", sa.String(40), nullable=False), sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index("ix_notifications_is_read", "notifications", ["is_read"])


def downgrade() -> None:
    op.drop_table("notifications")
    op.drop_table("request_notes")
    op.drop_table("status_history")
    op.drop_index("ix_service_requests_assigned_user_id", table_name="service_requests")
    op.drop_column("service_requests", "assigned_user_id")
    op.drop_column("service_requests", "workflow_status")
    op.drop_table("user_roles")
    op.drop_table("roles")
