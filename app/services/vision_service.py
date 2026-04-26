import asyncio
import logging
import sys
import threading
import time
import numpy as np
import cv2
from bson import ObjectId
from app.config import settings

logger = logging.getLogger(__name__)

# One capture at a time — concurrent VideoCapture on Windows (MSMF) often returns
# "can't grab frame" (-1072873821) when preview-jpeg and live-frame-b64 overlap.
_webcam_lock = threading.Lock()

# Reuse a very recent frame so dev preview + vision_agent don't each reopen the camera
# back-to-back (slow on Windows). Callers always get a copy; TTL keeps snapshots fresh enough.
_frame_cache: tuple[np.ndarray, float] | None = None
_FRAME_CACHE_TTL_SEC = 0.75
_capture_async_lock: asyncio.Lock | None = None


def _get_capture_lock() -> asyncio.Lock:
    global _capture_async_lock
    if _capture_async_lock is None:
        _capture_async_lock = asyncio.Lock()
    return _capture_async_lock


# Fallback zone name for MongoDB room_zones lookup
EVENT_ZONE_MAP: dict[str, str] = {
    "STOVE_LEFT_ON":        "stove",
    "IRON_LEFT_ON":         "stove",
    "FIRE_RISK":            "stove",
    "FAUCET_RUNNING":       "sink",
    "WATER_DRIPPING":       "sink",
    "FRIDGE_OPEN":          "fridge",
    "APPLIANCE_FAULT":      "stove",
    "FALL_DETECTED":        "stove",
    "TEMPERATURE_ANOMALY":  "stove",
    "SOUND_ANOMALY":        "sink",
    "DOOR_SENSOR_ANOMALY":  "fridge",
    "MULTIVARIATE_ANOMALY": "stove",
}


def _open_video_capture(idx: int) -> cv2.VideoCapture:
    """Prefer DirectShow on Windows — often more stable than MSMF for USB webcams."""
    if sys.platform == "win32":
        cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
        if cap.isOpened():
            return cap
        cap.release()
    return cv2.VideoCapture(idx)


def _capture_frame_sync() -> np.ndarray | None:
    idx = settings.WEBCAM_INDEX
    with _webcam_lock:
        logger.debug("webcam capture: opening device index=%s", idx)
        # Brief retry helps MSMF/DSHOW when the pipeline needs a warm-up frame
        for attempt in range(2):
            cap = _open_video_capture(idx)
            if not cap.isOpened():
                logger.warning(
                    "webcam capture: VideoCapture.open failed (index=%s) — no snapshot",
                    idx,
                )
                return None
            ret, frame = cap.read()
            cap.release()
            if ret and frame is not None:
                logger.debug(
                    "webcam capture: ok index=%s shape=%s dtype=%s",
                    idx,
                    frame.shape,
                    frame.dtype,
                )
                return frame
            if attempt == 0:
                time.sleep(0.08)
        logger.warning(
            "webcam capture: read() failed or empty frame (index=%s) — no snapshot",
            idx,
        )
        return None


async def capture_frame() -> np.ndarray | None:
    """Capture a single frame from the webcam. Returns None if webcam unavailable."""
    global _frame_cache
    now = time.monotonic()
    if _frame_cache is not None:
        frame, ts = _frame_cache
        if now - ts < _FRAME_CACHE_TTL_SEC:
            return frame.copy()

    async with _get_capture_lock():
        now = time.monotonic()
        if _frame_cache is not None:
            frame, ts = _frame_cache
            if now - ts < _FRAME_CACHE_TTL_SEC:
                return frame.copy()
        frame = await asyncio.to_thread(_capture_frame_sync)
        if frame is not None:
            _frame_cache = (frame, time.monotonic())
        return frame


async def detect_zone_in_frame(frame: np.ndarray, event_type: str) -> dict | None:
    """
    Use Claude vision to find the most safety-relevant object in a frame.
    Returns a zone dict with fractional coords (pct=True) or None if nothing found.
    """
    from app.services.cloudinary_service import frame_to_base64
    from app.services.claude_service import detect_objects_in_frame

    try:
        image_b64 = frame_to_base64(frame)
        objects = await detect_objects_in_frame(image_b64, event_type)
    except Exception as e:
        logger.warning(f"Claude vision detection failed: {e}")
        return None

    if not objects:
        logger.warning(f"Claude vision found nothing for event {event_type}")
        return None

    # Claude orders by safety relevance — take the top result
    obj = objects[0]
    obj_name = obj.get("name", "object").lower()
    logger.info(f"Claude vision detected '{obj_name}' for event {event_type}")
    return {
        "name": obj_name,
        "x": obj["x"],
        "y": obj["y"],
        "w": obj["w"],
        "h": obj["h"],
        "pct": True,
    }


