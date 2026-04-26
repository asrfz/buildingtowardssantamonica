from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.config import settings
from app.database import get_db
from app.schemas.integration_schema import ArduinoIngestRequest, ArduinoIngestResponse
from app.services.agent_bridge_service import send_to_agent_dummy
from app.services.arduino_contract_service import extract_json_contract_from_ino

router = APIRouter()


@router.get("/dev-context")
async def dev_console_context() -> dict:
    """
    Non-secret defaults for the local dev console. Only available when APP_ENV=development
    so production builds are not probed for IDs. Matches backend DEFAULT_USER_ID.
    """
    if settings.APP_ENV != "development":
        raise HTTPException(status_code=404, detail="Not available")
    return {"default_user_id": settings.DEFAULT_USER_ID or ""}


@router.post("/arduino/ingest", response_model=ArduinoIngestResponse)
async def ingest_arduino_contract(payload: ArduinoIngestRequest) -> ArduinoIngestResponse:
    """
    Theoretical integration flow:
    1) Read Arduino sketch to determine expected JSON output fields.
    2) Save extracted contract to MongoDB Atlas.
    3) Send contract to agent bridge (dummy implementation for now).
    """
    sketch_path = str(Path(payload.arduino_file_path).resolve())

    try:
        contract = extract_json_contract_from_ino(sketch_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    now = datetime.now(timezone.utc)
    db = get_db()
    record = {
        "source": "arduino_sketch",
        "saved_at": now,
        "arduino_file_path": contract["file_path"],
        "json_keys": contract["json_keys"],
        "json_key_count": contract["json_key_count"],
        "serializes_json": contract["serializes_json"],
    }

    insert_result = await db.arduino_contracts.insert_one(record)
    agent_dispatch = await send_to_agent_dummy(record)

    return ArduinoIngestResponse(
        status="ok",
        inserted_id=str(insert_result.inserted_id),
        saved_at=now,
        arduino_file_path=contract["file_path"],
        json_keys=contract["json_keys"],
        agent_dispatch=agent_dispatch,
    )
