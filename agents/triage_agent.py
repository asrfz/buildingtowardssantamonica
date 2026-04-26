import logging
import httpx
from datetime import datetime
from bson import ObjectId
from uagents import Agent, Context
from uagents_core.contrib.protocols.chat import ChatMessage
from app.config import settings
from app.database import connect_db, get_db
from app.services import claude_service
from app.services.tts_service import speak_async
from app.schemas.event_schema import build_event_doc
from agents.agent_messages import (
    IrregularityEvent,
    TriageResult,
    HISTORY_AGENT_ADDRESS,
    VISION_AGENT_ADDRESS,
)

logger = logging.getLogger(__name__)


def _voice_push_url() -> str:
    return f"{settings.HOMEPULSE_API_BASE.rstrip('/')}/voice/push"


def _sensor_alert_text(event_type: str, payload: dict, sensor_reason: str) -> str:
    """Build an immediate, plain-language TTS announcement from raw sensor data."""
    temp  = payload.get("temperature_c", 0)
    sound = payload.get("sound_level", 0)

    if event_type == "TEMPERATURE_ANOMALY":
        if temp > 30:
            return f"Higher than normal temperature detected — currently {temp:.0f} degrees. Activating camera."
        elif temp < 15:
            return f"Lower than normal temperature detected — currently {temp:.0f} degrees. Activating camera."
        else:
            return f"Unusual temperature reading — {temp:.0f} degrees. Activating camera."

    if event_type == "SOUND_ANOMALY":
        if sound > 600:
            return f"Loud noise detected — sound level {sound:.0f}. Activating camera."
        elif sound < 200:
            return f"Unusual low-level noise detected. Activating camera."
        else:
            return f"Unusual noise detected. Activating camera."

    if event_type == "DOOR_SENSOR_ANOMALY":
        return "Door or enclosure opened unexpectedly. Activating camera."

    if event_type == "OBJECT_DROPPED":
        return "Drop or impact detected. Activating camera."

    if event_type == "LIGHT_STATE_CHANGED":
        return "Unexpected light change detected. Activating camera."

    if event_type == "FALL_DETECTED":
        return "Possible fall detected. Activating camera immediately."

    if event_type == "FIRE_RISK":
        return "Fire risk detected by sensors. Activating camera."

    if event_type == "MULTIVARIATE_ANOMALY":
        return "Multiple sensor irregularities detected simultaneously. Activating camera."

    return f"Sensor irregularity detected. Activating camera."


async def _push_status(text: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            await client.post(_voice_push_url(), json={"type": "transcript", "text": text})
    except Exception:
        pass


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

    await ctx.send(HISTORY_AGENT_ADDRESS, triage_result)
    await ctx.send(VISION_AGENT_ADDRESS, triage_result)

    ctx.logger.info(
        f"[2/5] PIPELINE  event {event_id[:8]} → history_agent + vision_agent in parallel"
    )


if __name__ == "__main__":
    triage_agent.run()
