"""
Seed comprehensive historical data for HomePulse demo.

Populates:
  1. raw_sensor_readings — 30 days of time-series sensor data (time series collection)
  2. user_thresholds     — per-user personalized thresholds (shows User A vs B distinction)
  3. events              — 18 historical events with realistic metadata + event_label
  4. incident_reports    — 10 incident reports with embeddings for vector similarity demo
  5. risk_timeline       — daily risk scores derived from incidents

Run after seed_demo.py:
    python scripts/seed_history.py

All data is hardcoded and realistic for demo purposes.
"""
import asyncio
import sys
import os
import math
import random
from datetime import datetime, timezone, timedelta
from bson import ObjectId

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from motor.motor_asyncio import AsyncIOMotorClient
from app.config import settings
from app.services.vector_service import EMBEDDING_FIELDS
from app.services.baseline_stats import stat as baseline_stat
from app.services.incident_service import _RISK_SCORES
from app.utils.event_labels import label_for_event_type

NOW = datetime.now(timezone.utc)


def _make_embedding(temp, sound, mag, ax, ay, az, pressure):
    raw = {
        "temperature_c": temp, "sound_level": float(sound), "magnetic_state": float(mag),
        "accel_x": ax, "accel_y": ay, "accel_z": az, "pressure": pressure,
    }
    vec = []
    for payload_field, baseline_key in EMBEDDING_FIELDS:
        st = baseline_stat(None, baseline_key)
        mean = float(st["mean"])
        std = float(st["std_dev"]) or 1.0
        vec.append((raw[payload_field] - mean) / std)
    magnitude = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [round(v / magnitude, 6) for v in vec]


async def seed_user_thresholds(db, user_id: ObjectId):
    """
    Per-user thresholds — demonstrates that the same sensor reading means
    different things for different users.

    Margaret (User A): Quiet home, dim lighting, cool temperature preference
    Hypothetical User B: Noisier household, brighter lights, warmer preference
    """
    margaret_thresholds = {
        "temperature_c": {
            "idle_min":    16.0,
            "idle_max":    23.5,       # Margaret keeps it cool
            "alert_high":  32.0,
            "alert_low":   12.0,
            "multiplier":  2.5,
        },
        "sound_level": {
            "sleep_max":   160,        # Very quiet at night (quiet neighborhood)
            "activity_min": 230,
            "alert_high":  650,
            "multiplier":  2.8,
        },
        "light_level": {
            "lights_off_max": 120,     # Her bulbs are bright — <120 means lights OFF
            "lights_on_min":  380,     # >380 means lights definitely ON
            "multiplier":     3.0,
        },
        "pressure": {
            "idle_min":    1008.0,
            "idle_max":    1022.0,
            "alert_low":   995.0,
            "multiplier":  3.5,
        },
    }

    # Hypothetical User B — different household
    # light_level=200 means lights ARE ON for this person (dimmer bulbs)
    user_b_thresholds = {
        "temperature_c": {
            "idle_min":    18.0,
            "idle_max":    27.0,       # Warmer home preference
            "alert_high":  38.0,
            "alert_low":   14.0,
            "multiplier":  2.5,
        },
        "sound_level": {
            "sleep_max":   240,        # Lives on a busier street
            "activity_min": 310,
            "alert_high":  750,
            "multiplier":  3.0,
        },
        "light_level": {
            "lights_off_max": 210,     # Dim bulbs — 200 means lights ON for User B
            "lights_on_min":  270,     # Only needs 270 to confirm ON
            "multiplier":     2.5,
        },
        "pressure": {
            "idle_min":    1005.0,
            "idle_max":    1025.0,
            "alert_low":   993.0,
            "multiplier":  3.0,
        },
    }

    await db.user_thresholds.update_one(
        {"user_id": user_id},
        {"$set": {"thresholds": margaret_thresholds, "source": "seeded", "updated_at": datetime.utcnow()}},
        upsert=True,
    )
    print(f"  [OK] User thresholds seeded for Margaret (user_id={user_id})")
    print(f"       light_level=200 → LIGHTS OFF for Margaret (lights_off_max=120)")
    print(f"       light_level=200 → LIGHTS ON  for User B   (lights_off_max=210)")


