from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    success: bool = True
    data: T


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    success: bool = False
    error: ErrorBody


class RequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    request_id: str
    department: str
    service_type: str
    request_date: str
    sla_deadline: str
    current_stage: str
    priority: str
    status: str
    risk_score: float
    risk_level: str
    bottleneck: str
    recommended_action: str
    explanation: list[str]
    sla: dict
    recommendation: dict


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: str


class AuthIn(BaseModel):
    email: str
    password: str


class RegisterIn(AuthIn):
    name: str
    confirm_password: str


class RequestIn(BaseModel):
    request_id: str
    department: str
    service_type: str
    request_date: datetime
    sla_deadline: datetime
    current_stage: str
    stage_start_time: datetime
    priority: str
    historical_stage_avg_hours: float
    historical_stage_delay_rate: float
    department_delay_rate: float
    previous_delays: int = 0
