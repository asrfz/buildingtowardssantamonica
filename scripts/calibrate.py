"""
Manual baseline calibration runner.

Reads from Arduino serial for a configurable window and computes mean + std_dev
per sensor per hour-of-day and day-type, then writes to MongoDB sensor_baselines.

Uses the same JSON normalization as sensor_agent (app.utils.serial_reader._normalize_payload)
so keys match inputs.ino (light, sound, accel, gyro, magnetic, triggers).

Usage:
    python scripts/calibrate.py               # defaults: 1 hour, uses DEFAULT_USER_ID
    python scripts/calibrate.py <user_id>     # calibrate for specific user
"""
import asyncio
import sys
import os
import json
import math
import time
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from app.config import settings
from app.utils.serial_reader import _normalize_payload
from app.services.baseline_stats import accel_magnitude_of
from app.models.sensor import SensorPayload

CALIBRATION_SECONDS = settings.CALIBRATION_HOURS * 3600


def online_stats(samples: list[float]) -> tuple[float, float]:
    n = len(samples)
    if n == 0:
        return 0.0, 1.0
    mean = sum(samples) / n
    variance = sum((x - mean) ** 2 for x in samples) / max(n - 1, 1)
    return round(mean, 4), round(math.sqrt(variance), 4)


async def calibrate(user_id: str) -> None:
    client = AsyncIOMotorClient(settings.MONGODB_URI)
    db = client["homepulse"]

    buckets: dict = defaultdict(lambda: defaultdict(list))

    print(f"\nCalibrating for user {user_id}")
    print(f"Listening on {settings.ARDUINO_SERIAL_PORT} for {settings.CALIBRATION_HOURS}h")
    print("Press Ctrl+C to stop early and save.\n")

    try:
        import serial
        start = time.time()
        sample_count = 0
        with serial.Serial(settings.ARDUINO_SERIAL_PORT, settings.ARDUINO_BAUD_RATE, timeout=2) as ser:
            while time.time() - start < CALIBRATION_SECONDS:
                line = ser.readline().decode("utf-8", errors="ignore").strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(raw, dict) or raw.get("status") == "ready":
                    continue

                norm = _normalize_payload(raw)
                try:
                    p = SensorPayload(**norm)
                except Exception:
                    continue

                ts = datetime.utcnow()
                hour = ts.hour
                day_type = "weekend" if ts.weekday() >= 5 else "weekday"
                key = (hour, day_type)
                b = buckets[key]

                if p.temperature_c is not None:
                    b["temperature_c"].append(p.temperature_c)
                b["sound_level"].append(float(p.sound_level))
                b["magnetic_state"].append(float(p.magnetic_state))
                b["accel_x"].append(p.accel_x)
                b["accel_y"].append(p.accel_y)
                b["accel_z"].append(p.accel_z)
                b["accel_magnitude"].append(accel_magnitude_of(p))
                b["gyro_magnitude"].append(p.gyro_magnitude)
                if p.light_level is not None:
                    b["light_level"].append(float(p.light_level))
                if p.pressure is not None:
                    b["pressure"].append(p.pressure)
                sample_count += 1
                if sample_count % 250 == 0:
                    elapsed = int(time.time() - start)
                    print(f"  {elapsed}s — {sample_count} samples")

    except KeyboardInterrupt:
        print("\nStopped early.")
    except ImportError:
        print("pyserial not installed — run: pip install pyserial")
        return

    print(f"\nComputing baselines for {len(buckets)} (hour, day_type) buckets...")
    uid = ObjectId(user_id)

    for (hour, day_type), sensors in buckets.items():
        def stat(key: str, default: tuple[float, float]) -> dict:
            m, s = online_stats(sensors.get(key, []))
            if not sensors.get(key):
                m, s = default
            return {"mean": m, "std_dev": max(s, 1e-3)}

        doc = {
            "temperature": stat("temperature_c", (22.0, 1.5)),
            "sound_level": stat("sound_level", (200.0, 50.0)),
            "magnetic_state": stat("magnetic_state", (0.0, 0.1)),
            "accel_x": stat("accel_x", (0.0, 0.02)),
            "accel_y": stat("accel_y", (0.0, 0.02)),
            "accel_z": stat("accel_z", (1.0, 0.18)),
            "accel_magnitude": stat("accel_magnitude", (1.0, 0.18)),
            "gyro_magnitude": stat("gyro_magnitude", (8.0, 25.0)),
            "light_level": stat("light_level", (450.0, 120.0)),
            "pressure": stat("pressure", (1013.0, 2.0)),
        }

        await db.sensor_baselines.update_one(
            {"user_id": uid, "hour_of_day": hour, "day_type": day_type},
            {"$set": {**doc, "updated_at": datetime.utcnow()}},
            upsert=True,
        )

    print(f"✅ Baselines written for {len(buckets)} buckets.")
    client.close()


if __name__ == "__main__":
    uid = sys.argv[1] if len(sys.argv) > 1 else settings.DEFAULT_USER_ID
    if not uid:
        print("Error: provide user_id as argument or set DEFAULT_USER_ID in .env")
        sys.exit(1)
    asyncio.run(calibrate(uid))