async def seed_raw_sensor_readings(db, user_id: ObjectId):
    """
    30 days of raw sensor readings stored in a time-series collection.
    Readings every 5 minutes (8640 total — sampled down for seed).
    """
    docs = []
    base_time = NOW - timedelta(days=30)

    for i in range(720):   # 720 readings = one per hour for 30 days
        ts = base_time + timedelta(hours=i)
        hour = ts.hour
        is_night = 22 <= hour or hour < 7
        is_cooking = 7 <= hour <= 9 or 17 <= hour <= 19

        docs.append({
            "timestamp":  ts,
            "metadata":   {"user_id": str(user_id), "sensor_version": "v2"},
            "temperature_c":  round(random.gauss(19.0 if is_night else (28.0 if is_cooking else 22.0), 0.8), 2),
            "sound_level":    max(0, int(random.gauss(120 if is_night else 210, 30))),
            "magnetic_state": 0,
            "accel_x":        round(random.gauss(0.0, 0.03), 4),
            "accel_y":        round(random.gauss(0.0, 0.03), 4),
            "accel_z":        round(random.gauss(9.81, 0.05), 4),
            "pressure":       round(random.gauss(1013.0, 1.5), 2),
            "light_level":    max(0, min(1023, int(random.gauss(50 if is_night else 420, 40)))),
        })

    try:
        await db.create_collection(
            "raw_sensor_readings",
            timeseries={
                "timeField": "timestamp",
                "metaField": "metadata",
                "granularity": "minutes",
            },
            expireAfterSeconds=60 * 60 * 24 * 90,   # TTL: 90 days
        )
        print("  [OK] Time series collection 'raw_sensor_readings' created with 90-day TTL")
    except Exception:
        pass   # already exists

    await db.raw_sensor_readings.insert_many(docs)
    print(f"  [OK] Inserted {len(docs)} raw sensor readings (30 days, hourly)")


async def seed_events(db, user_id: ObjectId) -> list[ObjectId]:
    """18 realistic historical events spanning 30 days."""
    event_specs = [
        # (days_ago, hour, event_type, severity, deviation, sensor, reason)
        (28, 14, "STOVE_LEFT_ON",   "HIGH",     8.2,  "temperature", "Temperature 34.1°C, no activity for 25 min"),
        (25, 7,  "FRIDGE_OPEN",     "MEDIUM",   4.0,  "magnetic",    "Magnetic sensor state=1 for 8 min at breakfast"),
        (24, 19, "STOVE_LEFT_ON",   "HIGH",     7.8,  "temperature", "Temperature 33.8°C post-dinner, no motion"),
        (22, 2,  "FAUCET_RUNNING",  "MEDIUM",   3.9,  "sound",       "Sound 480 at 2am — abnormal overnight water use"),
        (21, 11, "IRON_LEFT_ON",    "HIGH",     6.1,  "temperature", "Temperature 31.5°C, low accel, living room"),
        (20, 8,  "FRIDGE_OPEN",     "MEDIUM",   4.0,  "magnetic",    "Door open 12 min at breakfast"),
        (18, 17, "STOVE_LEFT_ON",   "CRITICAL", 12.3, "temperature", "Temperature 41.2°C, smoke sensor co-trigger"),
        (17, 9,  "WATER_DRIPPING",  "LOW",      2.1,  "sound",       "Persistent low sound 270 — possible drip"),
        (16, 23, "FAUCET_RUNNING",  "MEDIUM",   4.2,  "sound",       "Sound 520 at 11pm — abnormal late-night use"),
        (15, 14, "MULTIVARIATE_ANOMALY", "MEDIUM", 3.6, "vector",    "vector_similarity=0.79 — combined sensor deviation"),
        (14, 6,  "STOVE_LEFT_ON",   "HIGH",     9.1,  "temperature", "Temperature 36.2°C at 6am before resident awake"),
        (12, 20, "APPLIANCE_FAULT", "MEDIUM",   5.0,  "sound",       "Irregular 50Hz hum from appliance area"),
        (11, 15, "FRIDGE_OPEN",     "LOW",      2.8,  "magnetic",    "Open for 4 min — borderline, lower confidence"),
        (9,  13, "IRON_LEFT_ON",    "HIGH",     6.8,  "temperature", "Temperature 30.9°C, stationary for 40 min"),
        (7,  18, "STOVE_LEFT_ON",   "HIGH",     8.5,  "temperature", "Temperature 35.1°C during evening hours"),
        (5,  21, "FAUCET_RUNNING",  "HIGH",     6.3,  "sound",       "Sound 680 at 9pm — very loud water flow"),
        (3,  10, "STOVE_LEFT_ON",   "MEDIUM",   4.7,  "temperature", "Temperature 29.4°C — below usual stove threshold"),
        (1,  16, "FIRE_RISK",       "CRITICAL", 15.0, "temperature", "Temperature 43.8°C with rapid accel spike"),
    ]

    statuses = ["notified", "notified", "notified", "notified", "confirmed",
                "confirmed", "notified", "false_positive", "notified", "notified",
                "notified", "notified", "false_positive", "notified", "notified",
                "notified", "notified", "notified"]

    inserted_ids = []
    for i, (days_ago, hour, event_type, severity, deviation, sensor, reason) in enumerate(event_specs):
        ts = NOW - timedelta(days=days_ago, hours=random.randint(0, 1))
        ts = ts.replace(hour=hour, minute=random.randint(0, 59), second=0, microsecond=0)
        ts = ts.replace(tzinfo=None)

        label = label_for_event_type(event_type)
        doc = {
            "user_id":            user_id,
            "event_type":         event_type,
            "event_label":        label,
            "severity":           severity,
            "deviation_score":    deviation,
            "triggered_sensor":   sensor,
            "triage_reason":      reason,
            "triage_confidence":  round(random.uniform(0.72, 0.97), 2),
            "recommended_action": _action_for(event_type),
            "status":             statuses[i],
            "detected_at":        ts,
            "sensor_payload":     _sensor_payload_for(event_type),
            "user_id_str":        str(user_id),
        }
        result = await db.events.insert_one(doc)
        inserted_ids.append(result.inserted_id)

    print(f"  [OK] Inserted {len(event_specs)} historical events")
    return inserted_ids


