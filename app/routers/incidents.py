"""
Incident Reports API.

GET  /incidents/<user_id>             — list all incidents for user (newest first)
GET  /incidents/detail/<incident_id>  — single incident with full detail
POST /incidents/similar/<incident_id> — find similar past incidents via vector search
GET  /incidents/risk-timeline/<user_id> — daily risk score timeline
"""
from fastapi import APIRouter, HTTPException, Query
from bson import ObjectId
from app.database import get_db
from app.services.incident_service import find_similar_incidents, get_risk_timeline

router = APIRouter()


def _serialize(doc: dict) -> dict:
    doc["incident_id"] = str(doc.pop("_id"))
    doc["event_id"]    = str(doc.get("event_id", ""))
    doc["user_id"]     = str(doc.get("user_id", ""))
    return doc


@router.get("/{user_id}")
async def list_incidents(user_id: str, limit: int = Query(50, le=200)) -> dict:
    db = get_db()
    docs = await db.incident_reports.find(
        {"user_id": ObjectId(user_id)},
        sort=[("created_at", -1)],
    ).to_list(limit)
    return {"incidents": [_serialize(d) for d in docs], "count": len(docs)}


@router.get("/detail/{incident_id}")
async def get_incident(incident_id: str) -> dict:
    db = get_db()
    doc = await db.incident_reports.find_one({"_id": ObjectId(incident_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Incident not found")
    return _serialize(doc)


@router.get("/similar/{incident_id}")
async def similar_incidents(
    incident_id: str,
    user_id: str = Query(...),
    limit: int = Query(5, le=20),
) -> dict:
    """
    Uses Atlas Vector Search (cosine similarity on sensor embedding) to find
    past incidents with the most similar sensor profiles to the given one.
    """
    db = get_db()
    results = await find_similar_incidents(incident_id, user_id, db, limit=limit)
    return {
        "source_incident_id": incident_id,
        "similar": results,
        "count": len(results),
    }


@router.get("/risk-timeline/{user_id}")
async def risk_timeline(user_id: str, days: int = Query(30, le=90)) -> dict:
    db = get_db()
    timeline = await get_risk_timeline(user_id, db, days=days)
    return {"user_id": user_id, "days": days, "timeline": timeline}
