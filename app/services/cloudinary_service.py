"""
cloudinary_service — Handles all Cloudinary image upload and transformation
for HomePulse alert images.

Encoding pipeline for every alert image:
    1. Raw JPEG upload  →  stored as homepulse/raw/{event_id} (tags: homepulse, evt_…, optional uid/type)
    2. c_crop           →  zone bounding box (fl_relative when coords are 0–1)
    3. Post-crop        →  either CLOUDINARY_NAMED_TRANSFORM_POSTCROP or:
                           e_sharpen:80 → e_improve → q_auto → f_auto → dpr_auto
    4. Thumbnail URL    →  same crop + inline sharpen + c_limit,w_MAX + improve + q_auto + f_auto + dpr_auto
                           (inline thumb chain even when primary uses a named transform)

See pitch/cloudinary.md for the feature checklist (#cloudinary-feature-index).
"""

import asyncio
import base64
import logging
import re
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


def _sanitize_tag_part(s: str, max_len: int = 48) -> str:
    """Cloudinary tags: alphanumeric, hyphen, underscore; collapse junk."""
    t = re.sub(r"[^a-zA-Z0-9_-]+", "_", (s or "").strip())[:max_len]
    return t or "unknown"


def _upload_tags(event_id: str, user_id: str = "", event_type: str = "") -> str:
    parts = ["homepulse", "alert", f"evt_{_sanitize_tag_part(event_id, 32)}"]
    if user_id:
        parts.append(f"uid_{_sanitize_tag_part(user_id, 24)}")
    if event_type:
        parts.append(f"type_{_sanitize_tag_part(event_type, 20)}")
    return ",".join(parts)


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


def _delivery_optimize_tail(*, with_dpr: bool = True) -> list[dict]:
    """Enhancement + auto quality + auto format (+ device pixel ratio for caregiver-facing URLs)."""
    tail: list[dict] = [
        {"effect": "improve"},
        {"quality": "auto"},
        {"fetch_format": "auto"},
    ]
    if with_dpr:
        tail.append({"dpr": "auto"})
    return tail


def _postcrop_effects_named_or_inline() -> list[dict]:
    name = (settings.CLOUDINARY_NAMED_TRANSFORM_POSTCROP or "").strip()
    if name:
        return [{"transformation": name}]
    return [
        {"effect": "sharpen:80"},
        *_delivery_optimize_tail(with_dpr=True),
    ]


def _crop_transformation_chain_alert_full(zone: dict) -> list[dict]:
    return [
        _build_crop_transform(zone),
        *_postcrop_effects_named_or_inline(),
    ]


def _crop_transformation_chain_alert_thumb(zone: dict) -> list[dict]:
    """Smaller bytes for email and gallery tiles; always uses inline post-limit pipeline."""
    w = max(64, min(2048, int(settings.CLOUDINARY_ALERT_THUMB_MAX_WIDTH)))
    return [
        _build_crop_transform(zone),
        {"effect": "sharpen:80"},
        {"width": w, "crop": "limit"},
        *_delivery_optimize_tail(with_dpr=True),
    ]


def _upload_sync(
    image_bytes: bytes,
    event_id: str,
    zone: dict,
    *,
    user_id: str = "",
    event_type: str = "",
) -> dict:
    _configure()
    tags = _upload_tags(event_id, user_id, event_type)
    raw = cloudinary.uploader.upload(
        image_bytes,
        public_id=f"homepulse/raw/{event_id}",
        resource_type="image",
        overwrite=True,
        tags=tags,
    )
    pid = f"homepulse/raw/{event_id}"
    chain_full = _crop_transformation_chain_alert_full(zone)
    chain_thumb = _crop_transformation_chain_alert_thumb(zone)

    cropped_url = cloudinary.utils.cloudinary_url(pid, transformation=chain_full)[0]
    cropped_thumb_url = cloudinary.utils.cloudinary_url(pid, transformation=chain_thumb)[0]

    logger.info(
        "Cloudinary upload complete for event %s — zone=%s tags=%s",
        event_id,
        zone.get("name", "?"),
        tags,
    )
    return {
        "raw_url": raw["secure_url"],
        "cropped_url": cropped_url,
        "cropped_thumb_url": cropped_thumb_url,
        "width": raw.get("width"),
        "height": raw.get("height"),
        "public_id": raw.get("public_id", pid),
    }


def _upload_and_crop_sync(
    frame: np.ndarray,
    event_id: str,
    zone: dict,
    *,
    user_id: str = "",
    event_type: str = "",
) -> dict:
    _, buffer = cv2.imencode(".jpg", frame)
    return _upload_sync(
        buffer.tobytes(),
        event_id,
        zone,
        user_id=user_id,
        event_type=event_type,
    )


def _upload_and_crop_from_b64_sync(
    image_b64: str,
    event_id: str,
    zone: dict,
    *,
    user_id: str = "",
    event_type: str = "",
) -> dict:
    image_bytes = base64.b64decode(image_b64)
    return _upload_sync(
        image_bytes,
        event_id,
        zone,
        user_id=user_id,
        event_type=event_type,
    )


def destroy_event_raw_image_sync(event_id: str) -> bool:
    """
    Remove the alert raw asset homepulse/raw/{event_id} from Cloudinary.
    Returns True if API reports ok or not_found (already gone).
    """
    if not settings.CLOUDINARY_CLOUD_NAME or not settings.CLOUDINARY_API_KEY:
        return False
    _configure()
    public_id = f"homepulse/raw/{event_id}"
    try:
        res = cloudinary.uploader.destroy(public_id, resource_type="image", invalidate=True)
        result = (res.get("result") or "").lower()
        ok = result in ("ok", "not found")
        if ok:
            logger.info("Cloudinary destroy %s → %s", public_id, result)
        else:
            logger.warning("Cloudinary destroy %s → %s", public_id, res)
        return ok
    except Exception as exc:
        logger.warning("Cloudinary destroy failed for %s: %s", public_id, exc)
        return False


async def destroy_event_raw_image(event_id: str) -> bool:
    return await asyncio.to_thread(destroy_event_raw_image_sync, event_id)


async def upload_and_crop_from_b64(
    image_b64: str,
    event_id: str,
    zone: dict,
    *,
    user_id: str = "",
    event_type: str = "",
) -> dict:
    """Async wrapper for the browser-frame upload path."""
    return await asyncio.to_thread(
        _upload_and_crop_from_b64_sync,
        image_b64,
        event_id,
        zone,
        user_id=user_id,
        event_type=event_type,
    )


async def upload_and_crop(
    frame: np.ndarray,
    event_id: str,
    zone: dict,
    *,
    user_id: str = "",
    event_type: str = "",
) -> dict:
    """
    Upload a webcam frame to Cloudinary and return:
      raw_url           : full unmodified frame (audit / monitor_agent)
      cropped_url       : zone crop + caregiver delivery chain (Claude reasoning, UI, TTS context)
      cropped_thumb_url : same crop, width-limited + same optimizations (email, dense lists)
    """
    return await asyncio.to_thread(
        _upload_and_crop_sync,
        frame,
        event_id,
        zone,
        user_id=user_id,
        event_type=event_type,
    )


def frame_to_base64(frame: np.ndarray) -> str:
    """
    Encode an OpenCV BGR frame as a base64 JPEG string for Claude vision API.
    Used by the voice correction loop — frames go directly to Claude without
    being uploaded to Cloudinary (no storage needed for transient guidance frames).
    """
    _, buffer = cv2.imencode(".jpg", frame)
    return base64.b64encode(buffer.tobytes()).decode("utf-8")