async def seed_incident_reports(db, user_id: ObjectId, event_ids: list[ObjectId]):
    """
    10 incident reports with embeddings — enables vector similarity search demo.
    Pairs with the MEDIUM+ severity events (stove, iron, fridge, faucet).
    """
    incidents = [
        {
            "idx": 0,   # STOVE_LEFT_ON HIGH
            "temp": 34.1, "sound": 195, "mag": 0, "ax": 0.01, "ay": 0.0, "az": 9.81, "pressure": 1013.2,
            "risk": 8.0, "resolution": "notified",
        },
        {
            "idx": 2,   # STOVE_LEFT_ON HIGH
            "temp": 33.8, "sound": 200, "mag": 0, "ax": 0.02, "ay": -0.01, "az": 9.80, "pressure": 1014.1,
            "risk": 8.0, "resolution": "notified",
        },
        {
            "idx": 4,   # IRON_LEFT_ON HIGH
            "temp": 31.5, "sound": 185, "mag": 0, "ax": 0.0, "ay": 0.0, "az": 9.82, "pressure": 1012.8,
            "risk": 8.0, "resolution": "notified",
        },
        {
            "idx": 6,   # STOVE_LEFT_ON CRITICAL
            "temp": 41.2, "sound": 220, "mag": 0, "ax": 0.05, "ay": 0.03, "az": 9.79, "pressure": 1011.5,
            "risk": 10.0, "resolution": "notified",
        },
        {
            "idx": 10,  # STOVE_LEFT_ON HIGH
            "temp": 36.2, "sound": 190, "mag": 0, "ax": 0.0, "ay": -0.01, "az": 9.81, "pressure": 1013.0,
            "risk": 8.0, "resolution": "notified",
        },
        {
            "idx": 13,  # IRON_LEFT_ON HIGH
            "temp": 30.9, "sound": 180, "mag": 0, "ax": 0.01, "ay": 0.0, "az": 9.80, "pressure": 1012.5,
            "risk": 8.0, "resolution": "notified",
        },
        {
            "idx": 14,  # STOVE_LEFT_ON HIGH
            "temp": 35.1, "sound": 205, "mag": 0, "ax": 0.02, "ay": 0.01, "az": 9.81, "pressure": 1013.8,
            "risk": 8.0, "resolution": "notified",
        },
        {
            "idx": 15,  # FAUCET_RUNNING HIGH
            "temp": 22.3, "sound": 680, "mag": 0, "ax": 0.0, "ay": 0.0, "az": 9.81, "pressure": 1013.5,
            "risk": 8.0, "resolution": "notified",
        },
        {
            "idx": 16,  # STOVE_LEFT_ON MEDIUM
            "temp": 29.4, "sound": 210, "mag": 0, "ax": 0.01, "ay": 0.0, "az": 9.82, "pressure": 1013.1,
            "risk": 5.0, "resolution": "notified",
        },
        {
            "idx": 17,  # FIRE_RISK CRITICAL
            "temp": 43.8, "sound": 250, "mag": 0, "ax": 2.1, "ay": 1.8, "az": 9.20, "pressure": 1010.2,
            "risk": 10.0, "resolution": "notified",
        },
    ]

    now = datetime.utcnow()
    docs = []
    for inc in incidents:
        idx = inc["idx"]
        event_oid = event_ids[idx] if idx < len(event_ids) else event_ids[0]

        event_doc = await db.events.find_one({"_id": event_oid})
        event_type = event_doc["event_type"] if event_doc else "STOVE_LEFT_ON"
        severity   = event_doc["severity"]   if event_doc else "HIGH"
        label      = label_for_event_type(event_type)
        ts         = event_doc["detected_at"] if event_doc else now

        embedding = _make_embedding(
            inc["temp"], inc["sound"], inc["mag"],
            inc["ax"], inc["ay"], inc["az"], inc["pressure"]
        )

        docs.append({
            "event_id":          event_oid,
            "user_id":           user_id,
            "user_id_str":       str(user_id),
            "title":             f"{label} — {severity.title()} Risk",
            "event_type":        event_type,
            "event_label":       label,
            "severity":          severity,
            "risk_score":        inc["risk"],
            "timestamp_iso":     ts.isoformat() if isinstance(ts, datetime) else str(ts),
            "summary": (
                f"{label} detected with {severity.lower()} severity. "
                f"Sensor readings: temperature {inc['temp']}°C, sound {inc['sound']}. "
                f"{_action_for(event_type)}"
            ),
            "sensor_readings":   {
                "temperature_c": inc["temp"], "sound_level": inc["sound"],
                "magnetic_state": inc["mag"], "accel_x": inc["ax"],
                "accel_y": inc["ay"], "accel_z": inc["az"], "pressure": inc["pressure"],
            },
            "image_urls":        {"raw": "", "cropped": ""},
            "recommended_action": _action_for(event_type),
            "resolution":        inc["resolution"],
            "embedding":         embedding,
            "created_at":        ts if isinstance(ts, datetime) else now,
        })

    await db.incident_reports.insert_many(docs)
    print(f"  [OK] Inserted {len(docs)} incident reports with vector embeddings")


