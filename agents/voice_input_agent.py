"""
voice_input_agent -- HomePulse deaf-user voice input agent.

Role in the FetchAI network:
    Bridges spoken queries from deaf users into the HomePulse agent pipeline.
    ElevenLabs Scribe transcribes the speech; FetchAI routes the query to
    dashboard_agent and receives the Claude-generated answer back.

Full pipeline per utterance:
    [User speaks] "Hey HomePulse" only
      -> short TTS greeting ("Hello, how can I help you?") — no automatic home recap
      -> a follow-up window opens where the next utterance does not need the wake phrase
    [User speaks] "Hey HomePulse, what's on my profile?" (or follow-up: "What incidents were there?")
      -> sounddevice captures audio (wake_word_service background thread)
      -> energy VAD detects utterance boundaries
      -> ElevenLabs Scribe (stt_service) transcribes to text
      -> wake word stripped (or whole transcript taken during follow-up window)
      -> voice_input_agent.on_interval picks up from detected_query_queue
      -> VoiceQuery sent to dashboard_agent via FetchAI
      -> dashboard_agent queries Claude + MongoDB, returns VoiceQueryResponse
      -> voice_input_agent POSTs to FastAPI /voice/push
      -> WebSocket broadcasts to all browser clients
      -> On-screen card shows question + answer for the deaf user

FetchAI role:
    - Orchestrates async message passing between the STT capture layer and
      the existing Claude/MongoDB query infrastructure (dashboard_agent).
    - on_interval(1.0s) drains the query queue without blocking the audio thread.
    - State tracking via _pending dict correlates query_id -> transcript so
      the WebSocket push shows the right question alongside each answer.

ElevenLabs role:
    Input:  Scribe v1 transcribes spoken queries (stt_service)
    Output: Not used here -- this agent is purely for query routing.
            The voice_agent handles TTS output for non-deaf users.
"""

import sys
import os
import re
import logging
import httpx
from datetime import datetime
from uuid import uuid4

from bson import ObjectId

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uagents import Agent, Context
from uagents_core.contrib.protocols.chat import ChatMessage

from app.config import settings
from app.database import connect_db, get_db
from app.services.wake_word_service import (
    arm_voice_followup_window,
    start as start_listener,
    detected_query_queue,
)
from app.services.tts_service import speak_async
from agents.agent_messages import (
    VoiceQuery,
    VoiceQueryResponse,
    DASHBOARD_AGENT_ADDRESS,
    NOTIFICATION_AGENT_ADDRESS,
    EscalationOrder,
)

logger = logging.getLogger(__name__)

voice_input_agent = Agent(
    name="homepulse_voice_input",
    seed=settings.FETCHAI_AGENT_SEED + "_voice_input",
)

# query_id -> original transcript; used when pushing answer to WebSocket
_pending: dict[str, str] = {}

# After wake word with no follow-up question — short greeting only (no Claude recap).
VOICE_ASSISTANT_GREETING = "Hello, how can I help you?"

# When STT is filler or small-talk, don't call the dashboard (avoids long sensor recaps).
VOICE_NOT_A_QUESTION_REPLY = (
    "Say what you need — for example your profile, recent alerts, or what's happening at home."
)

# Avoid bare "how" — matches echoed "how can I help you" from TTS. No bare "week"/"report" (TV false positives).
_TOPIC_WORD = re.compile(
    r"\b(?:"
    r"what|when|why|who|where|which|tell|show|list|give|any|status|"
    r"home|house|alert|incidents?|events?|sensor|sensors|monitor|monitoring|"
    r"profile|account|email|contact|emergency|happened|summary|rundown|"
    r"safe|safety|noise|sound|temperature|recent|today|tonight|yesterday|"
    r"morning|wrong|problem|issue|anything|everything|update|"
    r"how['']?s|"
    r"how\s+(?:is|are|was|were|many|much|do|does|did|has|have|long|often|about|goes|come)"
    r")\b",
    re.I,
)

_ECHO_SUBSTRINGS = (
    "how can i help",
    "what can i help",
    "how can i help you today",
    "i'm homepulse",
    "im homepulse",
    "your home safety assistant",
    "home safety assistant",
    "seconds pause",
    "second pause",
    "minutes pause",
    "minute pause",
    "weekly summary",
    "here's your weekly",
    "here is your weekly",
)


def _strip_stt_artifacts(text: str) -> str:
    """Remove Scribe stage directions like '(4 seconds pause)' that falsely add '?' intent."""
    t = re.sub(r"\([^)]*\)", " ", text)
    return re.sub(r"\s+", " ", t).strip()


def _is_likely_assistant_echo(text: str) -> bool:
    n = _strip_stt_artifacts(text).lower()
    return any(s in n for s in _ECHO_SUBSTRINGS)


def _utterance_asks_for_home_data(text: str) -> bool:
    """
    True only if we should run the dashboard / Claude path.
    Blocks casual lines and disfluencies from triggering sensor/event recaps.
    """
    t = _strip_stt_artifacts(text)
    if not t:
        return False
    if _is_likely_assistant_echo(t):
        return False
    if "?" in t:
        return True
    if _TOPIC_WORD.search(t):
        return True
    return False


