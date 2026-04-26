from dataclasses import dataclass
from bson import ObjectId
from app.models.sensor import SensorPayload
from app.utils.severity import compute_severity
from app.services.baseline_stats import accel_magnitude_of, stat
from app.services.vector_service import (
    payload_to_embedding,
    store_sensor_vector,
    vector_anomaly_score,
    ANOMALY_SIMILARITY_THRESHOLD,
)
from app.services.threshold_service import get_user_thresholds, get_multiplier


@dataclass
class AnomalyResult:
    triggered: bool
    event_type: str = ""
    deviation_score: float = 0.0
    severity: str = "LOW"
    sensor: str = ""
    reason: str = ""


def _z_exceeds(
    value: float,
    mean: float,
    std: float,
    multiplier: float,
) -> tuple[bool, float]:
    if std <= 0:
        return False, 0.0
    dev = abs(value - mean)
    if dev <= multiplier * std:
        return False, 0.0
    return True, round(dev / std, 2)


async def score_reading(user_id: str, payload: SensorPayload, db) -> AnomalyResult:
    """
    Score a sensor reading against hourly baselines + firmware edge flags.

    Priority (first match wins):
      1) IMU edge flags → OBJECT_DROPPED
      2) Light step change (Arduino) → LIGHT_STATE_CHANGED
      3) Firmware sound / magnetic edge flags → SOUND_ANOMALY / DOOR_SENSOR_ANOMALY
      4) Per-channel z-scores: temperature, sound, ambient light level, pressure,
         acceleration magnitude, gyro magnitude, magnetic reed state
      5) Multivariate vector similarity
    """
    # ── Firmware instant triggers (no baseline required) ───────────────────
    if payload.drop_detected or payload.motion_triggered or payload.gyro_triggered:
        return AnomalyResult(
            triggered=True,
            event_type="OBJECT_DROPPED",
            deviation_score=4.5 if (payload.motion_triggered and payload.gyro_triggered) else 3.8,
            severity="MEDIUM",
            sensor="accelerometer",
            reason="arduino_imu_threshold",
        )

    if payload.light_change_detected:
        return AnomalyResult(
            triggered=True,
            event_type="LIGHT_STATE_CHANGED",
            deviation_score=3.0,
            severity="LOW",
            sensor="light",
            reason="arduino_light_step_delta",
        )

    if payload.sound_triggered:
        return AnomalyResult(
            triggered=True,
            event_type="SOUND_ANOMALY",
            deviation_score=3.6,
            severity="MEDIUM",
            sensor="sound",
            reason="arduino_sound_threshold",
        )

    if payload.magnetic_triggered:
        return AnomalyResult(
            triggered=True,
            event_type="DOOR_SENSOR_ANOMALY",
            deviation_score=3.7,
            severity="MEDIUM",
            sensor="magnetic",
            reason="arduino_magnetic_field_threshold",
        )

    hour = payload.timestamp.hour
    day_type = "weekend" if payload.timestamp.weekday() >= 5 else "weekday"

    baseline = await db.sensor_baselines.find_one({
        "user_id": ObjectId(user_id),
        "hour_of_day": hour,
        "day_type": day_type,
    })
    if not baseline:
        return AnomalyResult(triggered=False, reason="no_baseline")

    thresholds = await get_user_thresholds(user_id, db)
    embedding = payload_to_embedding(payload, baseline)

    # ── Z-score channels (each uses baseline_stats defaults if key missing) ─

    if payload.temperature_c is not None:
        t = stat(baseline, "temperature")
        ok, score = _z_exceeds(
            payload.temperature_c, t["mean"], t["std_dev"],
            get_multiplier(thresholds, "temperature_c"),
        )
        if ok:
            await store_sensor_vector(user_id, payload, embedding, is_anomaly=True, db=db)
            return AnomalyResult(
                triggered=True,
                event_type="TEMPERATURE_ANOMALY",
                deviation_score=score,
                severity=compute_severity(score),
                sensor="temperature",
                reason=f"temp={payload.temperature_c}°C vs baseline mean={t['mean']:.1f}",
            )

    s = stat(baseline, "sound_level")
    ok, score = _z_exceeds(
        float(payload.sound_level), s["mean"], s["std_dev"],
        get_multiplier(thresholds, "sound_level"),
    )
    if ok:
        await store_sensor_vector(user_id, payload, embedding, is_anomaly=True, db=db)
        return AnomalyResult(
            triggered=True,
            event_type="SOUND_ANOMALY",
            deviation_score=score,
            severity=compute_severity(score),
            sensor="sound",
            reason=f"sound={payload.sound_level} vs baseline mean={s['mean']:.1f}",
        )

    if payload.light_level is not None:
        ll = stat(baseline, "light_level")
        ok, score = _z_exceeds(
            float(payload.light_level), ll["mean"], ll["std_dev"],
            get_multiplier(thresholds, "light_level"),
        )
        if ok:
            await store_sensor_vector(user_id, payload, embedding, is_anomaly=True, db=db)
            return AnomalyResult(
                triggered=True,
                event_type="LIGHT_STATE_CHANGED",
                deviation_score=score,
                severity=compute_severity(score),
                sensor="light",
                reason=f"light_level={payload.light_level} vs baseline mean={ll['mean']:.0f}",
            )

    if payload.pressure is not None:
        p = stat(baseline, "pressure")
        ok, score = _z_exceeds(
            payload.pressure, p["mean"], p["std_dev"],
            get_multiplier(thresholds, "pressure"),
        )
        if ok:
            await store_sensor_vector(user_id, payload, embedding, is_anomaly=True, db=db)
            return AnomalyResult(
                triggered=True,
                event_type="MULTIVARIATE_ANOMALY",
                deviation_score=score,
                severity=compute_severity(score),
                sensor="pressure",
                reason=f"pressure={payload.pressure} vs baseline mean={p['mean']:.1f}",
            )

    am = stat(baseline, "accel_magnitude")
    accel_mag = accel_magnitude_of(payload)
    ok, score = _z_exceeds(
        accel_mag, am["mean"], am["std_dev"],
        get_multiplier(thresholds, "accel_magnitude"),
    )
    if ok:
        await store_sensor_vector(user_id, payload, embedding, is_anomaly=True, db=db)
        return AnomalyResult(
            triggered=True,
            event_type="OBJECT_DROPPED",
            deviation_score=score,
            severity=compute_severity(score),
            sensor="accelerometer",
            reason=f"accel_mag={accel_mag:.3f}g vs baseline mean={am['mean']:.3f}",
        )

    gm = stat(baseline, "gyro_magnitude")
    ok, score = _z_exceeds(
        payload.gyro_magnitude, gm["mean"], gm["std_dev"],
        get_multiplier(thresholds, "gyro_magnitude"),
    )
    if ok:
        await store_sensor_vector(user_id, payload, embedding, is_anomaly=True, db=db)
        return AnomalyResult(
            triggered=True,
            event_type="OBJECT_DROPPED",
            deviation_score=score,
            severity=compute_severity(score),
            sensor="gyroscope",
            reason=f"gyro_mag={payload.gyro_magnitude:.1f} vs baseline mean={gm['mean']:.1f}",
        )

    mag_mean = stat(baseline, "magnetic_state")["mean"]
    if payload.magnetic_state != round(mag_mean) and payload.magnetic_state == 1:
        await store_sensor_vector(user_id, payload, embedding, is_anomaly=True, db=db)
        return AnomalyResult(
            triggered=True,
            event_type="DOOR_SENSOR_ANOMALY",
            deviation_score=4.0,
            severity="MEDIUM",
            sensor="magnetic",
            reason="magnetic_state changed — door or enclosure opened",
        )

    similarity = await vector_anomaly_score(user_id, embedding, db)
    if similarity < ANOMALY_SIMILARITY_THRESHOLD:
        deviation = round((1.0 - similarity) * 20, 2)
        await store_sensor_vector(user_id, payload, embedding, is_anomaly=True, db=db)
        return AnomalyResult(
            triggered=True,
            event_type="MULTIVARIATE_ANOMALY",
            deviation_score=deviation,
            severity=compute_severity(deviation),
            sensor="vector",
            reason=f"vector_similarity={similarity:.3f}",
        )

    await store_sensor_vector(user_id, payload, embedding, is_anomaly=False, db=db)
    return AnomalyResult(triggered=False)