async def seed_indexes(db):
    """Create compound and partial indexes for efficient querying."""
    # Events: compound index for user timeline queries
    await db.events.create_index(
        [("user_id", 1), ("detected_at", -1)],
        name="events_user_timeline",
    )
    # Events: compound index for event type frequency queries
    await db.events.create_index(
        [("user_id", 1), ("event_type", 1), ("detected_at", -1)],
        name="events_user_type_time",
    )
    # Events: partial index — only anomalies (exclude false_positives from heavy queries)
    await db.events.create_index(
        [("user_id", 1), ("severity", 1)],
        partialFilterExpression={"status": {"$ne": "false_positive"}},
        name="events_confirmed_only",
    )
    # Sensor readings: partial index — only anomalous readings
    await db.sensor_readings.create_index(
        [("user_id", 1), ("timestamp_iso", -1)],
        partialFilterExpression={"is_anomaly": True},
        name="sensor_anomalies_only",
    )
    # Incident reports: compound + partial (MEDIUM+ severity only)
    await db.incident_reports.create_index(
        [("user_id", 1), ("created_at", -1)],
        name="incidents_user_timeline",
    )
    await db.incident_reports.create_index(
        [("user_id", 1), ("risk_score", -1)],
        partialFilterExpression={"severity": {"$in": ["MEDIUM", "HIGH", "CRITICAL"]}},
        name="incidents_high_risk",
    )
    # User thresholds
    await db.user_thresholds.create_index(
        [("user_id", 1)],
        unique=True,
        name="user_thresholds_unique",
    )
    print("  [OK] Compound, partial, and unique indexes created")


