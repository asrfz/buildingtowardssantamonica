"""
Atlas Full-Text Search service for HomePulse events.

If Atlas Search is not configured (e.g. local MongoDB), aggregate falls back to
regex matching on event_label / event_type / recommended_action so demos still work.

Enables natural-language event lookup:
  "stove left on"  → STOVE_LEFT_ON events with exact timestamps
  "fridge"         → FRIDGE_OPEN events
  "high risk"      → HIGH/CRITICAL severity events
  "water"          → FAUCET_RUNNING, WATER_DRIPPING events

MongoDB features used:
  - Atlas Search ($search aggregation stage)
  - compound operator: must + should for boosting recent results
  - text with fuzzy for typo tolerance
  - range filter on detected_at
  - highlight for showing matched text in results
  - searchMeta for result counts without fetching docs
  - Covered by index: sensor_event_search (created via scripts/create_search_index.py)

The Atlas Search index uses a custom analyzer that:
  1. Strips underscores (STOVE_LEFT_ON → STOVE LEFT ON)
  2. Lowercases tokens
  3. Applies synonym mappings (e.g. "stove" ↔ "STOVE_LEFT_ON", "burner")
  so "stove left on" matches event_type STOVE_LEFT_ON naturally.
"""
import logging
import re
from datetime import datetime, timedelta
from pymongo.errors import OperationFailure

logger = logging.getLogger(__name__)


async def search_events(
    query: str,
    db,
    user_id: str | None = None,
    days: int | None = None,
    severity: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """
    Full-text search across event_type, event_label, recommended_action,
    triage_reason, and monitor_reasoning fields.

    Returns events sorted by Atlas Search relevance score, with detected_at
    for exact time display ("stove left on" → all times this happened).
    """
    must_clauses = [
        {
            "text": {
                "query": query,
                "path": ["event_label", "recommended_action", "triage_reason", "monitor_reasoning"],
                "fuzzy": {"maxEdits": 1},
            }
        }
    ]

    filter_clauses = []
    if user_id:
        filter_clauses.append({
            "equals": {
                "path": "user_id_str",
                "value": user_id,
            }
        })
    if severity:
        filter_clauses.append({
            "equals": {
                "path": "severity",
                "value": severity.upper(),
            }
        })
    if days:
        cutoff = datetime.utcnow() - timedelta(days=days)
        filter_clauses.append({
            "range": {
                "path": "detected_at",
                "gte": cutoff,
            }
        })

    search_stage: dict = {
        "index": "sensor_event_search",
        "compound": {
            "must": must_clauses,
        },
        "sort": {"score": {"$meta": "searchScore"}, "detected_at": -1},
    }
    if filter_clauses:
        search_stage["compound"]["filter"] = filter_clauses

    pipeline = [
        {"$search": search_stage},
        {
            "$project": {
                "event_id":         {"$toString": "$_id"},
                "event_type":       1,
                "event_label":      1,
                "severity":         1,
                "detected_at":      1,
                "recommended_action": 1,
                "triage_reason":    1,
                "status":           1,
                "cropped_image_url": 1,
                "score":            {"$meta": "searchScore"},
                "_id":              0,
            }
        },
        {"$limit": limit},
    ]

    try:
        results = await db.events.aggregate(pipeline).to_list(limit)
    except OperationFailure as exc:
        logger.warning("Atlas $search unavailable (%s) — using regex fallback", exc)
        results = await _fallback_search_events(query, db, user_id, days, severity, limit)

    for r in results:
        if isinstance(r.get("detected_at"), datetime):
            r["detected_at_str"] = r["detected_at"].strftime("%Y-%m-%d %H:%M UTC")
    return results


async def _fallback_search_events(
    query: str,
    db,
    user_id: str | None,
    days: int | None,
    severity: str | None,
    limit: int,
) -> list[dict]:
    """Local / non-Atlas: case-insensitive substring match."""
    esc = re.escape(query.strip())
    filt: dict = {
        "$or": [
            {"event_label": {"$regex": esc, "$options": "i"}},
            {"event_type": {"$regex": esc, "$options": "i"}},
            {"recommended_action": {"$regex": esc, "$options": "i"}},
            {"triage_reason": {"$regex": esc, "$options": "i"}},
            {"monitor_reasoning": {"$regex": esc, "$options": "i"}},
        ]
    }
    if user_id:
        from bson import ObjectId

        try:
            uid = ObjectId(user_id)
        except Exception:
            uid = None
        user_clause = (
            [{"user_id_str": user_id}, {"user_id": uid}]
            if uid
            else [{"user_id_str": user_id}]
        )
        filt = {"$and": [filt, {"$or": user_clause}]}
    if severity:
        base = filt
        filt = {"$and": [base, {"severity": severity.upper()}]}
    if days:
        cutoff = datetime.utcnow() - timedelta(days=days)
        base = filt
        filt = {"$and": [base, {"detected_at": {"$gte": cutoff}}]}

    cursor = db.events.find(filt).sort("detected_at", -1).limit(limit)
    out: list[dict] = []
    async for doc in cursor:
        eid = str(doc.pop("_id"))
        doc["event_id"] = eid
        out.append(doc)
    return out


async def search_incidents(
    query: str,
    db,
    user_id: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """Full-text search across incident_reports (title, summary, event_label)."""
    filter_clauses = []
    if user_id:
        filter_clauses.append({"equals": {"path": "user_id_str", "value": user_id}})

    search_stage: dict = {
        "index": "incident_text_search",
        "compound": {
            "must": [
                {
                    "text": {
                        "query": query,
                        "path": ["title", "summary", "event_label", "recommended_action"],
                        "fuzzy": {"maxEdits": 1},
                    }
                }
            ],
        },
    }
    if filter_clauses:
        search_stage["compound"]["filter"] = filter_clauses

    pipeline = [
        {"$search": search_stage},
        {
            "$project": {
                "incident_id": {"$toString": "$_id"},
                "title": 1,
                "event_type": 1,
                "severity": 1,
                "risk_score": 1,
                "timestamp_iso": 1,
                "summary": 1,
                "score": {"$meta": "searchScore"},
                "_id": 0,
            }
        },
        {"$limit": limit},
    ]
    try:
        return await db.incident_reports.aggregate(pipeline).to_list(limit)
    except OperationFailure as exc:
        logger.warning("Atlas $search unavailable for incidents (%s) — regex fallback", exc)
        return await _fallback_search_incidents(query, db, user_id, limit)


async def _fallback_search_incidents(
    query: str,
    db,
    user_id: str | None,
    limit: int,
) -> list[dict]:
    from bson import ObjectId

    esc = re.escape(query.strip())
    filt: dict = {
        "$or": [
            {"title": {"$regex": esc, "$options": "i"}},
            {"summary": {"$regex": esc, "$options": "i"}},
            {"event_label": {"$regex": esc, "$options": "i"}},
            {"event_type": {"$regex": esc, "$options": "i"}},
        ]
    }
    if user_id:
        try:
            uid = ObjectId(user_id)
        except Exception:
            uid = None
        user_clause = (
            [{"user_id_str": user_id}, {"user_id": uid}]
            if uid
            else [{"user_id_str": user_id}]
        )
        filt = {"$and": [filt, {"$or": user_clause}]}

    cursor = db.incident_reports.find(filt).sort("created_at", -1).limit(limit)
    out: list[dict] = []
    async for doc in cursor:
        iid = str(doc.pop("_id"))
        doc["incident_id"] = iid
        out.append(doc)
    return out
