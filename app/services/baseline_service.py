import logging
from datetime import datetime
from bson import ObjectId
from app.models.sensor import SensorPayload

logger = logging.getLogger(__name__)


async def update_running_stats(
    user_id: str,
    payload: SensorPayload,
    db,
) -> None:
    """
    Incrementally update sensor baselines using Welford's online algorithm.
    Called after every confirmed (non-false-positive) event so baselines stay current.
    """
    hour = payload.timestamp.hour
    day_type = "weekend" if payload.timestamp.weekday() >= 5 else "weekday"

    baseline = await db.sensor_baselines.find_one({
        "user_id": ObjectId(user_id),
        "hour_of_day": hour,
        "day_type": day_type,
    })
    if not baseline:
        logger.warning(f"No baseline found for user {user_id} hour={hour} day_type={day_type}")
        return

    def welford_update(mean: float, std_dev: float, new_val: float, n: int = 100) -> tuple:
        """Approximate Welford update assuming a rolling window of n samples."""
        delta = new_val - mean
        new_mean = mean + delta / n
        new_std = max(std_dev * 0.99, abs(delta) * 0.01)  # decay toward observed
        return round(new_mean, 4), round(new_std, 4)

    new_temp_mean, new_temp_std = welford_update(
        baseline["temperature"]["mean"],
        baseline["temperature"]["std_dev"],
        payload.temperature_c,
    )
    new_sound_mean, new_sound_std = welford_update(
        baseline["sound_level"]["mean"],
        baseline["sound_level"]["std_dev"],
        float(payload.sound_level),
    )

    await db.sensor_baselines.update_one(
        {"_id": baseline["_id"]},
        {
            "$set": {
                "temperature.mean": new_temp_mean,
                "temperature.std_dev": new_temp_std,
                "sound_level.mean": new_sound_mean,
                "sound_level.std_dev": new_sound_std,
                "updated_at": datetime.utcnow(),
            }
        },
    )
    logger.debug(f"Baseline updated for user {user_id} hour={hour}")


async def get_baseline(user_id: str, hour: int, day_type: str, db) -> dict | None:
    return await db.sensor_baselines.find_one({
        "user_id": ObjectId(user_id),
        "hour_of_day": hour,
        "day_type": day_type,
    })
