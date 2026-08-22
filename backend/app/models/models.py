from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class ServiceRequest(Base):
    __tablename__ = "service_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    department: Mapped[str] = mapped_column(String(100), index=True)
    service_type: Mapped[str] = mapped_column(String(100), index=True)
    request_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sla_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    current_stage: Mapped[str] = mapped_column(String(100), index=True)
    stage_start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    priority: Mapped[str] = mapped_column(String(20), index=True)
    historical_stage_avg_hours: Mapped[float] = mapped_column(Float)
    historical_stage_delay_rate: Mapped[float] = mapped_column(Float)
    department_delay_rate: Mapped[float] = mapped_column(Float)
    previous_delays: Mapped[int] = mapped_column(Integer)
    risk_score: Mapped[float] = mapped_column(Float, default=0, index=True)
    risk_level: Mapped[str] = mapped_column(String(20), default="LOW", index=True)
    status: Mapped[str] = mapped_column(String(20), default="ON_TRACK", index=True)
    bottleneck: Mapped[str] = mapped_column(String(100), default="")
    recommended_action: Mapped[str] = mapped_column(String(30), default="MONITOR")
    explanation: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (Index("ix_requests_priority_risk", "priority", "risk_score"),)
