"""
Per-user dynamic threshold service.

Stores and retrieves personalized sensor thresholds in the user_thresholds
collection. Every threshold value is computed from — or seeded to match —
that specific user's actual household behavior.

This replaces the global THRESHOLD_MULTIPLIER=2.5 constant. Two users with
the same raw sensor reading can have completely different anomaly verdicts:

  User A (Margaret, dim bulbs): light_level=200 → lights are ON
  User B (John, bright bulbs):  light_level=200 → lights are OFF

Collection: user_thresholds
  user_id, thresholds: { sensor_field: { low, high, alert_high, multiplier } },
  source: "seeded" | "computed", updated_at

MongoDB features used:
  - find_one with ObjectId filter
  - upsert for threshold updates
  - Compound index on (user_id, updated_at)
"""
from datetime import datetime
from bson import ObjectId

# Fallback global thresholds when no per-user record exists
_GLOBAL_DEFAULTS = {
    "temperature_c": {
        "idle_min":    15.0,
        "idle_max":    26.0,
        "alert_high":  35.0,
        "alert_low":   10.0,
        "multiplier":  2.5,
    },
    "sound_level": {
        "sleep_max":       200,
        "activity_min":    220,
        "alert_high":      700,
        "multiplier":      2.8,
    },
    "light_level": {
        "lights_off_max":  150,
        "lights_on_min":   300,
        "multiplier":      3.0,
    },
    "pressure": {
        "idle_min":    1000.0,
        "idle_max":    1025.0,
        "alert_low":   990.0,
        "multiplier":  3.0,
    },
    "magnetic_state": {
        "normal":      0,
        "alert":       1,
    },
}


async def get_user_thresholds(user_id: str, db) -> dict:
    """
    Returns the threshold dict for this user.
    Falls back to global defaults if no per-user record exists.
    """
    doc = await db.user_thresholds.find_one({"user_id": ObjectId(user_id)})
    if doc and doc.get("thresholds"):
        return doc["thresholds"]
    return _GLOBAL_DEFAULTS


async def upsert_user_thresholds(user_id: str, thresholds: dict, db, source: str = "computed") -> None:
    await db.user_thresholds.update_one(
        {"user_id": ObjectId(user_id)},
        {
            "$set": {
                "thresholds": thresholds,
                "source": source,
                "updated_at": datetime.utcnow(),
            }
        },
        upsert=True,
    )


def get_multiplier(thresholds: dict, sensor: str) -> float:
    return float(thresholds.get(sensor, {}).get("multiplier", 2.5))


def is_light_anomaly(light_level: int, thresholds: dict) -> str | None:
    """
    Returns event type if the light reading crosses a per-user threshold, else None.
    This is the key personalization: what counts as 'lights off' differs per user.
    """
    lt = thresholds.get("light_level", _GLOBAL_DEFAULTS["light_level"])
    if light_level <= lt["lights_off_max"]:
        return "LIGHTS_OFF"
    if light_level >= lt["lights_on_min"]:
        return "LIGHTS_ON"
    return None
