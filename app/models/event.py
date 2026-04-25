from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class IrregularityEvent(BaseModel):
    user_id: str
    event_type: str
    severity: str
    deviation_score: float
    sensor_payload: dict
    detected_at: datetime


class EventResponse(BaseModel):
    event_id: str
    status: str
    message: str


class EventConfirmRequest(BaseModel):
    confirmed: bool


class EventDetail(BaseModel):
    event_id: str
    user_id: str
    event_type: str
    severity: str
    deviation_score: float
    status: str
    notification_sent: bool
    detected_at: datetime
    triage_reason: Optional[str] = None
    triage_confidence: Optional[float] = None
    email_body: Optional[str] = None
