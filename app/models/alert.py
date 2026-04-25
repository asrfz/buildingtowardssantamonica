from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class AlertLog(BaseModel):
    alert_id: str
    event_id: str
    user_id: str
    recipients: list[str]
    severity: str
    subject: str
    sent_at: datetime
    cancelled: bool = False
    cancelled_at: Optional[datetime] = None


class AlertCancelResponse(BaseModel):
    alert_id: str
    status: str
    message: str
