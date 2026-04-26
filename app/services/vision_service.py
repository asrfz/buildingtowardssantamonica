import asyncio
import logging
import numpy as np
import cv2
from bson import ObjectId
from app.config import settings

logger = logging.getLogger(__name__)


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


def _capture_frame_sync() -> np.ndarray | None:
    cap = cv2.VideoCapture(settings.WEBCAM_INDEX)
    if not cap.isOpened():
        return None
    ret, frame = cap.read()
    cap.release()
    return frame if ret else None


async def capture_frame() -> np.ndarray | None:
    """Capture a single frame from the webcam. Returns None if webcam unavailable."""
    return await asyncio.to_thread(_capture_frame_sync)


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
        return zone

    logger.info(f"Falling back to MongoDB zone for {event_type}")
    z = await get_zone_for_event(user_id, event_type, db)
    if not z:
        return None
    return _pixel_zone_to_fractional(z, frame)


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
        return zone

    logger.info(f"Falling back to MongoDB zone for {event_type} (b64 path)")
    z = await get_zone_for_event(user_id, event_type, db)
    if not z:
        return None

    if z.get("pct"):
        z["name"] = z.get("name", "object")
        return z

    # Pixel zones need frame dimensions to normalize; use full-frame crop as safe fallback
    return {"name": z.get("name", "object"), "x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0, "pct": True}
