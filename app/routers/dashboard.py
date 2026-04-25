"""
POST /dashboard/chat — Agentverse HTTP endpoint for the homepulse_dashboard agent.

Agentverse calls this URL when a user sends a message via ASI:One chat.
It extracts the user's text, runs the HomePulse query logic, and returns
the response in the format Agentverse expects.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import get_db
from app.services import claude_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/chat")
async def dashboard_chat(request: Request) -> JSONResponse:
    """Agentverse calls this endpoint with the ASI:One user message."""
    raw_body = await request.body()
    logger.info(f"RAW Agentverse payload: {raw_body.decode('utf-8', errors='replace')}")

    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        body = {}

    logger.info(f"Parsed body keys: {list(body.keys())}")

    # Agentverse Chat Protocol wraps messages in an envelope.
    # The actual text lives inside payload → content[0].text or similar.
    user_text: str = (
        _extract_agentverse(body)
        or _extract(body, "text")
        or _extract(body, "message")
        or _extract(body, "content")
        or _extract(body, "query")
        or ""
    )

    if not user_text:
        logger.warning(f"Could not extract text from payload: {body}")
        user_text = "status"

    logger.info(f"ASI:One query: {user_text!r}")

    try:
        reply = await _build_response(user_text)
    except Exception as e:
        logger.error(f"Dashboard error: {e}", exc_info=True)
        reply = (
            "I'm having trouble fetching home data right now. "
            "The HomePulse system is running — please try again in a moment."
        )

    # Return in both flat and Agentverse Chat Protocol envelope formats
    return JSONResponse({
        "text": reply,
        "message": reply,
        "type": "agent_chat_message",
        "content": [{"type": "text", "text": reply}],
    })


# ── helpers ──────────────────────────────────────────────────────────────────

def _extract_agentverse(body: dict) -> str:
    """Handle Agentverse Chat Protocol envelope: payload is base64 JSON with content list."""
    import base64, json as _json
    payload = body.get("payload")
    if not payload:
        return ""
    try:
        decoded = base64.b64decode(payload + "==").decode("utf-8")
        inner = _json.loads(decoded)
        content = inner.get("content", [])
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                return item.get("text", "").strip()
        # fallback: maybe content is a plain string
        if isinstance(content, str):
            return content.strip()
    except Exception:
        pass
    return ""


def _extract(body: dict, key: str) -> str:
    """Pull a string value from body[key], handling nested dicts/lists."""
    val = body.get(key)
    if isinstance(val, str):
        return val.strip()
    if isinstance(val, list) and val:
        first = val[0]
        if isinstance(first, str):
            return first.strip()
        if isinstance(first, dict):
            return _extract(first, "text") or _extract(first, "content") or ""
    if isinstance(val, dict):
        return _extract(val, "text") or _extract(val, "content") or ""
    return ""


async def _build_response(query: str) -> str:
    db = get_db()
    now = datetime.utcnow()

    # ── System online status ─────────────────────────────────────────────────
    heartbeat = await db.agent_heartbeats.find_one({"agent": "sensor_agent"})
    if heartbeat and heartbeat.get("last_seen"):
        silence = (now - heartbeat["last_seen"]).total_seconds()
        system_online = silence < settings.HEARTBEAT_TIMEOUT_SECONDS
        last_seen_ago = f"{int(silence)}s ago"
    else:
        system_online = False
        last_seen_ago = "never"

    # ── User info ────────────────────────────────────────────────────────────
    user = None
    if settings.DEFAULT_USER_ID:
        try:
            user = await db.users.find_one({"_id": ObjectId(settings.DEFAULT_USER_ID)})
        except Exception:
            pass
    user_name = user["name"] if user else "the resident"

    # ── Recent events (last 7 days) ──────────────────────────────────────────
    cutoff = now - timedelta(days=7)
    cursor = db.events.find(
        {"detected_at": {"$gte": cutoff}},
        sort=[("detected_at", -1)],
        limit=15,
    )
    raw_events = await cursor.to_list(15)

    events_summary = []
    for e in raw_events:
        detected_at = e.get("detected_at", now)
        detected_str = (
            detected_at.strftime("%Y-%m-%d %H:%M UTC")
            if isinstance(detected_at, datetime)
            else str(detected_at)
        )
        events_summary.append({
            "event_type": e.get("event_type", "UNKNOWN"),
            "severity": e.get("severity", "UNKNOWN"),
            "status": e.get("status", "unknown"),
            "detected_at": detected_str,
            "recommended_action": e.get("recommended_action", ""),
        })

    # ── Behavioral schema ────────────────────────────────────────────────────
    threshold_info: dict = {}
    if settings.DEFAULT_USER_ID:
        try:
            schema = await db.behavioral_schema.find_one(
                {"user_id": ObjectId(settings.DEFAULT_USER_ID)}
            )
            if schema:
                threshold_info = schema.get("event_type_history", {})
        except Exception:
            pass

    return await claude_service.answer_dashboard_query(
        user_query=query,
        system_online=system_online,
        last_seen_ago=last_seen_ago,
        user_name=user_name,
        events_summary=events_summary,
        threshold_info=threshold_info,
    )
