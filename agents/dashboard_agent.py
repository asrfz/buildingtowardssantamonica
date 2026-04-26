"""
dashboard_agent — HomePulse conversational gateway for ASI:One.

Run alongside FastAPI in a separate terminal:
    python agents/dashboard_agent.py

With HOMEPULSE_DASHBOARD_MAILBOX=true: connects to Agentverse via mailbox (ASI:One).
With mailbox false (default): same HTTP bureau as run_agents.py for local voice queries.
"""
import sys
import os
import logging
from datetime import datetime, timezone, timedelta
from uuid import uuid4

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bson import ObjectId
from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    chat_protocol_spec,
    ChatMessage,
    ChatAcknowledgement,
    TextContent,
    StartSessionContent,
)

from app.config import settings
from app.database import connect_db, get_db
from app.services import claude_service
from app.services.claude_service import compact_user_profile_for_prompt
from agents.agent_messages import VoiceQuery, VoiceQueryResponse, VOICE_INPUT_AGENT_ADDRESS

logger = logging.getLogger(__name__)

# Mailbox ON: run `python agents/dashboard_agent.py` with HOMEPULSE_DASHBOARD_MAILBOX=true for ASI:One.
# Mailbox OFF: bundled in run_agents.py — uses bureau HTTP so voice_input → VoiceQuery resolves locally.
_dashboard_mailbox = settings.HOMEPULSE_DASHBOARD_MAILBOX
dashboard_agent = Agent(
    name="homepulse",
    seed=settings.FETCHAI_AGENT_SEED + "_dashboard",
    port=8001 if _dashboard_mailbox else None,
    mailbox=_dashboard_mailbox,
    agentverse=(
        {"api_key": settings.AGENTVERSE_KEY, "url": "https://agentverse.ai"}
        if _dashboard_mailbox
        else None
    ),
)

chat_proto = Protocol(spec=chat_protocol_spec)

_WELCOME = (
    "HomePulse is online. Ask a short question when you're ready — for example "
    "what happened recently, your profile, or past incidents. "
    "I'll keep answers brief unless you ask for a full summary."
)


# ── Startup ──────────────────────────────────────────────────────────────────

@dashboard_agent.on_event("startup")
async def startup(ctx: Context) -> None:
    await connect_db()
    ctx.logger.info(f"HomePulse online — {dashboard_agent.address}")


# ── Keep heartbeat fresh every 90s so system shows as online during demo ─────

@dashboard_agent.on_interval(period=90.0)
async def refresh_heartbeat(ctx: Context) -> None:
    try:
        db = get_db()
        await db.agent_heartbeats.update_one(
            {"agent": "sensor_agent"},
            {"$set": {"last_seen": datetime.now(timezone.utc)}},
            upsert=True,
        )
    except Exception as e:
        ctx.logger.warning(f"Heartbeat refresh failed: {e}")


# ── Chat protocol handlers ────────────────────────────────────────────────────

@chat_proto.on_message(ChatAcknowledgement)
async def handle_ack(ctx: Context, sender: str, msg: ChatAcknowledgement) -> None:
    pass


@chat_proto.on_message(ChatMessage)
async def handle_chat(ctx: Context, sender: str, msg: ChatMessage) -> None:
    await ctx.send(sender, ChatAcknowledgement(acknowledged_msg_id=msg.msg_id))

    # Use the convenience .text() method — handles all content types safely
    query = msg.text().strip()

    # Session-open handshake or empty message → send welcome
    has_session_open = any(isinstance(c, StartSessionContent) for c in msg.content)
    if has_session_open or not query:
        await ctx.send(sender, ChatMessage(content=[TextContent(type="text", text=_WELCOME)]))
        return

    ctx.logger.info(f"Query from {sender[:20]}: {query!r}")

    try:
        reply = await _build_response(query)
    except Exception as e:
        ctx.logger.error(f"Response error: {e}", exc_info=True)
        reply = (
            "I'm having trouble fetching home data right now. "
            "Please try again in a moment."
        )

    await ctx.send(sender, ChatMessage(content=[TextContent(type="text", text=reply)]))


dashboard_agent.include(chat_proto, publish_manifest=True)


# ── Voice input handler (deaf-user spoken queries) ────────────────────────────

@dashboard_agent.on_message(VoiceQuery)
async def handle_voice_query(ctx: Context, sender: str, msg: VoiceQuery) -> None:
    """
    Receives a spoken query transcribed by ElevenLabs Scribe via voice_input_agent.
    Reuses the same _build_response() pipeline as ASI:One chat.
    Sends VoiceQueryResponse back so voice_input_agent can push it to the browser overlay.
    """
    ctx.logger.info(f"[VoiceQuery] {msg.query_id[:8]}: {msg.transcript!r}")
    try:
        answer = await _build_response(msg.transcript)
    except Exception as exc:
        ctx.logger.error(f"VoiceQuery response error: {exc}", exc_info=True)
        answer = "I had trouble fetching that information. Please try again."

    reply_to = VOICE_INPUT_AGENT_ADDRESS or sender
    await ctx.send(
        reply_to,
        VoiceQueryResponse(
            query_id=msg.query_id,
            answer=answer,
            transcript=msg.transcript,
            timestamp_iso=datetime.now(timezone.utc).isoformat(),
        ),
    )


# ── Core response builder ─────────────────────────────────────────────────────

async def _build_response(query: str) -> str:
    db = get_db()
    now = datetime.now(timezone.utc)

    # ── System online status ─────────────────────────────────────────────────
    heartbeat = await db.agent_heartbeats.find_one({"agent": "sensor_agent"})
    system_online = False
    last_seen_ago = "never"
    if heartbeat:
        last_seen = heartbeat.get("last_seen")
        if last_seen:
            # Handle both timezone-aware and naive datetimes from MongoDB
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=timezone.utc)
            silence = (now - last_seen).total_seconds()
            system_online = silence < settings.HEARTBEAT_TIMEOUT_SECONDS
            last_seen_ago = f"{int(silence)}s ago"

    # ── User info ────────────────────────────────────────────────────────────
    user = None
    if settings.DEFAULT_USER_ID:
        try:
            user = await db.users.find_one({"_id": ObjectId(settings.DEFAULT_USER_ID)})
        except Exception:
            pass
    user_name = user["name"] if user else "the resident"

    # ── Recent events — last 7 days, newest first ────────────────────────────
    cutoff = now - timedelta(days=7)
    raw_events = await (
        db.events
        .find({"detected_at": {"$gte": cutoff.replace(tzinfo=None)}})
        .sort("detected_at", -1)
        .limit(15)
        .to_list(15)
    )

    events_summary = []
    for e in raw_events:
        detected_at = e.get("detected_at")
        if isinstance(detected_at, datetime):
            detected_str = detected_at.strftime("%Y-%m-%d %H:%M UTC")
        else:
            detected_str = str(detected_at) if detected_at else "unknown"

        events_summary.append({
            "event_type": e.get("event_type", "UNKNOWN"),
            "severity": e.get("severity", "UNKNOWN"),
            "status": e.get("status", "unknown"),
            "detected_at": detected_str,
            "recommended_action": e.get("recommended_action") or "",
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

    profile = compact_user_profile_for_prompt(user)

    return await claude_service.answer_dashboard_query(
        user_query=query,
        system_online=system_online,
        last_seen_ago=last_seen_ago,
        user_name=user_name,
        events_summary=events_summary,
        threshold_info=threshold_info,
        user_profile=profile,
    )


if __name__ == "__main__":
    dashboard_agent.run()
