"""
Manual baseline calibration runner.

Reads from Arduino serial for a configurable window and computes mean + std_dev
per sensor per hour-of-day and day-type, then writes to MongoDB sensor_baselines.

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
from app.config import settings

CALIBRATION_SECONDS = settings.CALIBRATION_HOURS * 3600


def online_stats(samples: list[float]) -> tuple[float, float]:
    """Return (mean, std_dev) for a list of samples."""
    n = len(samples)
    if n == 0:
        return 0.0, 1.0
    mean = sum(samples) / n
    variance = sum((x - mean) ** 2 for x in samples) / max(n - 1, 1)
    return round(mean, 4), round(math.sqrt(variance), 4)


async def calibrate(user_id: str) -> None:
    client = AsyncIOMotorClient(settings.MONGODB_URI)
    db = client["homepulse"]

    # bucket: (hour, day_type) → {sensor: [values]}
    buckets: dict = defaultdict(lambda: defaultdict(list))

    print(f"\nCalibrating for user {user_id}")
    print(f"Listening on {settings.ARDUINO_SERIAL_PORT} for {settings.CALIBRATION_HOURS}h")
    print("Press Ctrl+C to stop early and save.\n")

    try:
        import serial
        start = time.time()
        with serial.Serial(settings.ARDUINO_SERIAL_PORT, settings.ARDUINO_BAUD_RATE, timeout=2) as ser:
            while time.time() - start < CALIBRATION_SECONDS:
                line = ser.readline().decode("utf-8", errors="ignore").strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                ts = datetime.utcnow()
                hour = ts.hour
                day_type = "weekend" if ts.weekday() >= 5 else "weekday"
                key = (hour, day_type)

                for sensor in ("temperature_c", "sound_level", "magnetic_state",
                               "accel_x", "accel_y", "accel_z", "pressure"):
                    if sensor in data:
                        buckets[key][sensor].append(float(data[sensor]))

                elapsed = int(time.time() - start)
                if elapsed % 60 == 0:
                    print(f"  {elapsed // 60}m elapsed — {sum(len(v) for b in buckets.values() for v in b.values())} readings collected")

    except KeyboardInterrupt:
        print("\nStopped early.")
    except ImportError:
        print("pyserial not installed — run: pip install pyserial")
        return

    # Write baselines
    print(f"\nComputing baselines for {len(buckets)} (hour, day_type) buckets...")
    from bson import ObjectId
    uid = ObjectId(user_id)

    for (hour, day_type), sensors in buckets.items():
        temp_mean, temp_std = online_stats(sensors.get("temperature_c", [22.0]))
        sound_mean, sound_std = online_stats(sensors.get("sound_level", [200.0]))
        mag_mean, mag_std = online_stats(sensors.get("magnetic_state", [0.0]))

        await db.sensor_baselines.update_one(
            {"user_id": uid, "hour_of_day": hour, "day_type": day_type},
            {
                "$set": {
                    "temperature": {"mean": temp_mean, "std_dev": max(temp_std, 0.5)},
                    "sound_level": {"mean": sound_mean, "std_dev": max(sound_std, 10.0)},
                    "magnetic_state": {"mean": mag_mean, "std_dev": max(mag_std, 0.1)},
                    "updated_at": datetime.utcnow(),
                }
            },
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
