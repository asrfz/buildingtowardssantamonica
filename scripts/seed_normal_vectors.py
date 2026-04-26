"""
Seed sensor_readings with synthetic normal reading vectors.

These become the reference corpus for $vectorSearch anomaly detection.
Without this, vector_anomaly_score() returns 1.0 (safe) for every reading
because there are no normal neighbors to compare against.

Run after seed_demo.py and create_vector_index.py:
    python scripts/seed_normal_vectors.py

Generates 200 synthetic normal readings per user drawn from each user's
hourly baseline distributions. Uses 0.5x std_dev so generated readings
are clearly within normal range and won't pollute the anomaly corpus.
"""
import asyncio
import sys
import os
import random
import math
from datetime import datetime, timezone, timedelta
from bson import ObjectId

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from motor.motor_asyncio import AsyncIOMotorClient
from app.config import settings
from app.services.vector_service import EMBEDDING_FIELDS, _FALLBACK

READINGS_PER_USER = 200


async def seed() -> None:
    client = AsyncIOMotorClient(settings.MONGODB_URI)
    db = client[settings.MONGODB_DB_NAME]

    users = await db.users.find({}).to_list(100)
    if not users:
        print("ERROR: No users found. Run seed_demo.py first.")
        client.close()
        return

    now = datetime.now(timezone.utc)

    for user in users:
        user_id = user["_id"]
        print(f"Seeding vectors for user {user_id} ({user.get('name', '?')})...")

        docs = []
        for _ in range(READINGS_PER_USER):
            ts = now - timedelta(hours=random.uniform(0, 72))
            hour = ts.hour
            day_type = "weekend" if ts.weekday() >= 5 else "weekday"

            bl = await db.sensor_baselines.find_one({
                "user_id": user_id,
                "hour_of_day": hour,
                "day_type": day_type,
            })

            def sample(baseline_key: str) -> float:
                stats = (bl or {}).get(baseline_key, _FALLBACK[baseline_key])
                return random.gauss(
                    float(stats["mean"]),
                    float(stats["std_dev"]) * 0.5,
                )

            payload_dict = {
                "temperature_c":  round(sample("temperature"), 2),
                "sound_level":    max(0, min(1023, int(sample("sound_level")))),
                "magnetic_state": 0,
                "accel_x":        round(sample("accel_x"), 4),
                "accel_y":        round(sample("accel_y"), 4),
                "accel_z":        round(sample("accel_z"), 4),
                "pressure":       round(sample("pressure"), 2),
            }

            # Compute embedding inline (same math as payload_to_embedding)
            raw = {
                "temperature_c":  payload_dict["temperature_c"],
                "sound_level":    float(payload_dict["sound_level"]),
                "magnetic_state": float(payload_dict["magnetic_state"]),
                "accel_x":        payload_dict["accel_x"],
                "accel_y":        payload_dict["accel_y"],
                "accel_z":        payload_dict["accel_z"],
                "pressure":       payload_dict["pressure"],
            }
            vec = []
            for payload_field, baseline_key in EMBEDDING_FIELDS:
                stats = (bl or {}).get(baseline_key, _FALLBACK[baseline_key])
                mean = float(stats.get("mean", 0.0))
                std  = float(stats.get("std_dev", 1.0)) or 1.0
                vec.append((raw[payload_field] - mean) / std)
            magnitude = math.sqrt(sum(v * v for v in vec)) or 1.0
            embedding = [round(v / magnitude, 6) for v in vec]

            docs.append({
                "user_id":      user_id,
                "embedding":    embedding,
                "is_anomaly":   False,
                "payload":      payload_dict,
                "timestamp_iso": ts.isoformat(),
            })

        await db.sensor_readings.insert_many(docs)
        print(f"  [OK] Inserted {len(docs)} normal vectors.")

    client.close()
    print("Done. Vector search anomaly detection is ready.")


if __name__ == "__main__":
    asyncio.run(seed())
