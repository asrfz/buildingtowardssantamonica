"""
Seed MongoDB with a realistic week of past HomePulse events.

Run AFTER seed_demo.py (DEFAULT_USER_ID must be set in .env):
    python scripts/seed_events.py

Creates 10 incidents across the last 7 days covering all major event types,
with realistic sensor readings, Claude-style reasoning, and mixed outcomes
(confirmed, dismissed, cancelled) so the dashboard agent has rich data to
report on.
"""
import asyncio
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient
from app.config import settings

NOW = datetime.utcnow()


def days_ago(d: float, hour: int = 0) -> datetime:
    return (NOW - timedelta(days=d)).replace(hour=hour, minute=0, second=0, microsecond=0)


EVENTS = [
    # ── 1. Stove left on — HIGH — 6 days ago, 2am ────────────────────────────
    {
        "event_type": "STOVE_LEFT_ON",
        "severity": "HIGH",
        "status": "notified",
        "detected_at": days_ago(6, hour=2),
        "deviation_score": 9.2,
        "sensor": "temperature",
        "sensor_payload": {
            "sound_level": 210,
            "temperature_c": 48.7,
            "magnetic_state": 0,
            "accel_x": 0.01,
            "accel_y": 0.02,
            "accel_z": 9.80,
            "pressure": 1012,
        },
        "triage_reason": "Temperature 9.2x above 2am baseline with zero movement — high probability stove left on after late-night cooking.",
        "triage_confidence": 0.94,
        "monitor_reasoning": "Sustained 48.7°C at 2am with no accelerometer activity is consistent with a stove element left on after cooking. No sound anomaly rules out active cooking.",
        "recommended_action": "Please check your stove — it may have been left on after cooking.",
        "suggested_service": "none",
        "notification_sent": True,
        "cropped_image_url": "",
        "confirmed": True,
    },
    # ── 2. Fridge left open — MEDIUM — 5 days ago, 7pm ──────────────────────
    {
        "event_type": "FRIDGE_OPEN",
        "severity": "MEDIUM",
        "status": "notified",
        "detected_at": days_ago(5, hour=19),
        "deviation_score": 4.8,
        "sensor": "magnetic",
        "sensor_payload": {
            "sound_level": 195,
            "temperature_c": 26.1,
            "magnetic_state": 1,
            "accel_x": 0.0,
            "accel_y": 0.01,
            "accel_z": 9.81,
            "pressure": 1013,
        },
        "triage_reason": "Fridge door open for over 4 minutes with ambient temperature rising — not a brief grab.",
        "triage_confidence": 0.88,
        "monitor_reasoning": "Magnetic sensor shows door open for an extended period during dinner hour. Ambient temperature rise of 4°C confirms cold air escaping. Likely distracted during meal prep.",
        "recommended_action": "Your fridge door has been open for a while — please close it to keep food fresh.",
        "suggested_service": "none",
        "notification_sent": True,
        "cropped_image_url": "",
        "confirmed": True,
    },
    # ── 3. Faucet running — MEDIUM — 5 days ago, 11pm ───────────────────────
    {
        "event_type": "FAUCET_RUNNING",
        "severity": "MEDIUM",
        "status": "notified",
        "detected_at": days_ago(5, hour=23),
        "deviation_score": 5.3,
        "sensor": "sound",
        "sensor_payload": {
            "sound_level": 465,
            "temperature_c": 22.3,
            "magnetic_state": 0,
            "accel_x": 0.01,
            "accel_y": 0.0,
            "accel_z": 9.81,
            "pressure": 1013,
        },
        "triage_reason": "Continuous water-flow sound pattern at 11pm for 12+ minutes, no movement — tap likely left running.",
        "triage_confidence": 0.91,
        "monitor_reasoning": "Sound signature at 465 units matches running faucet and has been sustained for over 12 minutes with no movement nearby. 11pm timing makes accidental leave-on likely.",
        "recommended_action": "It sounds like a tap may have been left running — please check your sink.",
        "suggested_service": "none",
        "notification_sent": True,
        "cropped_image_url": "",
        "confirmed": True,
    },
    # ── 4. Dismissed false positive — dinner cooking — 4 days ago, 6pm ──────
    {
        "event_type": "STOVE_LEFT_ON",
        "severity": "LOW",
        "status": "dismissed",
        "detected_at": days_ago(4, hour=18),
        "deviation_score": 3.1,
        "sensor": "temperature",
        "sensor_payload": {
            "sound_level": 340,
            "temperature_c": 31.2,
            "magnetic_state": 0,
            "accel_x": 0.15,
            "accel_y": 0.12,
            "accel_z": 9.78,
            "pressure": 1014,
        },
        "triage_reason": "Temperature rise at 6pm weekday with active movement and sound — consistent with normal dinner cooking, not an anomaly.",
        "triage_confidence": 0.82,
        "monitor_reasoning": None,
        "recommended_action": None,
        "suggested_service": None,
        "notification_sent": False,
        "cropped_image_url": "",
        "confirmed": False,
    },
    # ── 5. Stove left on again — HIGH — 3 days ago, 1am ─────────────────────
    {
        "event_type": "STOVE_LEFT_ON",
        "severity": "HIGH",
        "status": "notified",
        "detected_at": days_ago(3, hour=1),
        "deviation_score": 11.4,
        "sensor": "temperature",
        "sensor_payload": {
            "sound_level": 198,
            "temperature_c": 52.1,
            "magnetic_state": 0,
            "accel_x": 0.0,
            "accel_y": 0.01,
            "accel_z": 9.81,
            "pressure": 1012,
        },
        "triage_reason": "52°C at 1am — 11.4x above overnight baseline — with zero movement. Second stove incident this week, high confidence.",
        "triage_confidence": 0.97,
        "monitor_reasoning": "This is the second stove event in 6 days, both after midnight. Temperature has reached 52°C which poses a fire risk if left unattended. Immediate attention required.",
        "recommended_action": "Your stove appears to be on at 1am — please check immediately and turn it off.",
        "suggested_service": "none",
        "notification_sent": True,
        "cropped_image_url": "",
        "confirmed": True,
    },
    # ── 6. Appliance fault — washer — MEDIUM — 3 days ago, 10am ─────────────
    {
        "event_type": "APPLIANCE_FAULT",
        "severity": "MEDIUM",
        "status": "notified",
        "detected_at": days_ago(3, hour=10),
        "deviation_score": 6.7,
        "sensor": "accelerometer",
        "sensor_payload": {
            "sound_level": 580,
            "temperature_c": 23.1,
            "magnetic_state": 0,
            "accel_x": 1.82,
            "accel_y": 2.14,
            "accel_z": 10.3,
            "pressure": 1013,
        },
        "triage_reason": "Abnormal vibration signature with loud sound mid-morning — possible unbalanced washing machine.",
        "triage_confidence": 0.79,
        "monitor_reasoning": "Accelerometer shows irregular high-amplitude vibrations inconsistent with normal appliance operation. Combined with elevated sound, this suggests an off-balance washer or mechanical fault.",
        "recommended_action": "There may be an issue with an appliance — check your washing machine for an unbalanced load.",
        "suggested_service": "appliance_repair",
        "notification_sent": True,
        "cropped_image_url": "",
        "confirmed": True,
    },
    # ── 7. Water dripping — LOW — 2 days ago, 3am ────────────────────────────
    {
        "event_type": "WATER_DRIPPING",
        "severity": "LOW",
        "status": "notified",
        "detected_at": days_ago(2, hour=3),
        "deviation_score": 3.8,
        "sensor": "sound",
        "sensor_payload": {
            "sound_level": 285,
            "temperature_c": 21.9,
            "magnetic_state": 0,
            "accel_x": 0.0,
            "accel_y": 0.0,
            "accel_z": 9.81,
            "pressure": 1013,
        },
        "triage_reason": "Rhythmic low-volume repeating sound at 3am — classic dripping tap signature.",
        "triage_confidence": 0.73,
        "monitor_reasoning": "Sound pattern shows rhythmic low-amplitude pulses consistent with a dripping faucet. Not urgent but persistent — worth checking in the morning.",
        "recommended_action": "There may be a dripping tap — check your faucets when you wake up.",
        "suggested_service": "none",
        "notification_sent": True,
        "cropped_image_url": "",
        "confirmed": True,
    },
    # ── 8. Fridge left open — cancelled by user — 1 day ago, 9am ────────────
    {
        "event_type": "FRIDGE_OPEN",
        "severity": "MEDIUM",
        "status": "cancelled",
        "detected_at": days_ago(1, hour=9),
        "deviation_score": 4.1,
        "sensor": "magnetic",
        "sensor_payload": {
            "sound_level": 200,
            "temperature_c": 24.8,
            "magnetic_state": 1,
            "accel_x": 0.02,
            "accel_y": 0.01,
            "accel_z": 9.80,
            "pressure": 1013,
        },
        "triage_reason": "Fridge door open for over 3 minutes at 9am — possible false positive during breakfast.",
        "triage_confidence": 0.71,
        "monitor_reasoning": "Door open during breakfast hour — could be intentional. Flagged for user confirmation.",
        "recommended_action": "Your fridge door has been open — is everything okay?",
        "suggested_service": "none",
        "notification_sent": True,
        "cropped_image_url": "",
        "confirmed": False,
    },
    # ── 9. Iron left on — HIGH — today, 8am ──────────────────────────────────
    {
        "event_type": "IRON_LEFT_ON",
        "severity": "HIGH",
        "status": "notified",
        "detected_at": days_ago(0, hour=8),
        "deviation_score": 8.9,
        "sensor": "temperature",
        "sensor_payload": {
            "sound_level": 202,
            "temperature_c": 44.3,
            "magnetic_state": 0,
            "accel_x": 0.0,
            "accel_y": 0.0,
            "accel_z": 9.81,
            "pressure": 1012,
        },
        "triage_reason": "Heat spike this morning with zero vibration — consistent with iron left on after getting dressed.",
        "triage_confidence": 0.89,
        "monitor_reasoning": "44°C with zero accelerometer movement this morning suggests an iron left on after use. No sound anomaly rules out active cooking. Fire risk if left unattended.",
        "recommended_action": "Your iron may have been left on — please check before leaving the room.",
        "suggested_service": "none",
        "notification_sent": True,
        "cropped_image_url": "",
        "confirmed": True,
    },
    # ── 10. Faucet running — today, 2 hours ago ───────────────────────────────
    {
        "event_type": "FAUCET_RUNNING",
        "severity": "MEDIUM",
        "status": "notified",
        "detected_at": NOW - timedelta(hours=2),
        "deviation_score": 5.1,
        "sensor": "sound",
        "sensor_payload": {
            "sound_level": 451,
            "temperature_c": 22.7,
            "magnetic_state": 0,
            "accel_x": 0.01,
            "accel_y": 0.0,
            "accel_z": 9.81,
            "pressure": 1013,
        },
        "triage_reason": "Sustained water-flow sound pattern for 10+ minutes with no nearby movement.",
        "triage_confidence": 0.87,
        "monitor_reasoning": "Running faucet sound sustained for over 10 minutes with no movement detected nearby. Likely left on after handwashing or dishwashing.",
        "recommended_action": "A tap may have been left running — please check your kitchen or bathroom sink.",
        "suggested_service": "none",
        "notification_sent": True,
        "cropped_image_url": "",
        "confirmed": True,
    },
]


