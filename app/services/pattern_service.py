"""
Pattern detection service using MongoDB aggregation pipelines.

Analyzes stored events and incident reports to surface behavioral patterns:
- Which event types occur most frequently
- What times of day anomalies cluster
- Weekly trend (are things getting better or worse?)
- Which sensors are most active for this user

MongoDB features used:
  - $group with $sum, $avg, $push for aggregation
  - $sortByCount for frequency ranking
  - $bucket for time-of-day distribution
  - $dateToString for temporal grouping
  - $facet for parallel aggregation in one pipeline
"""
from datetime import datetime, timedelta
from bson import ObjectId


async def get_event_frequency(user_id: str, db, days: int = 30) -> list[dict]:
    """
    Most frequent event types in the past N days, ranked by count.
    Uses $sortByCount — shorthand for $group + $sort.
    """
    cutoff = datetime.utcnow() - timedelta(days=days)
    pipeline = [
        {"$match": {
            "user_id": ObjectId(user_id),
            "detected_at": {"$gte": cutoff},
        }},
        {"$sortByCount": "$event_type"},
        {"$project": {
            "event_type": "$_id",
            "count": 1,
            "_id": 0,
        }},
    ]
    return await db.events.aggregate(pipeline).to_list(20)


async def get_hourly_distribution(user_id: str, db, days: int = 30) -> list[dict]:
    """
    Event counts bucketed by hour-of-day — shows when anomalies cluster.
    Uses $bucket with hour boundaries 0-23.
    """
    cutoff = datetime.utcnow() - timedelta(days=days)
    pipeline = [
        {"$match": {
            "user_id": ObjectId(user_id),
            "detected_at": {"$gte": cutoff},
        }},
        {
            "$bucket": {
                "groupBy": {"$hour": "$detected_at"},
                "boundaries": list(range(0, 25)),
                "default": "unknown",
                "output": {
                    "count": {"$sum": 1},
                    "event_types": {"$push": "$event_type"},
                },
            }
        },
    ]
    results = await db.events.aggregate(pipeline).to_list(25)
    return [{"hour": r["_id"], "count": r["count"], "event_types": r["event_types"]} for r in results]


async def get_weekly_trend(user_id: str, db, weeks: int = 8) -> list[dict]:
    """
    Weekly event counts — are incidents increasing or decreasing over time?
    Uses $dateToString with %Y-%U (year-week) for grouping.
    """
    cutoff = datetime.utcnow() - timedelta(weeks=weeks)
    pipeline = [
        {"$match": {
            "user_id": ObjectId(user_id),
            "detected_at": {"$gte": cutoff},
        }},
        {
            "$group": {
                "_id": {
                    "$dateToString": {"format": "%Y-%U", "date": "$detected_at"}
                },
                "event_count": {"$sum": 1},
                "avg_severity_score": {
                    "$avg": {
                        "$switch": {
                            "branches": [
                                {"case": {"$eq": ["$severity", "CRITICAL"]}, "then": 4},
                                {"case": {"$eq": ["$severity", "HIGH"]},     "then": 3},
                                {"case": {"$eq": ["$severity", "MEDIUM"]},   "then": 2},
                                {"case": {"$eq": ["$severity", "LOW"]},      "then": 1},
                            ],
                            "default": 0,
                        }
                    }
                },
            }
        },
        {"$sort": {"_id": 1}},
        {"$project": {"week": "$_id", "event_count": 1, "avg_severity_score": 1, "_id": 0}},
    ]
    return await db.events.aggregate(pipeline).to_list(weeks)


async def get_sensor_activity_summary(user_id: str, db, days: int = 30) -> dict:
    """
    Which sensors are triggering anomalies most? Uses $facet to run
    multiple aggregations in a single pipeline pass.
    """
    cutoff = datetime.utcnow() - timedelta(days=days)
    pipeline = [
        {"$match": {
            "user_id": ObjectId(user_id),
            "detected_at": {"$gte": cutoff},
            "triggered_sensor": {"$exists": True},
        }},
        {
            "$facet": {
                "by_sensor": [
                    {"$sortByCount": "$triggered_sensor"},
                ],
                "by_severity": [
                    {"$sortByCount": "$severity"},
                ],
                "avg_deviation": [
                    {"$group": {
                        "_id": "$triggered_sensor",
                        "avg_score": {"$avg": "$deviation_score"},
                        "max_score": {"$max": "$deviation_score"},
                    }}
                ],
            }
        },
    ]
    results = await db.events.aggregate(pipeline).to_list(1)
    return results[0] if results else {}


async def get_full_pattern_report(user_id: str, db) -> dict:
    """Single call that returns all pattern data for the dashboard."""
    frequency = await get_event_frequency(user_id, db)
    hourly    = await get_hourly_distribution(user_id, db)
    weekly    = await get_weekly_trend(user_id, db)
    sensors   = await get_sensor_activity_summary(user_id, db)
    return {
        "event_frequency": frequency,
        "hourly_distribution": hourly,
        "weekly_trend": weekly,
        "sensor_activity": sensors,
    }
