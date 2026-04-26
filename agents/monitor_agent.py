import logging
from datetime import datetime
from bson import ObjectId
from uagents import Agent, Context
from uagents_core.contrib.protocols.chat import ChatMessage
from app.config import settings
from app.database import connect_db, get_db
from app.services import claude_service
from app.utils.event_labels import label_for_event_type
from agents.agent_messages import (
    UserHistoryContext,
    VisionResult,
    MonitorDecision,
    ESCALATION_AGENT_ADDRESS,
)

logger = logging.getLogger(__name__)

monitor_agent = Agent(
    name="homepulse_monitor",
    seed=settings.FETCHAI_AGENT_SEED + "_monitor",
)

# In-memory state: collects history + vision results per event_id before reasoning.
# Safe because uAgents event loop is single-threaded.
_pending: dict[str, dict] = {}


@monitor_agent.on_event("startup")
async def startup(ctx: Context) -> None:
    await connect_db()
    ctx.logger.info(f"monitor_agent online — address: {monitor_agent.address}")


@monitor_agent.on_message(ChatMessage)
async def handle_chat(ctx: Context, sender: str, msg: ChatMessage) -> None:
    await ctx.send(sender, ChatMessage(content="HomePulse monitor_agent online"))


@monitor_agent.on_message(UserHistoryContext)
async def got_history(ctx: Context, sender: str, msg: UserHistoryContext) -> None:
    _pending.setdefault(msg.event_id, {})["history"] = msg
    await _try_reason(ctx, msg.event_id)


@monitor_agent.on_message(VisionResult)
async def got_vision(ctx: Context, sender: str, msg: VisionResult) -> None:
    _pending.setdefault(msg.event_id, {})["vision"] = msg
    await _try_reason(ctx, msg.event_id)


async def _try_reason(ctx: Context, event_id: str) -> None:
    data = _pending.get(event_id, {})
    if "history" not in data or "vision" not in data:
        return  # still waiting for the other agent

    history: UserHistoryContext = data.pop("history")
    vision: VisionResult = data.pop("vision")
    _pending.pop(event_id, None)

    now = datetime.utcnow()
    hour = now.hour
    day_type = "weekend" if now.weekday() >= 5 else "weekday"

    ctx.logger.info(f"Both results received for event {event_id} — calling Claude")

    try:
        decision = await claude_service.reason_about_event(
            sensor_data=history.sensor_payload,
            deviation_score=history.deviation_score,
            image_url=vision.cropped_url,
            user_history=history.recent_events,
            behavioral_schema=history.behavioral_schema,
            hour=hour,
            day_type=day_type,
        )
    except Exception as e:
        ctx.logger.error(f"Claude reasoning failed for event {event_id}: {e}")
        return

    confirmed_type = decision.get("confirmed_event_type", "UNKNOWN")
    severity = decision.get("severity", "MEDIUM")
    recommended_action = decision.get("recommended_action", "Please check your home.")
    suggested_service = decision.get("suggested_service", "none")

    ctx.logger.info(
        f"Monitor decision: {confirmed_type} ({severity}) — {recommended_action}"
    )

    # Update event in MongoDB with full reasoning
    db = get_db()
    try:
        await db.events.update_one(
            {"_id": ObjectId(event_id)},
            {
                "$set": {
                    "event_type": confirmed_type,
                    "event_label": label_for_event_type(confirmed_type),
                    "severity": severity,
                    "recommended_action": recommended_action,
                    "suggested_service": suggested_service,
                    "raw_image_url": vision.raw_url,
                    "cropped_image_url": vision.cropped_url,
                    "monitor_reasoning": decision.get("reasoning", ""),
                    "status": "monitored",
                }
            },
        )
    except Exception as e:
        ctx.logger.error(f"Failed to update event {event_id}: {e}")

    if not ESCALATION_AGENT_ADDRESS:
        ctx.logger.warning("ESCALATION_AGENT_ADDRESS not set")
        return

    await ctx.send(
        ESCALATION_AGENT_ADDRESS,
        MonitorDecision(
            event_id=event_id,
            user_id=history.user_id,
            confirmed_event_type=confirmed_type,
            severity=severity,
            recommended_action=recommended_action,
            suggested_service=suggested_service,
            image_url=vision.cropped_url,
            timestamp_iso=datetime.utcnow().isoformat(),
            sensor_payload=history.sensor_payload,
        ),
    )


if __name__ == "__main__":
    monitor_agent.run()
