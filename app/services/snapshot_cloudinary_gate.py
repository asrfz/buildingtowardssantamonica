"""
Rate-limit Cloudinary snapshot uploads per user: one upload credit per triage that
investigates. Vision and POST /sensor/preview-snapshot consume the same pool so
bursts of pipeline retries or manual saves do not stack uploads before the next anomaly.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config import settings

logger = logging.getLogger(__name__)

GATE_COLL = "snapshot_cloudinary_gate"


async def grant_upload_slot(db: AsyncIOMotorDatabase, user_id: str) -> None:
    """Call when triage confirms investigate=True — allows the next Cloudinary snapshot for this user."""
    if not settings.SNAPSHOT_CLOUDINARY_GATE_ENABLED:
        return
    try:
        oid = ObjectId(user_id)
    except Exception:
        logger.warning("snapshot_gate grant: invalid user_id %r", user_id)
        return
    now = datetime.now(timezone.utc)
    await db[GATE_COLL].update_one(
        {"user_id": oid},
        {
            "$inc": {"pending_slots": 1},
            "$set": {"updated_at": now},
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    logger.info("snapshot_gate: granted 1 upload slot user=%s…", user_id[:12])


async def try_consume_upload_slot(db: AsyncIOMotorDatabase, user_id: str) -> bool:
    """
    Atomically consume one slot if pending_slots > 0.
    Returns True if this caller may proceed with Cloudinary upload.
    """
    if not settings.SNAPSHOT_CLOUDINARY_GATE_ENABLED:
        return True
    try:
        oid = ObjectId(user_id)
    except Exception:
        return False
    now = datetime.now(timezone.utc)
    prev = await db[GATE_COLL].find_one_and_update(
        {"user_id": oid, "pending_slots": {"$gt": 0}},
        {"$inc": {"pending_slots": -1}, "$set": {"updated_at": now}},
    )
    if prev is not None:
        logger.info(
            "snapshot_gate: consumed slot user=%s… remaining≈%s",
            user_id[:12],
            int(prev.get("pending_slots", 1)) - 1,
        )
        return True
    logger.info("snapshot_gate: no slot to consume user=%s… — skipping Cloudinary upload", user_id[:12])
    return False


async def refund_upload_slot(db: AsyncIOMotorDatabase, user_id: str) -> None:
    """Restore one slot after a reserved upload failed (e.g. Cloudinary error)."""
    if not settings.SNAPSHOT_CLOUDINARY_GATE_ENABLED:
        return
    try:
        oid = ObjectId(user_id)
    except Exception:
        return
    now = datetime.now(timezone.utc)
    await db[GATE_COLL].update_one(
        {"user_id": oid},
        {"$inc": {"pending_slots": 1}, "$set": {"updated_at": now}},
    )
    logger.info("snapshot_gate: refunded 1 slot user=%s…", user_id[:12])
