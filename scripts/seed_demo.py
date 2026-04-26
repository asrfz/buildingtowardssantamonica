"""
Seed MongoDB with a demo user, sensor baselines, room zones, and behavioral schema.

Run ONCE before starting any agents:
    python scripts/seed_demo.py

After running, copy the printed ObjectId into .env as DEFAULT_USER_ID=<id>
"""
import asyncio
import sys
import os
from datetime import datetime

# Allow imports from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from motor.motor_asyncio import AsyncIOMotorClient
from app.config import settings


async def seed() -> None:
    client = AsyncIOMotorClient(settings.MONGODB_URI)
    db = client["homepulse"]

    # ── 1. Create demo user ──────────────────────────────────────────────────
    result = await db.users.insert_one({
        "name": "Margaret Chen",
        "email": settings.GMAIL_ADDRESS or "demo@example.com",
        "emergency_contacts": [],
        "threshold_multiplier": 2.5,
        "created_at": datetime.utcnow(),
    })
    user_id = result.inserted_id
    print(f"\n[OK] Demo user created: {user_id}")
    print(f"   Add this to .env:\n   DEFAULT_USER_ID={user_id}\n")

    # ── 2. Seed baselines for all 24 hours × 2 day types ────────────────────
    # Tight std_devs make demo triggers easy to produce:
    #   - Any temp above 25.75°C (= 22 + 2.5×1.5) will fire
    #   - Any sound above 325 (= 200 + 2.5×50) will fire
    baseline_docs = []
    for hour in range(24):
        for day_type in ("weekday", "weekend"):
            baseline_docs.append({
                "user_id": user_id,
                "hour_of_day": hour,
                "day_type": day_type,
                "temperature": {"mean": 22.0, "std_dev": 1.5},
                "sound_level": {"mean": 200, "std_dev": 50},
                "magnetic_state": {"mean": 0, "std_dev": 0.1},
                "accel_x": {"mean": 0.0, "std_dev": 0.02},
                "accel_y": {"mean": 0.0, "std_dev": 0.02},
                "accel_z": {"mean": 1.0, "std_dev": 0.18},
                "accel_magnitude": {"mean": 1.0, "std_dev": 0.18},
                "gyro_magnitude": {"mean": 8.0, "std_dev": 25.0},
                "light_level": {"mean": 450.0, "std_dev": 120.0},
                "pressure": {"mean": 1013.0, "std_dev": 2.0},
                "created_at": datetime.utcnow(),
            })
    await db.sensor_baselines.insert_many(baseline_docs)
    print(f"[OK] Inserted {len(baseline_docs)} baseline documents (24 hours x 2 day types)")

    # ── 3. Seed room zones (stove, sink, fridge) ─────────────────────────────
    await db.room_zones.insert_one({
        "user_id": user_id,
        "zones": {
            "stove":  {"x": 400, "y": 150, "w": 280, "h": 220},
            "sink":   {"x": 100, "y": 200, "w": 300, "h": 200},
            "fridge": {"x": 50,  "y": 100, "w": 200, "h": 350},
        },
        "created_at": datetime.utcnow(),
    })
    print("[OK] Room zones seeded (stove, sink, fridge)")

    # ── 4. Empty behavioral schema ───────────────────────────────────────────
    await db.behavioral_schema.insert_one({
        "user_id": user_id,
        "event_type_history": {},
        "updated_at": datetime.utcnow(),
    })
    print("[OK] Behavioral schema initialized")

    print("\nSetup complete. Don't forget to set DEFAULT_USER_ID in your .env file.")
    client.close()


if __name__ == "__main__":
    asyncio.run(seed())
