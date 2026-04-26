"""
Sensor vector embedding service — MongoDB Atlas Vector Search.

Each SensorPayload is converted to a 7-dimensional unit vector by z-score
normalizing every sensor field against the user's hourly baseline, then
L2-normalizing the result. Vectors are stored in sensor_readings and queried
via $vectorSearch to detect multi-variate anomalies that single-field
z-scores can miss (e.g. mildly elevated temp + mildly elevated sound together).

Collection: sensor_readings
  user_id (ObjectId), embedding ([float x7]), is_anomaly (bool),
  payload (dict), timestamp_iso (str)

Atlas index: sensor_vector_index  — create with scripts/create_vector_index.py
  type: vectorSearch, dims: 7, similarity: cosine
  filter fields: user_id, is_anomaly

Similarity score (cosine, Atlas convention): (1 + cos_sim) / 2
  1.0 = perfectly normal, 0.0 = perfectly opposite
  ANOMALY_SIMILARITY_THRESHOLD = 0.82  (below this → flag as anomaly)
"""
import math
from bson import ObjectId
from app.models.sensor import SensorPayload

# (payload_field, baseline_doc_key)
EMBEDDING_FIELDS = [
    ("temperature_c",  "temperature"),
    ("sound_level",    "sound_level"),
    ("magnetic_state", "magnetic_state"),
    ("accel_x",        "accel_x"),
    ("accel_y",        "accel_y"),
    ("accel_z",        "accel_z"),
    ("pressure",       "pressure"),
]

_FALLBACK = {
    "temperature":    {"mean": 22.0,   "std_dev": 1.5},
    "sound_level":    {"mean": 200.0,  "std_dev": 50.0},
    "magnetic_state": {"mean": 0.0,    "std_dev": 1.0},
    "accel_x":        {"mean": 0.0,    "std_dev": 0.05},
    "accel_y":        {"mean": 0.0,    "std_dev": 0.05},
    "accel_z":        {"mean": 9.81,   "std_dev": 0.1},
    "pressure":       {"mean": 1013.0, "std_dev": 2.0},
}

ANOMALY_SIMILARITY_THRESHOLD = 0.82


def payload_to_embedding(payload: SensorPayload, baseline: dict | None) -> list[float]:
    """Z-score normalize 7 sensor fields, then L2-normalize to a unit vector."""
    raw = {
        "temperature_c":  payload.temperature_c,
        "sound_level":    float(payload.sound_level),
        "magnetic_state": float(payload.magnetic_state),
        "accel_x":        payload.accel_x,
        "accel_y":        payload.accel_y,
        "accel_z":        payload.accel_z,
        "pressure":       payload.pressure,
    }
    vec = []
    for payload_field, baseline_key in EMBEDDING_FIELDS:
        stats = (baseline or {}).get(baseline_key, _FALLBACK[baseline_key])
        mean = float(stats.get("mean", 0.0))
        std  = float(stats.get("std_dev", 1.0)) or 1.0
        vec.append((raw[payload_field] - mean) / std)

    magnitude = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [round(v / magnitude, 6) for v in vec]


async def store_sensor_vector(
    user_id: str,
    payload: SensorPayload,
    embedding: list[float],
    is_anomaly: bool,
    db,
) -> None:
    await db.sensor_readings.insert_one({
        "user_id": ObjectId(user_id),
        "embedding": embedding,
        "is_anomaly": is_anomaly,
        "payload": {
            "temperature_c":  payload.temperature_c,
            "sound_level":    payload.sound_level,
            "magnetic_state": payload.magnetic_state,
            "accel_x":        payload.accel_x,
            "accel_y":        payload.accel_y,
            "accel_z":        payload.accel_z,
            "pressure":       payload.pressure,
        },
        "timestamp_iso": payload.timestamp.isoformat(),
    })


async def vector_anomaly_score(user_id: str, embedding: list[float], db) -> float:
    """
    Returns avg cosine similarity score of the 5 nearest *normal* readings.
    1.0 = reading looks normal. < ANOMALY_SIMILARITY_THRESHOLD = anomaly.
    Returns 1.0 (safe/normal) if the index isn't ready or corpus is empty.
    """
    try:
        pipeline = [
            {
                "$vectorSearch": {
                    "index": "sensor_vector_index",
                    "path": "embedding",
                    "queryVector": embedding,
                    "numCandidates": 50,
                    "limit": 5,
                    "filter": {
                        "user_id": ObjectId(user_id),
                        "is_anomaly": False,
                    },
                }
            },
            {"$project": {"score": {"$meta": "vectorSearchScore"}}},
        ]
        results = await db.sensor_readings.aggregate(pipeline).to_list(5)
        if not results:
            return 1.0
        return sum(r["score"] for r in results) / len(results)
    except Exception:
        return 1.0
