from fastapi import APIRouter
from datetime import datetime
from app.models.sensor import SensorPayload
from app.models.event import EventResponse
from app.services.anomaly_detector import score_reading
from app.utils.serial_reader import inject_reading
from app.database import get_db

router = APIRouter()


@router.post("/reading", response_model=EventResponse)
async def receive_reading(payload: SensorPayload) -> EventResponse:
    """Receive a sensor payload and run anomaly detection. Used for HTTP-based testing."""
    db = get_db()
    # Pull DEFAULT_USER_ID lazily to avoid circular import at module load
    from app.config import settings
    user_id = settings.DEFAULT_USER_ID
    if not user_id:
        return EventResponse(event_id="", status="error", message="DEFAULT_USER_ID not set")

    result = await score_reading(user_id, payload, db)
    if result.triggered:
        return EventResponse(
            event_id="",
            status="anomaly_detected",
            message=f"{result.event_type} — {result.deviation_score:.1f}x above baseline ({result.severity})",
        )
    return EventResponse(event_id="", status="normal", message="Reading within baseline")


@router.post("/simulate", response_model=EventResponse)
async def simulate_reading(payload: SensorPayload) -> EventResponse:
    """
    Inject a simulated sensor reading into the serial queue.
    Use this endpoint to trigger the full agent pipeline without Arduino hardware.
    """
    inject_reading(payload.model_dump(mode="json"))
    return EventResponse(
        event_id="",
        status="injected",
        message=f"Reading injected — temp={payload.temperature_c}°C, sound={payload.sound_level}",
    )


@router.get("/baseline/{user_id}")
async def get_baseline(user_id: str) -> dict:
    """Return stored baselines for a user (all hours)."""
    from bson import ObjectId
    db = get_db()
    docs = await db.sensor_baselines.find({"user_id": ObjectId(user_id)}).to_list(100)
    for d in docs:
        d["_id"] = str(d["_id"])
        d["user_id"] = str(d["user_id"])
    return {"baselines": docs}
