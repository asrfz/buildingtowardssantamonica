"""
cloudinary_service — Handles all Cloudinary image upload and transformation
for HomePulse alert images.

Encoding pipeline for every alert image:
    1. Raw JPEG upload  →  stored as homepulse/raw/{event_id}
    2. c_crop           →  cut to the exact zone bounding box
                           (fl_relative when coords are fractional 0–1,
                            pixel coords when sourced from MongoDB zones)
    3. e_sharpen:80     →  compensate for webcam softness / motion blur
    4. e_improve        →  Cloudinary's content-aware auto-enhancement
                           (adjusts brightness, contrast, saturation per image)
    5. q_auto           →  context-aware quality encoding: Cloudinary analyses
                           each image's visual complexity and picks the smallest
                           file size that retains perceived quality. A blurry
                           background gets lower quality; a sharp stove burner
                           gets higher quality. No manual quality knob needed.

Why q_auto matters here:
    Webcam frames vary wildly in quality — bright kitchen vs dim room, fast
    motion vs static scene. q_auto adapts per-image so alert thumbnails in
    emails are always crisp without wasting bandwidth on noisy frames.
"""

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


def _build_crop_transform(zone: dict) -> dict:
    """
    Build the Cloudinary crop transformation for a zone.

    If zone["pct"] is True, coordinates are fractions (0.0–1.0) from Claude
    vision detection — use fl_relative so Cloudinary interprets them correctly.

    Otherwise, coordinates are absolute pixels from MongoDB zone calibration.
    """
    if zone.get("pct"):
        return {
            "crop": "crop",
            "x": zone["x"],
            "y": zone["y"],
            "width": zone["w"],
            "height": zone["h"],
            "flags": "relative",    # tells Cloudinary coords are 0–1 fractions
        }
    return {
        "crop": "crop",
        "x": int(zone["x"]),
        "y": int(zone["y"]),
        "width": int(zone["w"]),
        "height": int(zone["h"]),
    }


def _upload_and_crop_sync(frame: np.ndarray, event_id: str, zone: dict) -> dict:
    _configure()

    _, buffer = cv2.imencode(".jpg", frame)
    raw = cloudinary.uploader.upload(
        buffer.tobytes(),
        public_id=f"homepulse/raw/{event_id}",
        resource_type="image",
        overwrite=True,
    )

    transformation = [
        _build_crop_transform(zone),
        {"effect": "sharpen:80"},   # compensate for webcam softness
        {"effect": "improve"},      # content-aware brightness/contrast boost
        {"quality": "auto"},        # context-aware encoding (see module docstring)
    ]

    cropped_url = cloudinary.utils.cloudinary_url(
        f"homepulse/raw/{event_id}",
        transformation=transformation,
    )[0]

    logger.info(f"Cloudinary upload complete for event {event_id} — zone={zone.get('name', '?')}")
    return {
        "raw_url": raw["secure_url"],
        "cropped_url": cropped_url,
        "width": raw.get("width"),
        "height": raw.get("height"),
        "public_id": raw.get("public_id", ""),
    }


def _upload_and_crop_from_b64_sync(image_b64: str, event_id: str, zone: dict) -> dict:
    """Upload a base64 JPEG from the browser (no OpenCV needed)."""
    _configure()
    image_bytes = base64.b64decode(image_b64)
    raw = cloudinary.uploader.upload(
        image_bytes,
        public_id=f"homepulse/raw/{event_id}",
        resource_type="image",
        overwrite=True,
    )
    transformation = [
        _build_crop_transform(zone),
        {"effect": "sharpen:80"},
        {"effect": "improve"},
        {"quality": "auto"},
    ]
    cropped_url = cloudinary.utils.cloudinary_url(
        f"homepulse/raw/{event_id}",
        transformation=transformation,
    )[0]
    logger.info(f"Cloudinary upload complete for event {event_id} — zone={zone.get('name', '?')}")
    return {
        "raw_url": raw["secure_url"],
        "cropped_url": cropped_url,
        "width": raw.get("width"),
        "height": raw.get("height"),
        "public_id": raw.get("public_id", ""),
    }


async def upload_and_crop_from_b64(image_b64: str, event_id: str, zone: dict) -> dict:
    """Async wrapper for the browser-frame upload path."""
    return await asyncio.to_thread(_upload_and_crop_from_b64_sync, image_b64, event_id, zone)


async def upload_and_crop(frame: np.ndarray, event_id: str, zone: dict) -> dict:
    """
    Upload a webcam frame to Cloudinary and return:
      raw_url    : full unmodified frame (for audit / monitor_agent context)
      cropped_url: zone-cropped + encoded image (for alert emails + voice agent)

    Cloudinary applies q_auto context-aware encoding on the cropped URL so the
    alert thumbnail is always optimal quality for the captured scene.
    """
    return await asyncio.to_thread(_upload_and_crop_sync, frame, event_id, zone)


def frame_to_base64(frame: np.ndarray) -> str:
    """
    Encode an OpenCV BGR frame as a base64 JPEG string for Claude vision API.
    Used by the voice correction loop — frames go directly to Claude without
    being uploaded to Cloudinary (no storage needed for transient guidance frames).
    """
    _, buffer = cv2.imencode(".jpg", frame)
    return base64.b64encode(buffer.tobytes()).decode("utf-8")
