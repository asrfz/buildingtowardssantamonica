import asyncio
import base64
import logging
import cloudinary
import cloudinary.uploader
import cloudinary.utils
import cv2
import numpy as np
from app.config import settings

logger = logging.getLogger(__name__)


def _configure() -> None:
    cloudinary.config(
        cloud_name=settings.CLOUDINARY_CLOUD_NAME,
        api_key=settings.CLOUDINARY_API_KEY,
        api_secret=settings.CLOUDINARY_API_SECRET,
    )


def _upload_and_crop_sync(frame: np.ndarray, event_id: str, zone: dict) -> dict:
    _configure()
    _, buffer = cv2.imencode(".jpg", frame)
    raw = cloudinary.uploader.upload(
        buffer.tobytes(),
        public_id=f"homepulse/raw/{event_id}",
        resource_type="image",
    )
    # Zone coords are pixel values; convert to percentage-based if flagged
    transform: list[dict] = []
    if zone.get("pct"):
        # Rekognition/Claude returns percentages — use w_/h_ with fl_relative
        transform.append({
            "crop": "crop",
            "x": zone["x"],
            "y": zone["y"],
            "width": zone["w"],
            "height": zone["h"],
            "flags": "relative",
        })
    else:
        transform.append({
            "crop": "crop",
            "x": int(zone["x"]),
            "y": int(zone["y"]),
            "width": int(zone["w"]),
            "height": int(zone["h"]),
        })

    transform += [
        {"effect": "sharpen:80"},
        {"effect": "improve"},
        {"quality": "auto"},  # context-aware encoding — adjusts quality per image content
    ]

    cropped_url = cloudinary.utils.cloudinary_url(
        f"homepulse/raw/{event_id}",
        transformation=transform,
    )[0]
    return {"raw_url": raw["secure_url"], "cropped_url": cropped_url}


async def upload_and_crop(frame: np.ndarray, event_id: str, zone: dict) -> dict:
    """Upload a frame to Cloudinary and return a crop-enhanced URL for the zone of interest."""
    return await asyncio.to_thread(_upload_and_crop_sync, frame, event_id, zone)


def frame_to_base64(frame: np.ndarray) -> str:
    """Encode an OpenCV frame as a base64 JPEG string for Claude vision."""
    _, buffer = cv2.imencode(".jpg", frame)
    return base64.b64encode(buffer.tobytes()).decode("utf-8")
