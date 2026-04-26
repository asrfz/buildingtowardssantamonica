"""
Persist bureau camera frames (Cloudinary URLs + metadata) for caregiver / dev UI galleries.

Collection: camera_snapshots
  — preview: manual or periodic POST /sensor/preview-snapshot
  — vision: anomaly pipeline after upload_and_crop_from_b64
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger(__name__)

CAMERA_SNAPSHOTS_COLL = "camera_snapshots"


async def record_camera_snapshot(
    db: AsyncIOMotorDatabase,
    *,
    user_id: str,
    url: str,
    cropped_url: str = "",
    cropped_thumb_url: str = "",
    public_id: str = "",
    width: int | None = None,
    height: int | None = None,
    source: str,
    event_id: str | None = None,
    event_type: str = "",
) -> str | None:
    """
    Insert one snapshot document. Returns inserted_id as str, or None if user_id invalid.
    """
    try:
        oid = ObjectId(user_id)
    except Exception:
        logger.warning("camera_snapshot: invalid user_id %r", user_id)
        return None

    doc: dict = {
        "user_id": oid,
        "url": url,
        "cropped_url": cropped_url or "",
        "cropped_thumb_url": cropped_thumb_url or "",
        "public_id": public_id or "",
        "width": width,
        "height": height,
        "source": source,
        "event_type": event_type or "",
        "created_at": datetime.now(timezone.utc),
    }
    if event_id:
        try:
            doc["event_id"] = ObjectId(event_id)
        except Exception:
            doc["event_id"] = None
    else:
        doc["event_id"] = None

    result = await db[CAMERA_SNAPSHOTS_COLL].insert_one(doc)
    return str(result.inserted_id)


async def find_snapshot_for_event(
    db: AsyncIOMotorDatabase,
    *,
    user_id: str,
    event_id: str,
    source: str | None = "vision",
) -> dict | None:
    """Latest camera_snapshots row for this user+event (for dedup / retry without re-upload)."""
    try:
        uid = ObjectId(user_id)
        eid = ObjectId(event_id)
    except Exception:
        return None
    q: dict = {"user_id": uid, "event_id": eid}
    if source:
        q["source"] = source
    doc = await db[CAMERA_SNAPSHOTS_COLL].find_one(q, sort=[("created_at", -1)])
    if not doc:
        return None
    return {
        "url": doc.get("url", ""),
        "cropped_url": doc.get("cropped_url", ""),
        "cropped_thumb_url": doc.get("cropped_thumb_url", ""),
        "public_id": doc.get("public_id", ""),
        "width": doc.get("width"),
        "height": doc.get("height"),
    }
