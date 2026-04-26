import logging
import httpx
from datetime import datetime
from bson import ObjectId
from uagents import Agent, Context
from uagents_core.contrib.protocols.chat import ChatMessage
from app.config import settings
from app.database import connect_db, get_db
from app.services import claude_service
from app.services.snapshot_cloudinary_gate import grant_upload_slot
from app.services.tts_service import speak_async
from app.schemas.event_schema import build_event_doc
from agents.agent_messages import (
    IrregularityEvent,
    TriageResult,
    HISTORY_AGENT_ADDRESS,
    VISION_AGENT_ADDRESS,
    NOTIFICATION_AGENT_ADDRESS,
    EscalationOrder,
)

logger = logging.getLogger(__name__)


def _voice_push_url() -> str:
    return f"{settings.HOMEPULSE_API_BASE.rstrip('/')}/voice/push"


def _sensor_alert_text(event_type: str, payload: dict, sensor_reason: str) -> str:
    """Build an immediate, plain-language TTS announcement from raw sensor data."""
    temp = payload.get("temperature_c")
    sound = payload.get("sound_level", 0)

    _tail = "Running a quick safety check."

    if event_type == "TEMPERATURE_ANOMALY":
        if isinstance(temp, (int, float)):
            if temp > 30:
                return f"Higher than normal temperature detected — currently {temp:.0f} degrees. {_tail}"
            if temp < 15:
                return f"Lower than normal temperature detected — currently {temp:.0f} degrees. {_tail}"
            return f"Unusual temperature reading — {temp:.0f} degrees. {_tail}"
        return f"Unusual temperature pattern reported by sensors. {_tail}"

    if event_type == "SOUND_ANOMALY":
        if sound > 600:
            return f"Loud noise detected — sound level {sound:.0f}. {_tail}"
        elif sound < 200:
            return f"Unusual low-level noise detected. {_tail}"
        else:
            return f"Unusual noise detected. {_tail}"

    if event_type == "DOOR_SENSOR_ANOMALY":
        return f"Door or enclosure sensor changed unexpectedly. {_tail}"

    if event_type == "OBJECT_DROPPED":
        return f"Drop or impact detected. {_tail}"

    if event_type == "LIGHT_STATE_CHANGED":
        return f"Unexpected light change detected. {_tail}"

    if event_type == "FALL_DETECTED":
        return "Possible fall detected. Please assess if you can do so safely."

    if event_type == "FIRE_RISK":
        return f"Fire risk flagged by sensors. {_tail}"

    if event_type == "MULTIVARIATE_ANOMALY":
        return f"Multiple sensor irregularities at once. {_tail}"

    return f"Sensor irregularity detected. {_tail}"


