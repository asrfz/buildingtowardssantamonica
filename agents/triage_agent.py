import logging
from datetime import datetime
from bson import ObjectId
from uagents import Agent, Context
from uagents.protocols.chat import ChatProtocol, ChatMessage
from app.config import settings
from app.database import connect_db, get_db
from app.services import claude_service
from app.schemas.event_schema import build_event_doc
from agents.agent_messages import (
    IrregularityEvent,
    TriageResult,
    HISTORY_AGENT_ADDRESS,
    VISION_AGENT_ADDRESS,
)

logger = logging.getLogger(__name__)

triage_agent = Agent(
    name="homepulse_triage",
    seed=settings.FETCHAI_AGENT_SEED + "_triage",
)
triage_agent.include(ChatProtocol())


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
        f"Triaging {msg.event_type} (score={msg.deviation_score:.1f}x, fp_rate={fp_rate:.0%})"
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

    ctx.logger.info(
        f"Triage result — investigate={investigate}, "
        f"confidence={confidence:.2f}, reason={reason!r}"
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
        ctx.logger.info(f"Event {event_id} dismissed by Claude: {reason}")
        return

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
        f"Event {event_id} confirmed — fired history_agent + vision_agent in parallel"
    )


if __name__ == "__main__":
    triage_agent.run()
