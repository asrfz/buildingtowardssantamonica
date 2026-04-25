from pydantic import BaseModel
from datetime import datetime


class EventTypeStats(BaseModel):
    total: int = 0
    false_positives: int = 0
    false_positive_rate: float = 0.2


class BehavioralSchemaResponse(BaseModel):
    user_id: str
    event_type_history: dict[str, EventTypeStats]
    updated_at: datetime
