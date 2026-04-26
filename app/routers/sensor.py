from fastapi import APIRouter, HTTPException
from datetime import datetime
from app.models.sensor import SensorPayload
from app.models.event import EventResponse
from app.services.anomaly_detector import score_reading
from app.services.vision_service import capture_frame
from app.services.cloudinary_service import upload_and_crop
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
    temp_text = f"{payload.temperature_c}°C" if payload.temperature_c is not None else "n/a"
    return EventResponse(
        event_id="",
        status="injected",
        message=f"Reading injected — temp={temp_text}, sound={payload.sound_level}",
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
