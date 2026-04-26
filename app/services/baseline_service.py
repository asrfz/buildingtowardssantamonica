import logging
from datetime import datetime
from bson import ObjectId
from app.models.sensor import SensorPayload
from app.services.baseline_stats import accel_magnitude_of

logger = logging.getLogger(__name__)


async def update_running_stats(
    user_id: str,
    payload: SensorPayload,
    db,
) -> None:
    """
    Incrementally update sensor baselines using Welford's online algorithm.
    Called after every confirmed (non-false-positive) event so baselines stay current.
    Skips channels that were not measured (None) so we don't train on placeholders.
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
        delta = new_val - mean
        new_mean = mean + delta / n
        new_std = max(std_dev * 0.99, abs(delta) * 0.01)
        return round(new_mean, 4), round(new_std, 4)

    new_sound_mean, new_sound_std = welford_update(
        baseline["sound_level"]["mean"],
        baseline["sound_level"]["std_dev"],
        float(payload.sound_level),
    )

    set_doc: dict = {
        "sound_level.mean": new_sound_mean,
        "sound_level.std_dev": new_sound_std,
        "updated_at": datetime.utcnow(),
    }

    if payload.temperature_c is not None:
        nt, ns = welford_update(
            baseline["temperature"]["mean"],
            baseline["temperature"]["std_dev"],
            payload.temperature_c,
        )
        set_doc["temperature.mean"] = nt
        set_doc["temperature.std_dev"] = ns

    if payload.light_level is not None:
        ll = baseline.get("light_level") or {"mean": 450.0, "std_dev": 120.0}
        nl, ns = welford_update(
            float(ll["mean"]), float(ll["std_dev"]), float(payload.light_level)
        )
        set_doc["light_level.mean"] = nl
        set_doc["light_level.std_dev"] = ns

    gm = baseline.get("gyro_magnitude") or {"mean": 8.0, "std_dev": 25.0}
    ng, gs = welford_update(
        float(gm["mean"]), float(gm["std_dev"]), float(payload.gyro_magnitude)
    )
    set_doc["gyro_magnitude.mean"] = ng
    set_doc["gyro_magnitude.std_dev"] = gs

    am = baseline.get("accel_magnitude") or {"mean": 1.0, "std_dev": 0.18}
    mag = accel_magnitude_of(payload)
    na, as_ = welford_update(float(am["mean"]), float(am["std_dev"]), mag)
    set_doc["accel_magnitude.mean"] = na
    set_doc["accel_magnitude.std_dev"] = as_

    if payload.pressure is not None:
        pr = baseline.get("pressure") or {"mean": 1013.0, "std_dev": 2.0}
        np, ps = welford_update(
            float(pr["mean"]), float(pr["std_dev"]), float(payload.pressure)
        )
        set_doc["pressure.mean"] = np
        set_doc["pressure.std_dev"] = ps

    mg = baseline.get("magnetic_state") or {"mean": 0.0, "std_dev": 0.1}
    nm, ms = welford_update(
        float(mg["mean"]), float(mg["std_dev"]), float(payload.magnetic_state)
    )
    set_doc["magnetic_state.mean"] = nm
    set_doc["magnetic_state.std_dev"] = ms

    await db.sensor_baselines.update_one({"_id": baseline["_id"]}, {"$set": set_doc})
    logger.debug(f"Baseline updated for user {user_id} hour={hour}")


async def get_baseline(user_id: str, hour: int, day_type: str, db) -> dict | None:
    return await db.sensor_baselines.find_one({
        "user_id": ObjectId(user_id),
        "hour_of_day": hour,
        "day_type": day_type,
    })
