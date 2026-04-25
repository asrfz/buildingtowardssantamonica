from pydantic import BaseModel, Field
from datetime import datetime


class SensorPayload(BaseModel):
    sound_level: int = Field(ge=0, le=1023)
    temperature_c: float = Field(ge=-40.0, le=120.0)
    magnetic_state: int = Field(ge=0, le=1)
    accel_x: float
    accel_y: float
    accel_z: float
    pressure: float
    timestamp: datetime