async def get_zone_for_event(user_id: str, event_type: str, db) -> dict | None:
    """
    Look up the bounding box for the zone relevant to this event type.
    Falls back to stored MongoDB zones if dynamic detection is unavailable.
    """
    zone_name = EVENT_ZONE_MAP.get(event_type)
    if not zone_name:
        return None
    doc = await db.room_zones.find_one({"user_id": ObjectId(user_id)})
    if not doc:
        return None
    zone = doc.get("zones", {}).get(zone_name)
    if zone:
        zone["name"] = zone_name
    return zone


def _pixel_zone_to_fractional(zone: dict, frame: np.ndarray) -> dict:
    """Convert stored pixel bbox to 0–1 coords so Cloudinary fl_relative and voice_agent match."""
    h, w = frame.shape[0], frame.shape[1]
    if w <= 0 or h <= 0:
        return {**zone, "pct": False}
    return {
        "name": zone.get("name", "object"),
        "x": float(zone["x"]) / w,
        "y": float(zone["y"]) / h,
        "w": float(zone["w"]) / w,
        "h": float(zone["h"]) / h,
        "pct": True,
    }


async def get_zone_dynamic_or_fallback(
    frame: np.ndarray,
    user_id: str,
    event_type: str,
    db,
) -> dict | None:
    """
    Primary path: detect zone via Claude vision on the live frame.
    Fallback: MongoDB room_zones (pixels) → normalized to fractional so crop + VoiceAlert work.
    """
    zone = await detect_zone_in_frame(frame, event_type)
    if zone:
        zone["visual_verified"] = True
        return zone

    logger.info(f"Falling back to MongoDB zone for {event_type}")
    z = await get_zone_for_event(user_id, event_type, db)
    if not z:
        return None
    out = _pixel_zone_to_fractional(z, frame)
    out["visual_verified"] = False
    return out


async def detect_zone_in_frame_b64(image_b64: str, event_type: str) -> dict | None:
    """
    Browser-frame variant of detect_zone_in_frame — accepts base64 JPEG directly.
    Claude identifies whatever safety-relevant object is actually present.
    """
    from app.services.claude_service import detect_objects_in_frame

    try:
        objects = await detect_objects_in_frame(image_b64, event_type)
    except Exception as e:
        logger.warning(f"Claude vision detection failed: {e}")
        return None

    if not objects:
        logger.warning(f"Claude vision found nothing for event {event_type}")
        return None

    obj = objects[0]
    obj_name = obj.get("name", "object").lower()
    logger.info(f"Claude vision detected '{obj_name}' for event {event_type}")
    return {
        "name": obj_name,
        "x": obj["x"],
        "y": obj["y"],
        "w": obj["w"],
        "h": obj["h"],
        "pct": True,
    }


async def get_zone_dynamic_or_fallback_b64(
    image_b64: str,
    user_id: str,
    event_type: str,
    db,
) -> dict | None:
    """
    Browser-frame variant of get_zone_dynamic_or_fallback.
    Falls back to a full-frame crop when MongoDB pixel zones can't be normalized
    without image dimensions.
    """
    zone = await detect_zone_in_frame_b64(image_b64, event_type)
    if zone:
        zone["visual_verified"] = True
        return zone

    logger.info(f"Falling back to MongoDB zone for {event_type} (b64 path)")
    z = await get_zone_for_event(user_id, event_type, db)
    if not z:
        return None

    if z.get("pct"):
        z = {**z, "name": z.get("name", "object"), "visual_verified": False}
        return z

    # Pixel zones need frame dimensions to normalize; use full-frame crop as safe fallback
    return {
        "name": z.get("name", "object"),
        "x": 0.0,
        "y": 0.0,
        "w": 1.0,
        "h": 1.0,
        "pct": True,
        "visual_verified": False,
    }
