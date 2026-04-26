"""
Cloudinary Admin API helpers for the caregiver UI — tags, colors, faces metadata.
Requires CLOUDINARY_* in .env (same as uploads).
"""

from __future__ import annotations

import logging

import cloudinary
import cloudinary.api
from fastapi import APIRouter, HTTPException, Query

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


def _configure() -> None:
    cloudinary.config(
        cloud_name=settings.CLOUDINARY_CLOUD_NAME,
        api_key=settings.CLOUDINARY_API_KEY,
        api_secret=settings.CLOUDINARY_API_SECRET,
    )


@router.get("/resource")
async def cloudinary_resource(
    public_id: str = Query(..., description="Asset public_id, e.g. homepulse/raw/<event_id>"),
) -> dict:
    """
    Return tags, context, colors, optional faces — powers “AI tagging” strip in the frontend.
    Tags include upload-time tags; enable Cloudinary auto-tagging / AI Content Analysis for richer tags.
    """
    if not settings.CLOUDINARY_CLOUD_NAME or not settings.CLOUDINARY_API_KEY or not settings.CLOUDINARY_API_SECRET:
        raise HTTPException(status_code=503, detail="Cloudinary Admin API not configured")
    pid = public_id.strip()
    if not pid:
        raise HTTPException(status_code=400, detail="public_id required")
    _configure()
    try:
        r = cloudinary.api.resource(
            pid,
            resource_type="image",
            colors=True,
            image_metadata=True,
            faces=True,
        )
    except Exception as e:
        logger.info("cloudinary.api.resource failed for %s: %s", pid[:48], e)
        raise HTTPException(status_code=404, detail=str(e)) from e

    colors = r.get("colors") or []
    if colors and isinstance(colors[0], (list, tuple)) and len(colors[0]) >= 2:
        colors_out = [{"color": c[0], "score": c[1]} for c in colors[:12]]
    else:
        colors_out = []

    return {
        "public_id": r.get("public_id"),
        "tags": r.get("tags") or [],
        "context": r.get("context") or {},
        "colors": colors_out,
        "width": r.get("width"),
        "height": r.get("height"),
        "bytes": r.get("bytes"),
        "faces": r.get("faces"),
        "moderation": r.get("moderation"),
    }
