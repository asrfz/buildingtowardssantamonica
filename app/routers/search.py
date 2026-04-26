"""
Search API — full-text event and incident search backed by Atlas Search.

GET /search/events?q=stove+left+on
    Returns all times "stove left on" events were detected, with exact timestamps.

GET /search/events?q=water&severity=HIGH&days=30
    Filter by severity and recency.

GET /search/incidents?q=fridge&user_id=<id>
    Search incident reports by text.

GET /search/patterns/<user_id>
    Aggregation-based pattern report (frequency, hourly distribution, weekly trend).
"""
from fastapi import APIRouter, Query
from typing import Optional
from app.database import get_db
from app.services.search_service import search_events, search_incidents
from app.services.pattern_service import get_full_pattern_report

router = APIRouter()


@router.get("/events")
async def search_events_endpoint(
    q: str = Query(..., description='Search query, e.g. "stove left on"'),
    user_id: Optional[str] = Query(None),
    severity: Optional[str] = Query(None, description="LOW|MEDIUM|HIGH|CRITICAL"),
    days: Optional[int] = Query(None, description="Limit to last N days"),
    limit: int = Query(20, le=100),
) -> dict:
    db = get_db()
    results = await search_events(
        query=q,
        db=db,
        user_id=user_id,
        days=days,
        severity=severity,
        limit=limit,
    )
    return {
        "query": q,
        "count": len(results),
        "results": results,
    }


@router.get("/incidents")
async def search_incidents_endpoint(
    q: str = Query(..., description='Search query, e.g. "stove" or "high risk"'),
    user_id: Optional[str] = Query(None),
    limit: int = Query(10, le=50),
) -> dict:
    db = get_db()
    results = await search_incidents(query=q, db=db, user_id=user_id, limit=limit)
    return {
        "query": q,
        "count": len(results),
        "results": results,
    }


@router.get("/patterns/{user_id}")
async def get_patterns(user_id: str) -> dict:
    db = get_db()
    return await get_full_pattern_report(user_id, db)
