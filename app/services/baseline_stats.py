"""
Helpers for hourly sensor_baselines documents.

Older DBs may lack newer keys (light_level, gyro_magnitude, accel_magnitude).
Code always merges sane defaults so scoring is never a no-op for missing fields.
"""

from __future__ import annotations

import math

from app.models.sensor import SensorPayload

# Defaults match Arduino Nicla / LSM9DS1 + PDM + analog light when baselines are absent.
_DEFAULT_BLOCKS: dict[str, dict[str, float]] = {
    "temperature": {"mean": 22.0, "std_dev": 1.5},
    "sound_level": {"mean": 200.0, "std_dev": 50.0},
    "magnetic_state": {"mean": 0.0, "std_dev": 0.1},
    "accel_x": {"mean": 0.0, "std_dev": 0.02},
    "accel_y": {"mean": 0.0, "std_dev": 0.02},
    # Firmware sends total acceleration magnitude in g on accel_z (see serial_reader).
    "accel_z": {"mean": 1.0, "std_dev": 0.18},
    "pressure": {"mean": 1013.0, "std_dev": 2.0},
    "light_level": {"mean": 450.0, "std_dev": 120.0},
    "gyro_magnitude": {"mean": 8.0, "std_dev": 25.0},
    "accel_magnitude": {"mean": 1.0, "std_dev": 0.18},
}


def stat(baseline: dict | None, key: str) -> dict[str, float]:
    """Return {mean, std_dev} for a baseline sub-key, with defaults if missing."""
    d = (baseline or {}).get(key)
    if isinstance(d, dict) and "mean" in d and "std_dev" in d:
        mean = float(d["mean"])
        std = max(float(d["std_dev"]), 1e-6)
        # Older seeds used ~9.81 for accel_z (m/s²). Arduino LSM9DS1 reports g (~1.0 at rest).
        if key == "accel_z" and mean > 3.0:
            return dict(_DEFAULT_BLOCKS["accel_z"])
        return {"mean": mean, "std_dev": std}
    return dict(_DEFAULT_BLOCKS.get(key, {"mean": 0.0, "std_dev": 1.0}))


def accel_magnitude_of(payload: SensorPayload) -> float:
    return math.sqrt(
        payload.accel_x ** 2 + payload.accel_y ** 2 + payload.accel_z ** 2
    ) or 0.0
