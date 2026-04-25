import asyncio
import logging
import numpy as np
import cv2
from bson import ObjectId
from app.config import settings

logger = logging.getLogger(__name__)

# Maps event types to the object name Claude should find in the frame
EVENT_OBJECT_MAP: dict[str, str] = {
    "STOVE_LEFT_ON": "stove",
    "IRON_LEFT_ON": "iron",
    "FIRE_RISK": "stove",
    "FAUCET_RUNNING": "sink",
    "WATER_DRIPPING": "sink",
    "FRIDGE_OPEN": "fridge",
    "APPLIANCE_FAULT": "stove",
    "FALL_DETECTED": "stove",
}

# Fallback zone name for MongoDB lookup (same as before)
EVENT_ZONE_MAP: dict[str, str] = {
    "STOVE_LEFT_ON": "stove",
    "IRON_LEFT_ON": "stove",
    "FIRE_RISK": "stove",
    "FAUCET_RUNNING": "sink",
    "WATER_DRIPPING": "sink",
    "FRIDGE_OPEN": "fridge",
    "APPLIANCE_FAULT": "stove",
    "FALL_DETECTED": "stove",
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
    Use Claude vision to find the relevant object in a frame.
    Returns a zone dict with fractional coords (pct=True) or None if not found.
    Caches the result to MongoDB for faster future lookups.
    """
    from app.services.cloudinary_service import frame_to_base64
    from app.services.claude_service import detect_objects_in_frame

    target = EVENT_OBJECT_MAP.get(event_type)
    if not target:
        return None

    try:
        image_b64 = frame_to_base64(frame)
        objects = await detect_objects_in_frame(image_b64)
    except Exception as e:
        logger.warning(f"Claude vision detection failed: {e}")
        return None

    # Find best match — exact name or prefix match (e.g. "fridge" matches "fridge door")
    for obj in objects:
        name = obj.get("name", "").lower()
        if name == target or name.startswith(target) or target in name:
            logger.info(f"Claude vision detected '{name}' for event {event_type}")
            return {
                "name": target,
                "x": obj["x"],
                "y": obj["y"],
                "w": obj["w"],
                "h": obj["h"],
                "pct": True,  # signal to Cloudinary service to use fl_relative
            }

    logger.warning(f"Claude vision could not find '{target}' for event {event_type}")
    return None


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
