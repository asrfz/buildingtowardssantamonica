import asyncio
import logging
import numpy as np
import cv2
from bson import ObjectId
from app.config import settings

logger = logging.getLogger(__name__)

# Map event types to the zone they should crop
EVENT_ZONE_MAP: dict[str, str] = {
    "STOVE_LEFT_ON": "stove",
    "IRON_LEFT_ON": "stove",
    "FIRE_RISK": "stove",
    "FAUCET_RUNNING": "sink",
    "WATER_DRIPPING": "sink",
    "FRIDGE_OPEN": "fridge",
    "APPLIANCE_FAULT": "stove",
    "FALL_DETECTED": "stove",   # fallback — no dedicated zone
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


async def get_zone_for_event(user_id: str, event_type: str, db) -> dict | None:
    """Look up the bounding box for the zone relevant to this event type."""
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