async def _push_status(text: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            await client.post(_voice_push_url(), json={"type": "transcript", "text": text})
    except Exception:
        pass


_STREAK_VOICE = (
    "Three repeated sensor alerts were detected with no acknowledged response from the home. "
    "I'm sending an email to your emergency contact now."
)


async def _sensor_streak_email_recipients(user_id: str, severity: str) -> list[str]:
    """Primary user + emergency contacts when auto-escalating after consecutive sensor trips."""
    user = await get_db().users.find_one({"_id": ObjectId(user_id)})
    if not user:
        return []
    emails: list[str] = []
    if user.get("email"):
        emails.append(user["email"])
    if severity in ("MEDIUM", "HIGH", "CRITICAL"):
        for contact in user.get("emergency_contacts") or []:
            em = (contact or {}).get("email")
            if em:
                emails.append(em)
    seen: set[str] = set()
    out: list[str] = []
    for e in emails:
        if e and e not in seen:
            seen.add(e)
            out.append(e)
    return out


triage_agent = Agent(
    name="homepulse_triage",
    seed=settings.FETCHAI_AGENT_SEED + "_triage",
)


@triage_agent.on_event("startup")
async def startup(ctx: Context) -> None:
    await connect_db()
    ctx.logger.info(f"triage_agent online — address: {triage_agent.address}")


@triage_agent.on_message(ChatMessage)
async def handle_chat(ctx: Context, sender: str, msg: ChatMessage) -> None:
    await ctx.send(sender, ChatMessage(content="HomePulse triage_agent online"))


@triage_agent.on_message(IrregularityEvent)
async def triage(ctx: Context, sender: str, msg: IrregularityEvent) -> None:
    db = get_db()
    now = datetime.utcnow()
    hour = now.hour
    day_type = "weekend" if now.weekday() >= 5 else "weekday"

    # Pull false positive rate from behavioral_schema (default 0.2 if no history)
    schema = await db.behavioral_schema.find_one({"user_id": ObjectId(msg.user_id)})
    fp_rate = 0.2
    if schema:
        fp_rate = (
            schema.get("event_type_history", {})
            .get(msg.event_type, {})
            .get("false_positive_rate", 0.2)
        )

    ctx.logger.info(
        f"[1/5] TRIAGE  {msg.event_type}"
        f"  score={msg.deviation_score:.1f}x  fp_rate={fp_rate:.0%}"
    )

    try:
        result = await claude_service.triage_event(
            event_type=msg.event_type,
            deviation_score=msg.deviation_score,
            sensor_payload=msg.sensor_payload,
            hour=hour,
            day_type=day_type,
            recent_false_positive_rate=fp_rate,
        )
    except Exception as e:
        ctx.logger.error(f"Claude triage failed: {e}")
        return

    investigate: bool = result.get("investigate", False)
    confidence: float = result.get("confidence", 0.0)
    reason: str = result.get("reason", "")

    outcome = "CONFIRMED" if investigate else "DISMISSED"
    ctx.logger.info(
        f"[1/5] TRIAGE  {outcome}  confidence={confidence:.0%}  reason={reason!r}"
    )

    # Write event to MongoDB regardless of outcome
    doc = build_event_doc(
        user_id=msg.user_id,
        event_type=msg.event_type,
        severity=msg.severity,
        deviation_score=msg.deviation_score,
        sensor_payload=msg.sensor_payload,
        status="dismissed" if not investigate else "triaged",
    )
    doc["triage_reason"] = reason
    doc["triage_confidence"] = confidence

    inserted = await db.events.insert_one(doc)
    event_id = str(inserted.inserted_id)

    if not investigate:
        ctx.logger.info(f"[1/5] TRIAGE  event {event_id[:8]} dismissed — pipeline stopped")
        return

    # Speak sensor-specific alert immediately — before camera analysis runs
    alert_text = _sensor_alert_text(msg.event_type, msg.sensor_payload, msg.sensor_reason)
    try:
        await speak_async(alert_text, correction=False)
        await _push_status(alert_text)
    except Exception as e:
        ctx.logger.debug(f"Early TTS/push failed (non-blocking): {e}")

    thr = settings.SENSOR_STREAK_EMAIL_THRESHOLD
    if msg.consecutive_sensor_triggers >= thr:
        ctx.logger.info(
            f"[1/5] TRIAGE  sensor streak {msg.consecutive_sensor_triggers} ≥ {thr} — auto emergency email"
        )
        try:
            await speak_async(_STREAK_VOICE, correction=False)
            await _push_status(_STREAK_VOICE)
        except Exception as e:
            ctx.logger.debug(f"Streak TTS/push failed (non-blocking): {e}")

        recipients = await _sensor_streak_email_recipients(msg.user_id, msg.severity)
        if not recipients:
            ctx.logger.warning("[1/5] TRIAGE  streak escalation: no email recipients on user doc")
            try:
                await speak_async(
                    "I need to reach your emergency contact, but no email is configured. Please add one in settings.",
                    correction=False,
                )
            except Exception:
                pass
        elif NOTIFICATION_AGENT_ADDRESS:
            cancel_window = 0 if msg.severity == "CRITICAL" else settings.CANCEL_WINDOW_SECONDS
            await ctx.send(
                NOTIFICATION_AGENT_ADDRESS,
                EscalationOrder(
                    event_id=event_id,
                    user_id=msg.user_id,
                    recipients=recipients,
                    severity=msg.severity,
                    recommended_action=(
                        f"HomePulse automated escalation: {msg.consecutive_sensor_triggers} consecutive "
                        "sensor anomalies with no user acknowledgment. Please check on the resident."
                    ),
                    cancel_window_seconds=cancel_window,
                    event_type=msg.event_type,
                    sensor_payload=msg.sensor_payload,
                    image_url="",
                ),
            )
        else:
            ctx.logger.warning("NOTIFICATION_AGENT_ADDRESS not set — streak email skipped")

    # Fire history_agent and vision_agent in parallel — both forward to monitor_agent
    if not HISTORY_AGENT_ADDRESS or not VISION_AGENT_ADDRESS:
        ctx.logger.warning("HISTORY/VISION agent addresses not set — run scripts/register_agents.py")
        return

    triage_result = TriageResult(
        user_id=msg.user_id,
        event_id=event_id,
        event_type=msg.event_type,
        severity=msg.severity,
        deviation_score=msg.deviation_score,
        sensor_payload=msg.sensor_payload,
        confidence=confidence,
        triage_reason=reason,
        investigate=True,
        timestamp_iso=datetime.utcnow().isoformat(),
    )

    await grant_upload_slot(db, msg.user_id)

    await ctx.send(HISTORY_AGENT_ADDRESS, triage_result)
    await ctx.send(VISION_AGENT_ADDRESS, triage_result)

    ctx.logger.info(
        f"[2/5] PIPELINE  event {event_id[:8]} → history_agent + vision_agent in parallel"
    )


if __name__ == "__main__":
    triage_agent.run()
