from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SensorPayload(BaseModel):
    # Arduino PDM (inputs.ino): mean abs of int16 mic samples — often 300–4000+, not 10-bit ADC
    sound_level: int = Field(ge=0, le=65535)
    # LSM9DS1 die temperature when present; omit or null if unavailable (no placeholder °C)
    temperature_c: Optional[float] = Field(default=None, ge=-40.0, le=120.0)
    magnetic_state: int = Field(ge=0, le=1)
    accel_x: float
    accel_y: float
    accel_z: float
    # LSM9DS1 gyro vector magnitude (dps); inputs.ino sends JSON key "gyro"
    gyro_magnitude: float = Field(default=0.0, ge=0.0, le=1e7)
    # No barometer on Nicla + LSM9DS1 — null/omit unless you attach e.g. BMP280 and send hPa
    pressure: Optional[float] = Field(default=None, ge=300.0, le=1100.0)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    drop_detected: int = Field(default=0, ge=0, le=1)
    light_change_detected: int = Field(default=0, ge=0, le=1)
    motion_triggered: int = Field(default=0, ge=0, le=1)
    gyro_triggered: int = Field(default=0, ge=0, le=1)
    sound_triggered: int = Field(default=0, ge=0, le=1)
    magnetic_triggered: int = Field(default=0, ge=0, le=1)
    # Analog light (A6) when present; None if not reported (skip ambient z-score)
    light_level: Optional[int] = Field(default=None, ge=0, le=1023)