def _action_for(event_type: str) -> str:
    return {
        "STOVE_LEFT_ON":      "Please check the kitchen — the stove may have been left on.",
        "IRON_LEFT_ON":       "The iron may be on and unattended. Please turn it off.",
        "FIRE_RISK":          "Potential fire risk detected. Check immediately and call 911 if needed.",
        "FRIDGE_OPEN":        "The fridge door has been open for an extended time.",
        "FAUCET_RUNNING":     "A faucet may be running unattended. Check sinks and taps.",
        "WATER_DRIPPING":     "Possible water drip detected. Check under sinks and around pipes.",
        "APPLIANCE_FAULT":    "An appliance may be malfunctioning. Check kitchen equipment.",
        "MULTIVARIATE_ANOMALY": "Multiple sensors show unusual patterns. A check is recommended.",
        "OBJECT_DROPPED":     "An object may have been dropped. Check if help is needed.",
        "LIGHTS_OFF":         "Lights turned off — checking if expected.",
        "LIGHT_STATE_CHANGED": "Lighting changed unexpectedly.",
    }.get(event_type, "Please check your home.")


def _sensor_payload_for(event_type: str) -> dict:
    base = {
        "sound_level": 210, "temperature_c": 22.0, "magnetic_state": 0,
        "accel_x": 0.01, "accel_y": 0.0, "accel_z": 9.81, "pressure": 1013.0,
    }
    overrides = {
        "STOVE_LEFT_ON":      {"temperature_c": 34.5, "sound_level": 195},
        "IRON_LEFT_ON":       {"temperature_c": 31.2, "sound_level": 180},
        "FIRE_RISK":          {"temperature_c": 43.1, "sound_level": 245, "accel_x": 2.1},
        "FRIDGE_OPEN":        {"magnetic_state": 1, "sound_level": 195},
        "FAUCET_RUNNING":     {"sound_level": 460, "temperature_c": 22.1},
        "WATER_DRIPPING":     {"sound_level": 265, "temperature_c": 21.8},
        "APPLIANCE_FAULT":    {"sound_level": 520},
        "MULTIVARIATE_ANOMALY": {"temperature_c": 26.1, "sound_level": 310, "accel_x": 0.08},
    }
    return {**base, **overrides.get(event_type, {})}


async def main():
    client = AsyncIOMotorClient(settings.MONGODB_URI)
    db = client[settings.MONGODB_DB_NAME]

    users = await db.users.find({}).to_list(10)
    if not users:
        print("ERROR: No users found. Run seed_demo.py first.")
        client.close()
        return

    user = users[0]
    user_id = user["_id"]
    print(f"\nSeeding historical data for: {user.get('name', '?')} ({user_id})\n")

    print("1. User thresholds (per-user personalized)...")
    await seed_user_thresholds(db, user_id)

    print("\n2. Raw sensor readings (time series, 30 days)...")
    await seed_raw_sensor_readings(db, user_id)

    print("\n3. Historical events (18 incidents)...")
    event_ids = await seed_events(db, user_id)

    print("\n4. Incident reports with embeddings...")
    await seed_incident_reports(db, user_id, event_ids)

    print("\n5. Database indexes (compound, partial, unique)...")
    await seed_indexes(db)

    print("\n[Done] Historical data seeded. Next steps:")
    print("  python scripts/create_vector_index.py    # Atlas Vector Search index")
    print("  python scripts/create_search_index.py    # Atlas Full-Text Search index")
    print("  python scripts/seed_normal_vectors.py    # Normal reading corpus")
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
