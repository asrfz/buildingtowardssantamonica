from fastapi import APIRouter, HTTPException, Request
from datetime import datetime, timezone
from typing import Any

from app.models.sensor import SensorPayload
from app.models.event import EventResponse
from app.services.anomaly_detector import score_reading
from app.services.vision_service import capture_frame
from app.services.cloudinary_service import upload_and_crop
from app.utils.serial_reader import inject_reading
from app.database import get_db

router = APIRouter()

# Cross-process queue: FastAPI and sensor_agent (run_agents.py) are different
# processes — in-memory inject_reading() alone never reaches the bureau.
SIMULATION_QUEUE_COLL = "sensor_simulation_queue"


def _parse_simulate_json(body: dict[str, Any]) -> tuple[SensorPayload, dict[str, Any] | None]:
    """
    Accept legacy flat SensorPayload JSON, or wrapped:
    { "payload": { ... }, "force_triage": { "event_type", "severity", ... } }
    """
    force = body.get("force_triage")
    if force is not None and not isinstance(force, dict):
        force = None
    inner = body.get("payload")
    if isinstance(inner, dict):
        return SensorPayload(**inner), force
    flat = {k: v for k, v in body.items() if k != "force_triage"}
    return SensorPayload(**flat), force


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
async def simulate_reading(request: Request) -> EventResponse:
    """
    Queue a reading for sensor_agent (MongoDB), and also push the in-memory queue
    (only useful if API and agents share one process — normally ignored by bureau).

    Body: flat SensorPayload fields, or { "payload": {...}, "force_triage": {...} }.
    force_triage skips anomaly scoring and sends IrregularityEvent directly — use when
    baselines are missing or for deterministic demos (e.g. loud noise).
    """
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("JSON object expected")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON body: {e}") from e

    try:
        payload, force_triage = _parse_simulate_json(body)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid simulate payload: {e}") from e

    db = get_db()
    doc: dict[str, Any] = {
        "payload": payload.model_dump(mode="json"),
        "force_triage": force_triage,
        "created_at": datetime.now(timezone.utc),
    }
    await db[SIMULATION_QUEUE_COLL].insert_one(doc)

    inject_reading(payload.model_dump(mode="json"))

    temp_text = f"{payload.temperature_c}°C" if payload.temperature_c is not None else "n/a"
    extra = " + force_triage" if force_triage else ""
    return EventResponse(
        event_id="",
        status="queued",
        message=f"Queued for sensor_agent (Mongo){extra} — temp={temp_text}, sound={payload.sound_level}",
    )


@router.post("/capture")
async def capture_reference_frame() -> dict:
    """
    Capture a single webcam frame and upload it to Cloudinary as a reference image
    for zone calibration. Returns the raw Cloudinary URL and public_id.
    """
    frame = await capture_frame()
    if frame is None:
        raise HTTPException(status_code=503, detail="Webcam unavailable")

    import cloudinary.uploader
    import cv2
    from app.config import settings

    _, buffer = cv2.imencode(".jpg", frame)
    result = cloudinary.uploader.upload(
        buffer.tobytes(),
        public_id="homepulse/reference/calibration",
        resource_type="image",
        overwrite=True,
    )
    return {
        "public_id": result["public_id"],
        "url": result["secure_url"],
        "width": result["width"],
        "height": result["height"],
    }


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
