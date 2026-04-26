from dataclasses import dataclass, field
from bson import ObjectId
from app.models.sensor import SensorPayload
from app.utils.severity import compute_severity


@dataclass
class AnomalyResult:
    triggered: bool
    event_type: str = ""
    deviation_score: float = 0.0
    severity: str = "LOW"
    sensor: str = ""
    reason: str = ""


async def score_reading(user_id: str, payload: SensorPayload, db) -> AnomalyResult:
    # Hard threshold path from Arduino triggers (real-time edge events).
    if payload.drop_detected or (payload.motion_triggered and payload.gyro_triggered):
        return AnomalyResult(
            triggered=True,
            event_type="OBJECT_DROPPED",
            deviation_score=4.5,
            severity="MEDIUM",
            sensor="accelerometer",
            reason="arduino_threshold_drop",
        )

    if payload.light_change_detected:
        return AnomalyResult(
            triggered=True,
            event_type="LIGHT_STATE_CHANGED",
            deviation_score=3.0,
            severity="LOW",
            sensor="light",
            reason="arduino_threshold_light_delta",
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

    user = await db.users.find_one({"_id": ObjectId(user_id)})
    multiplier = (user or {}).get("threshold_multiplier", 2.5)

    # Temperature check
    temp_mean = baseline["temperature"]["mean"]
    temp_std = baseline["temperature"]["std_dev"]
    temp_dev = abs(payload.temperature_c - temp_mean)
    if temp_dev > multiplier * temp_std:
        score = round(temp_dev / temp_std, 2)
        return AnomalyResult(
            triggered=True,
            event_type=_classify_temp_event(payload),
            deviation_score=score,
            severity=compute_severity(score),
            sensor="temperature",
        )

    # Sound check
    sound_mean = baseline["sound_level"]["mean"]
    sound_std = baseline["sound_level"]["std_dev"]
    sound_dev = abs(payload.sound_level - sound_mean)
    if sound_dev > multiplier * sound_std:
        score = round(sound_dev / sound_std, 2)
        return AnomalyResult(
            triggered=True,
            event_type=_classify_sound_event(payload),
            deviation_score=score,
            severity=compute_severity(score),
            sensor="sound",
        )

    # Magnetic check (door open)
    mag_mean = baseline["magnetic_state"]["mean"]
    if payload.magnetic_state != round(mag_mean) and payload.magnetic_state == 1:
        return AnomalyResult(
            triggered=True,
            event_type="FRIDGE_OPEN",
            deviation_score=4.0,
            severity="MEDIUM",
            sensor="magnetic",
        )

    return AnomalyResult(triggered=False)


def _classify_temp_event(payload: SensorPayload) -> str:
    accel_mag = (payload.accel_x ** 2 + payload.accel_y ** 2 + payload.accel_z ** 2) ** 0.5
    if accel_mag < 0.5:
        return "STOVE_LEFT_ON" if payload.temperature_c > 40 else "IRON_LEFT_ON"
    return "FIRE_RISK"


def _classify_sound_event(payload: SensorPayload) -> str:
    if 300 < payload.sound_level < 500:
        return "FAUCET_RUNNING"
    if payload.sound_level < 300:
        return "WATER_DRIPPING"
    return "APPLIANCE_FAULT"
