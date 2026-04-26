from pydantic import BaseModel, Field
from datetime import datetime


class SensorPayload(BaseModel):
    sound_level: int = Field(ge=0, le=1023)
    temperature_c: float = Field(default=22.0, ge=-40.0, le=120.0)
    magnetic_state: int = Field(ge=0, le=1)
    accel_x: float
    accel_y: float
    accel_z: float
    pressure: float
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    drop_detected: int = Field(default=0, ge=0, le=1)
    light_change_detected: int = Field(default=0, ge=0, le=1)
    motion_triggered: int = Field(default=0, ge=0, le=1)
    gyro_triggered: int = Field(default=0, ge=0, le=1)
    sound_triggered: int = Field(default=0, ge=0, le=1)
    magnetic_triggered: int = Field(default=0, ge=0, le=1)
