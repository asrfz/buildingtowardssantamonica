import logging
from datetime import datetime, timedelta
from bson import ObjectId

from app.config import settings

logger = logging.getLogger(__name__)


async def record_outcome(event_id: str, confirmed: bool, db) -> None:
    """Mark an event as confirmed or false positive and update behavioral schema."""
    event = await db.events.find_one({"_id": ObjectId(event_id)})
    if not event:
        logger.warning(f"record_outcome: event {event_id} not found")
        return

    await db.events.update_one(
        {"_id": ObjectId(event_id)},
        {
            "$set": {
                "confirmed": confirmed,
                "resolved_at": datetime.utcnow(),
                "status": "confirmed" if confirmed else "false_positive",
            }
        },
    )

    user_id = event["user_id"]
    event_type = event["event_type"]
    await _update_false_positive_rate(str(user_id), event_type, confirmed, db)

    if confirmed:
        from app.services.baseline_service import update_running_stats
        from app.models.sensor import SensorPayload
        try:
            payload = SensorPayload(**event["sensor_payload"])
            await update_running_stats(str(user_id), payload, db)
        except Exception as e:
            logger.error(f"Baseline update failed: {e}")
    elif settings.CLOUDINARY_DESTROY_ON_FALSE_POSITIVE:
        try:
            from app.services.cloudinary_service import destroy_event_raw_image

            ok = await destroy_event_raw_image(event_id)
            if ok:
                logger.info("Cloudinary asset removed for false positive event %s", event_id[:12])
        except Exception as e:
            logger.warning("Cloudinary destroy skipped or failed for %s: %s", event_id[:12], e)


async def _update_false_positive_rate(
    user_id: str, event_type: str, confirmed: bool, db
) -> None:
    schema = await db.behavioral_schema.find_one({"user_id": ObjectId(user_id)})
    if not schema:
        return

    history = schema.get("event_type_history", {})
    entry = history.get(event_type, {"total": 0, "false_positives": 0, "false_positive_rate": 0.2})

    entry["total"] = entry.get("total", 0) + 1
    if not confirmed:
        entry["false_positives"] = entry.get("false_positives", 0) + 1

    total = entry["total"]
    fps = entry["false_positives"]
    entry["false_positive_rate"] = round(fps / total, 3) if total > 0 else 0.2
    history[event_type] = entry

    await db.behavioral_schema.update_one(
        {"user_id": ObjectId(user_id)},
        {"$set": {"event_type_history": history, "updated_at": datetime.utcnow()}},
    )


async def adjust_threshold(user_id: str, event_type: str, db) -> None:
    """
    Tighten or loosen threshold_multiplier based on false positive rate.
    High FP rate → loosen (raise multiplier). Low FP rate → tighten (lower multiplier).
    """
    schema = await db.behavioral_schema.find_one({"user_id": ObjectId(user_id)})
    if not schema:
        return

    fp_rate = (
        schema.get("event_type_history", {})
        .get(event_type, {})
        .get("false_positive_rate", 0.2)
    )

    user = await db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        return

    current = user.get("threshold_multiplier", 2.5)
    if fp_rate > 0.5:
        new_multiplier = min(current + 0.1, 5.0)   # too many FPs — loosen
    elif fp_rate < 0.1:
        new_multiplier = max(current - 0.05, 1.5)  # very accurate — tighten slightly
    else:
        return

    await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"threshold_multiplier": round(new_multiplier, 2)}},
    )
    logger.info(
        f"Threshold for user {user_id} adjusted: {current:.2f} → {new_multiplier:.2f} "
        f"(event_type={event_type}, fp_rate={fp_rate:.0%})"
    )


async def refresh_behavioral_schema(user_id: str, db) -> None:
    """
    Recompute full behavioral schema from last 30 days of events.
    Called by learning_agent on its 24h schedule.
    """
    cutoff = datetime.utcnow() - timedelta(days=30)
    events = await db.events.find({
        "user_id": ObjectId(user_id),
        "detected_at": {"$gte": cutoff},
    }).to_list(500)

    history: dict = {}
    for event in events:
        et = event.get("event_type", "UNKNOWN")
        entry = history.setdefault(et, {"total": 0, "false_positives": 0})
        entry["total"] += 1
        if event.get("confirmed") is False:
            entry["false_positives"] += 1

    for et, entry in history.items():
        total = entry["total"]
        fps = entry["false_positives"]
        entry["false_positive_rate"] = round(fps / total, 3) if total > 0 else 0.2

    await db.behavioral_schema.update_one(
        {"user_id": ObjectId(user_id)},
        {
            "$set": {
                "event_type_history": history,
                "updated_at": datetime.utcnow(),
            }
        },
        upsert=True,
    )
    logger.info(f"Behavioral schema refreshed for user {user_id} — {len(history)} event types")
