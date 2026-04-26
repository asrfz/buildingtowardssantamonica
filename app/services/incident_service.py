"""
Incident report service.

Auto-generates structured incident reports when events are escalated and
stores them with vector embeddings so similar past incidents can be found
via MongoDB Atlas Vector Search.

Collection: incident_reports
  event_id, user_id, title, event_type, severity, risk_score,
  timestamp_iso, summary, sensor_readings, image_urls,
  recommended_action, resolution, embedding ([float x7]),
  created_at, similar_event_ids

MongoDB features used:
  - Atlas Vector Search ($vectorSearch) for similar incident retrieval
  - Transactions: incident insert + event link on events are atomic
  - Time-series style queries via aggregation ($group by day) for risk timeline
"""
import logging
import math
from datetime import datetime
from bson import ObjectId
from pymongo.errors import OperationFailure
from app.services.vector_service import EMBEDDING_FIELDS
from app.services.baseline_stats import stat as baseline_stat
from app.utils.event_labels import label_for_event_type

logger = logging.getLogger(__name__)

# Risk scores per severity
_RISK_SCORES = {
    "LOW":      2.0,
    "MEDIUM":   5.0,
    "HIGH":     8.0,
    "CRITICAL": 10.0,
}


def _sensor_to_embedding(sensor_payload: dict) -> list[float]:
    """Build a 7-dim unit vector from a sensor_payload dict (no baseline — uses default stats)."""
    tc = sensor_payload.get("temperature_c")
    pr = sensor_payload.get("pressure")
    raw = {
        "temperature_c": float(tc) if tc is not None else baseline_stat(None, "temperature")["mean"],
        "sound_level":    float(sensor_payload.get("sound_level", 200)),
        "magnetic_state": float(sensor_payload.get("magnetic_state", 0)),
        "accel_x":        float(sensor_payload.get("accel_x", 0.0)),
        "accel_y":        float(sensor_payload.get("accel_y", 0.0)),
        "accel_z":        float(sensor_payload.get("accel_z", 1.0)),
        "pressure":       float(pr) if pr is not None else baseline_stat(None, "pressure")["mean"],
    }
    vec = []
    for payload_field, baseline_key in EMBEDDING_FIELDS:
        stats = baseline_stat(None, baseline_key)
        mean = float(stats["mean"])
        std = float(stats["std_dev"]) or 1.0
        vec.append((raw[payload_field] - mean) / std)
    magnitude = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [round(v / magnitude, 6) for v in vec]


async def create_incident_report(
    event_id: str,
    user_id: str,
    event_type: str,
    severity: str,
    sensor_payload: dict,
    recommended_action: str,
    image_urls: dict,
    db,
    resolution: str = "notified",
) -> str:
    """
    Creates and stores an incident report. Returns the new report's ObjectId as str.
    Uses a transaction so the report insert and event status update are atomic.
    """
    label = label_for_event_type(event_type)
    risk_score = _RISK_SCORES.get(severity, 5.0)
    embedding = _sensor_to_embedding(sensor_payload)
    now = datetime.utcnow()

    temp = sensor_payload.get("temperature_c")
    temp_s = f"{temp}°C" if temp is not None else "n/a"
    sound = sensor_payload.get("sound_level", "?")
    summary = (
        f"{label} detected with {severity.lower()} severity. "
        f"Sensor readings at time of incident: temperature {temp_s}, "
        f"sound level {sound}. {recommended_action}"
    )

    report_doc = {
        "event_id":          ObjectId(event_id),
        "user_id":           ObjectId(user_id),
        "user_id_str":       user_id,
        "title":             f"{label} — {severity.title()} Risk",
        "event_type":        event_type,
        "event_label":       label,
        "severity":          severity,
        "risk_score":        risk_score,
        "timestamp_iso":     now.isoformat(),
        "summary":           summary,
        "sensor_readings":   sensor_payload,
        "image_urls":        image_urls,
        "recommended_action": recommended_action,
        "resolution":        resolution,
        "embedding":         embedding,
        "created_at":        now,
    }

    try:
        async with await db.client.start_session() as session:
            async with session.start_transaction():
                result = await db.incident_reports.insert_one(report_doc, session=session)
                await db.events.update_one(
                    {"_id": ObjectId(event_id)},
                    {"$set": {"incident_report_id": result.inserted_id}},
                    session=session,
                )
    except OperationFailure as exc:
        # Standalone local MongoDB doesn't support transactions — fall back to two writes.
        logger.warning("Transaction unavailable (%s) — using non-transactional fallback", exc)
        result = await db.incident_reports.insert_one(report_doc)
        await db.events.update_one(
            {"_id": ObjectId(event_id)},
            {"$set": {"incident_report_id": result.inserted_id}},
        )

    return str(result.inserted_id)


async def find_similar_incidents(
    incident_id: str,
    user_id: str,
    db,
    limit: int = 5,
) -> list[dict]:
    """
    Uses Atlas Vector Search to find the most similar past incidents.
    Similarity is cosine distance over the 7-dim sensor embedding —
    incidents with similar temperature/sound/motion profiles rank highest.
    """
    source = await db.incident_reports.find_one({"_id": ObjectId(incident_id)})
    if not source or not source.get("embedding"):
        return []

    pipeline = [
        {
            "$vectorSearch": {
                "index": "incident_vector_index",
                "path": "embedding",
                "queryVector": source["embedding"],
                "numCandidates": 50,
                "limit": limit + 1,
                "filter": {"user_id": ObjectId(user_id)},
            }
        },
        {"$match": {"_id": {"$ne": ObjectId(incident_id)}}},
        {"$limit": limit},
        {
            "$project": {
                "title": 1,
                "event_type": 1,
                "severity": 1,
                "risk_score": 1,
                "timestamp_iso": 1,
                "recommended_action": 1,
                "score": {"$meta": "vectorSearchScore"},
            }
        },
    ]
    results = await db.incident_reports.aggregate(pipeline).to_list(limit)
    for r in results:
        r["_id"] = str(r["_id"])
    return results


async def get_risk_timeline(user_id: str, db, days: int = 30) -> list[dict]:
    """
    Returns daily risk summary for the user over the past N days.
    Uses $group aggregation to bucket incidents by date and sum risk scores.
    """
    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(days=days)

    pipeline = [
        {"$match": {"user_id": ObjectId(user_id), "created_at": {"$gte": cutoff}}},
        {
            "$group": {
                "_id": {
                    "$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}
                },
                "total_risk": {"$sum": "$risk_score"},
                "incident_count": {"$sum": 1},
                "max_severity": {"$max": "$severity"},
                "incidents": {
                    "$push": {
                        "title": "$title",
                        "event_type": "$event_type",
                        "severity": "$severity",
                        "timestamp_iso": "$timestamp_iso",
                        "risk_score": "$risk_score",
                    }
                },
            }
        },
        {"$sort": {"_id": -1}},
    ]
    results = await db.incident_reports.aggregate(pipeline).to_list(days)
    return [{"date": r["_id"], **{k: v for k, v in r.items() if k != "_id"}} for r in results]