def _voice_push_url() -> str:
    return f"{settings.HOMEPULSE_API_BASE.rstrip('/')}/voice/push"


# Substrings (anywhere in utterance) that mean "send the deferred alert email"
_EXTERNAL_HELP_PHRASES = (
    "send a message",
    "send message",
    "send an email",
    "send the email",
    "send that email",
    "send notification email",
    "send the notification",
    "send alert email",
    "you can send",
    "go ahead and send",
    "please send",
    "okay send",
    "yes send",
    "email someone",
    "notify someone",
    "get help",
    "send help",
    "call for help",
    "contact someone",
    "message someone to",
    "email my",
    "notify my",
    "tell someone to fix",
    "send someone to",
    "dispatch email",
    "notify my contacts",
    "notify emergency",
    "email them",
    "email it now",
)

# Assistant coaching ("say send email…") — do not treat as user consent to send.
_INSTRUCTIONAL_EMAIL_HINT = re.compile(
    r"\b(?:say|tell\s+them|you\s+can\s+say)\b.{0,52}\b(?:send|e-?mail)\b",
    re.I,
)

# Flexible patterns for STT variants ("it's fine to send an email", "go ahead you can email").
_EXTERNAL_HELP_REGEX = re.compile(
    r"\b("
    r"send\s+(?:an?\s+|the\s+|that\s+)?(?:notification\s+|alert\s+)?(?:e-?mail|mail)\b|"
    r"dispatch\s+(?:the\s+)?(?:e-?mail|notification|alert)\b|"
    r"(?:go\s+ahead|you\s+can|please|okay)[,\s]+(?:and\s+)?(?:send|fire)\s+(?:an?\s+|the\s+)?(?:e-?mail|notification)\b|"
    r"\bnotify\s+(?:my\s+)?(?:contacts?|family|emergency(?:\s+contacts?)?)\b|"
    r"\be-?mail\s+(?:them|it|the\s+alert|my\s+contacts)\b"
    r")",
    re.I,
)


def _transcript_requests_external_help(text: str) -> bool:
    raw = _strip_stt_artifacts(text)
    t = raw.lower().strip()
    if not t:
        return False
    if _INSTRUCTIONAL_EMAIL_HINT.search(raw):
        return False
    if any(p in t for p in _EXTERNAL_HELP_PHRASES):
        return True
    return _EXTERNAL_HELP_REGEX.search(raw) is not None


async def _try_send_pending_escalation_email(ctx: Context, user_id: str) -> bool:
    """
    If there is an event awaiting email confirmation, send EscalationOrder to
    notification_agent. Returns True if a message was dispatched.
    """
    if not user_id or user_id == "unknown":
        ctx.logger.error("[VoiceInput] DEFAULT_USER_ID missing — cannot send help email")
        await speak_async("HomePulse is not configured with a user account for alerts.", correction=False)
        return False

    if not (settings.GMAIL_ADDRESS or "").strip() or not (settings.GMAIL_APP_PASSWORD or "").strip():
        ctx.logger.error("[VoiceInput] GMAIL_ADDRESS / GMAIL_APP_PASSWORD not set — cannot send email")
        await speak_async(
            "Email is not configured on this server. Add Gmail credentials to the HomePulse environment.",
            correction=False,
        )
        await _push("error", "Gmail not configured — alert email not sent.")
        return False

    if not NOTIFICATION_AGENT_ADDRESS:
        ctx.logger.error("[VoiceInput] NOTIFICATION_AGENT_ADDRESS not set — cannot send email")
        await speak_async("Notifications are not configured.", correction=False)
        return False

    db = get_db()
    try:
        event = await db.events.find_one(
            {"user_id": ObjectId(user_id), "status": "awaiting_email_confirmation"},
            sort=[("detected_at", -1)],
        )
    except Exception as e:
        ctx.logger.exception(f"[VoiceInput] Mongo lookup for pending email failed: {e}")
        await speak_async("Could not look up pending alerts.", correction=False)
        return False

    if not event:
        ctx.logger.warning("[VoiceInput] No event in awaiting_email_confirmation for user")
        await speak_async(
            "There is no alert waiting to send by email. Say the wake phrase after an issue is detected.",
            correction=False,
        )
        return False

    recipients = event.get("pending_email_recipients") or []
    if not recipients:
        ctx.logger.error(f"[VoiceInput] Event {event['_id']} missing pending_email_recipients")
        await speak_async("That alert is missing email recipients. Check your account settings.", correction=False)
        return False

    cancel_window = int(event.get("pending_email_cancel_window_seconds", settings.CANCEL_WINDOW_SECONDS))
    event_id = str(event["_id"])
    image_url = (
        event.get("cropped_image_url")
        or event.get("raw_image_url")
        or ""
    )
    recommended = event.get("recommended_action") or "Please check your home."

    order = EscalationOrder(
        event_id=event_id,
        user_id=user_id,
        recipients=list(recipients),
        severity=event.get("severity", "MEDIUM"),
        recommended_action=recommended,
        cancel_window_seconds=cancel_window,
        event_type=event.get("event_type", "UNKNOWN"),
        sensor_payload=event.get("sensor_payload") or {},
        image_url=image_url,
    )

    ctx.logger.info(
        f"[VoiceInput] User requested external help — emailing event {event_id} "
        f"({order.event_type}, {order.severity}) → {len(recipients)} recipient(s)"
    )

    await ctx.send(NOTIFICATION_AGENT_ADDRESS, order)
    ctx.logger.info("[VoiceInput] EscalationOrder sent to notification_agent — Gmail send runs there")
    await speak_async("Okay. Sending the notification email now.", correction=False)
    await _push("answer", "Sending notification email for the latest alert.")
    arm_voice_followup_window()
    return True


