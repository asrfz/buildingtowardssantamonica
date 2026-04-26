import logging
import uuid
from fastapi import APIRouter, HTTPException, Query, Request, Response
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId

from app.config import settings
from app.models.sensor import SensorPayload
from app.models.event import EventResponse
from app.services.anomaly_detector import score_reading
from app.services.camera_snapshot_service import record_camera_snapshot
from app.services.snapshot_cloudinary_gate import refund_upload_slot, try_consume_upload_slot
from app.services.vision_service import capture_frame
from app.services.cloudinary_service import upload_and_crop, frame_to_base64
from app.utils.serial_reader import inject_reading
from app.database import get_db

logger = logging.getLogger(__name__)

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


@router.get("/live-frame-b64")
async def live_frame_b64() -> dict:
    """
    One OpenCV frame from the bureau webcam as base64 JPEG (no Cloudinary).
    Used by vision_agent / voice_agent so the camera stays on the API process.
    """
    logger.debug("sensor live-frame-b64: requesting capture")
    frame = await capture_frame()
    if frame is None:
        logger.warning("sensor live-frame-b64: no frame (webcam unavailable)")
        raise HTTPException(status_code=503, detail="Webcam unavailable")
    b64 = frame_to_base64(frame)
    logger.debug(
        "sensor live-frame-b64: encoded JPEG base64 len=%s shape=%s",
        len(b64),
        frame.shape,
    )
    return {"ok": True, "image_b64": b64}


@router.get("/preview-jpeg")
async def bureau_preview_jpeg() -> Response:
    """
    Latest OpenCV frame as raw JPEG bytes — no Cloudinary. Use for dev UI <img src>.
    """
    logger.info("sensor preview-jpeg: taking snapshot…")
    frame = await capture_frame()
    if frame is None:
        logger.warning("sensor preview-jpeg: snapshot aborted — webcam unavailable")
        raise HTTPException(status_code=503, detail="Webcam unavailable")
    import cv2

    h, w = frame.shape[:2]
    _, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    raw = buffer.tobytes()
    logger.info(
        "sensor preview-jpeg: snapshot ok %sx%s — JPEG encoded %s bytes (no Cloudinary)",
        w,
        h,
        len(raw),
    )
    return Response(
        content=raw,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@router.post("/preview-snapshot")
async def bureau_preview_snapshot(
    user_id: str | None = Query(None),
    force: bool = Query(False, description="development only: bypass upload slot gate"),
) -> dict:
    """
    Capture one OpenCV frame, upload to Cloudinary with a unique public_id, and store metadata
    in MongoDB (camera_snapshots) for the caregiver UI. Requires CLOUDINARY_* in .env.
    Optional query: user_id (defaults to DEFAULT_USER_ID). Live tile still uses GET /preview-jpeg.
    Uploads share a per-user slot pool with vision: one slot is granted per investigating triage;
    without a slot, returns 429 until the next anomaly (force=true in development bypasses).
    """
    if not settings.CLOUDINARY_CLOUD_NAME or not settings.CLOUDINARY_API_KEY:
        logger.warning(
            "sensor preview-snapshot: Cloudinary not configured (cloud_name/api_key missing)"
        )
        raise HTTPException(
            status_code=503,
            detail="Cloudinary not configured — use GET /sensor/preview-jpeg for local preview",
        )

    uid = (user_id or settings.DEFAULT_USER_ID or "").strip()
    if not uid:
        raise HTTPException(
            status_code=400,
            detail="user_id query param or DEFAULT_USER_ID in .env required to store snapshots",
        )
    try:
        ObjectId(uid)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid user_id: {e}") from e

    db = get_db()
    slot_consumed = False
    if settings.SNAPSHOT_CLOUDINARY_GATE_ENABLED:
        bypass = force and settings.APP_ENV == "development"
        if bypass:
            logger.warning("sensor preview-snapshot: force=True bypassing upload slot (APP_ENV=development)")
        elif not await try_consume_upload_slot(db, uid):
            raise HTTPException(
                status_code=429,
                detail=(
                    "No Cloudinary upload slot — wait for the next sensor anomaly (investigating triage), "
                    "or use GET /sensor/preview-jpeg for a local frame. "
                    "In development, ?force=true bypasses this gate."
                ),
            )
        else:
            slot_consumed = not bypass

    logger.info(
        "sensor preview-snapshot: taking snapshot for Cloudinary (cloud=%s) user=%s…",
        settings.CLOUDINARY_CLOUD_NAME,
        uid[:12],
    )
    frame = await capture_frame()
    if frame is None:
        logger.warning("sensor preview-snapshot: snapshot aborted — webcam unavailable")
        if slot_consumed:
            await refund_upload_slot(db, uid)
        raise HTTPException(status_code=503, detail="Webcam unavailable")

    import cloudinary.uploader
    import cv2

    h, w = frame.shape[:2]
    _, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    jpeg_bytes = buffer.tobytes()
    snap_key = uuid.uuid4().hex[:10]
    public_id = f"homepulse/snapshots/preview/{uid}/{snap_key}"
    logger.info(
        "sensor preview-snapshot: OpenCV JPEG buffer %s bytes (%sx%s) — uploading %s…",
        len(jpeg_bytes),
        w,
        h,
        public_id,
    )
    try:
        result = cloudinary.uploader.upload(
            jpeg_bytes,
            public_id=public_id,
            resource_type="image",
            overwrite=False,
        )
    except Exception as e:
        if slot_consumed:
            await refund_upload_slot(db, uid)
        logger.exception("sensor preview-snapshot: Cloudinary upload failed")
        raise HTTPException(status_code=502, detail=f"Cloudinary upload failed: {e}") from e
    url = result.get("secure_url", "")
    cw = result.get("width", w)
    ch = result.get("height", h)
    logger.info(
        "sensor preview-snapshot: Cloudinary upload done public_id=%s url=%s…",
        result.get("public_id"),
        url[:72] + ("…" if len(url) > 72 else ""),
    )

    inserted = await record_camera_snapshot(
        db,
        user_id=uid,
        url=url,
        cropped_url="",
        public_id=result.get("public_id", public_id),
        width=cw,
        height=ch,
        source="preview",
        event_id=None,
        event_type="",
    )
    return {
        "snapshot_id": inserted,
        "public_id": result["public_id"],
        "url": result["secure_url"],
        "width": cw,
        "height": ch,
    }


@router.post("/capture")
async def capture_reference_frame() -> dict:
    """
    Capture a single webcam frame and upload it to Cloudinary as a reference image
    for zone calibration. Returns the raw Cloudinary URL and public_id.
    """
    logger.info("sensor /capture (calibration): taking snapshot…")
    frame = await capture_frame()
    if frame is None:
        logger.warning("sensor /capture: webcam unavailable")
        raise HTTPException(status_code=503, detail="Webcam unavailable")

    import cloudinary.uploader
    import cv2

    _, buffer = cv2.imencode(".jpg", frame)
    jpeg_bytes = buffer.tobytes()
    logger.info(
        "sensor /capture: JPEG %s bytes — uploading to Cloudinary (reference/calibration)…",
        len(jpeg_bytes),
    )
    result = cloudinary.uploader.upload(
        jpeg_bytes,
        public_id="homepulse/reference/calibration",
        resource_type="image",
        overwrite=True,
    )
    url = result.get("secure_url", "")
    logger.info(
        "sensor /capture: Cloudinary ok public_id=%s url=%s…",
        result.get("public_id"),
        url[:72] + ("…" if len(url) > 72 else ""),
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
