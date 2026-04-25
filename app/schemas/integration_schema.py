from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field


class ArduinoIngestRequest(BaseModel):
    arduino_file_path: str = Field(
        default="arduino/homepulse_sensor/homepulse_sensor.ino",
        description="Path to the Arduino sketch that defines outgoing JSON.",
    )


class ArduinoIngestResponse(BaseModel):
    status: str
    inserted_id: str
    saved_at: datetime
    arduino_file_path: str
    json_keys: list[str]
    agent_dispatch: dict