# ── Startup ───────────────────────────────────────────────────────────────────

@voice_input_agent.on_event("startup")
async def startup(ctx: Context) -> None:
    await connect_db()
    start_listener()    # starts wake_word_service background thread
    ctx.logger.info(f"voice_input_agent online -- address: {voice_input_agent.address}")
    ctx.logger.info("Wake word listener started. Say 'Hey HomePulse' to query.")
    await _push("listening", "")


# ── Drain query queue every second ───────────────────────────────────────────

@voice_input_agent.on_interval(period=1.0)
async def poll_queries(ctx: Context) -> None:
    """
    Pick up queries that the wake_word_service background thread deposited.
    Sends each one to dashboard_agent as a VoiceQuery.
    """
    while not detected_query_queue.empty():
        try:
            question = detected_query_queue.get_nowait()
        except Exception:
            break

        question = (question or "").strip()
        if not question:
            ctx.logger.info("[VoiceInput] Wake-only — greeting user (no dashboard query)")
            await _push("transcript", "")
            await _push("answer", VOICE_ASSISTANT_GREETING)
            await speak_async(VOICE_ASSISTANT_GREETING, correction=False)
            arm_voice_followup_window()
            continue

        query_id = str(uuid4())
        ctx.logger.info(f"[VoiceInput] Heard {query_id[:8]}: {question!r}")
        await _push("transcript", question)

        if _is_likely_assistant_echo(question):
            ctx.logger.info("[VoiceInput] Ignoring likely TTS / assistant echo — not routing")
            continue

        if _transcript_requests_external_help(question):
            uid = settings.DEFAULT_USER_ID or ""
            await _try_send_pending_escalation_email(ctx, uid)
            continue

        if not _utterance_asks_for_home_data(question):
            ctx.logger.info(
                "[VoiceInput] Not routing to dashboard — no home/profile/incident question: %r",
                question,
            )
            await _push("answer", VOICE_NOT_A_QUESTION_REPLY)
            await speak_async(VOICE_NOT_A_QUESTION_REPLY, correction=False)
            arm_voice_followup_window()
            continue

        if not DASHBOARD_AGENT_ADDRESS:
            ctx.logger.warning("DASHBOARD_AGENT_ADDRESS not set -- cannot route query")
            await _push("error", "Dashboard agent not configured.")
            continue

        _pending[query_id] = question
        await ctx.send(
            DASHBOARD_AGENT_ADDRESS,
            VoiceQuery(
                query_id=query_id,
                user_id=settings.DEFAULT_USER_ID or "unknown",
                transcript=question,
                timestamp_iso=datetime.utcnow().isoformat(),
            ),
        )


# ── Receive answer from dashboard_agent ───────────────────────────────────────

@voice_input_agent.on_message(VoiceQueryResponse)
async def handle_response(ctx: Context, sender: str, msg: VoiceQueryResponse) -> None:
    """
    Receives the Claude answer from dashboard_agent and pushes it to the
    browser overlay via the FastAPI /voice/push endpoint.
    """
    transcript = _pending.pop(msg.query_id, msg.transcript)
    ctx.logger.info(f"[VoiceInput] Answer for {msg.query_id[:8]}: {msg.answer[:60]}...")
    await _push("answer", msg.answer)
    await speak_async(msg.answer, correction=False)
    arm_voice_followup_window()


# ── ASI:One passthrough ───────────────────────────────────────────────────────

@voice_input_agent.on_message(ChatMessage)
async def handle_chat(ctx: Context, sender: str, msg: ChatMessage) -> None:
    await ctx.send(sender, ChatMessage(content="HomePulse voice_input_agent online"))


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _push(msg_type: str, text: str) -> None:
    """POST a message to the FastAPI WebSocket push endpoint."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            await client.post(_voice_push_url(), json={"type": msg_type, "text": text})
    except Exception as exc:
        logger.warning(
            "[VoiceInput] WebSocket push failed (is uvicorn on :8000?): %s",
            exc,
            exc_info=True,
        )


if __name__ == "__main__":
    voice_input_agent.run()
