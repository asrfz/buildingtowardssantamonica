from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Optional


class EmergencyContact(BaseModel):
    name: str
    email: str
    relationship: str = ""


class UserCreate(BaseModel):
    name: str
    email: str
    emergency_contacts: list[EmergencyContact] = []
    threshold_multiplier: float = 2.5


class UserResponse(BaseModel):
    user_id: str
    name: str
    email: str
    emergency_contacts: list[EmergencyContact]
    threshold_multiplier: float
    created_at: datetime


class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    emergency_contacts: Optional[list[EmergencyContact]] = None
    threshold_multiplier: Optional[float] = None