async def seed_events() -> None:
    if not settings.DEFAULT_USER_ID:
        print("ERROR: DEFAULT_USER_ID not set in .env — run seed_demo.py first.")
        return

    client = AsyncIOMotorClient(settings.MONGODB_URI)
    db = client["homepulse"]
    user_id = ObjectId(settings.DEFAULT_USER_ID)

    # Stamp user_id onto every event
    docs = []
    for e in EVENTS:
        doc = dict(e)
        doc["user_id"] = user_id
        docs.append(doc)

    result = await db.events.insert_many(docs)
    print(f"[OK] Inserted {len(result.inserted_ids)} events into MongoDB")

    # Update behavioral schema with realistic false positive rates
    await db.behavioral_schema.update_one(
        {"user_id": user_id},
        {"$set": {
            "event_type_history": {
                "STOVE_LEFT_ON":   {"count": 3, "confirmed": 2, "false_positive_rate": 0.33},
                "FRIDGE_OPEN":     {"count": 3, "confirmed": 1, "false_positive_rate": 0.33},
                "FAUCET_RUNNING":  {"count": 2, "confirmed": 2, "false_positive_rate": 0.0},
                "WATER_DRIPPING":  {"count": 1, "confirmed": 1, "false_positive_rate": 0.0},
                "APPLIANCE_FAULT": {"count": 1, "confirmed": 1, "false_positive_rate": 0.0},
                "IRON_LEFT_ON":    {"count": 1, "confirmed": 1, "false_positive_rate": 0.0},
            },
            "updated_at": NOW,
        }},
        upsert=True,
    )
    print("[OK] Behavioral schema updated with false positive rates")

    # Fake a recent heartbeat so system shows as online
    await db.agent_heartbeats.update_one(
        {"agent": "sensor_agent"},
        {"$set": {"last_seen": NOW}},
        upsert=True,
    )
    print("[OK] Heartbeat set — system will show as online")

    print("\nDone. Ask the dashboard agent:")
    print('  "What happened at home this week?"')
    print('  "Any critical alerts recently?"')
    print('  "Has the stove been left on?"')

    client.close()


if __name__ == "__main__":
    asyncio.run(seed_events())
