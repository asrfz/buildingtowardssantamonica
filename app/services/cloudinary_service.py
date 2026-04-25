import asyncio
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
    cropped_url = cloudinary.utils.cloudinary_url(
        f"homepulse/raw/{event_id}",
        transformation=[
            {
                "crop": "crop",
                "x": zone["x"],
                "y": zone["y"],
                "width": zone["w"],
                "height": zone["h"],
            },
            {"effect": "sharpen:80"},
            {"effect": "improve"},
        ],
    )[0]
    return {"raw_url": raw["secure_url"], "cropped_url": cropped_url}


async def upload_and_crop(frame: np.ndarray, event_id: str, zone: dict) -> dict:
    """Upload a frame to Cloudinary and return a crop-enhanced URL for the zone of interest."""
    return await asyncio.to_thread(_upload_and_crop_sync, frame, event_id, zone)
