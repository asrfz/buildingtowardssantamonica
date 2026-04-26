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
# One browser alert card per event (guards rare double-reason or multi-WS duplicates).
_alert_ui_sent: set[str] = set()


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

    has_frame = bool(
        (vision.cropped_url and vision.cropped_url.strip())
        or (vision.raw_url and vision.raw_url.strip())
    )
    ctx.logger.info(
        f"[4/5] MONITOR  both results in for event {event_id[:8]} — calling Claude reasoning "
        f"(image={'yes' if has_frame else 'no'}, triage_type={history.triage_event_type})"
    )

    try:
        decision = await claude_service.reason_about_event(
            sensor_data=history.sensor_payload,
            deviation_score=history.deviation_score,
            image_url=vision.cropped_url,
            user_history=history.recent_events,
            behavioral_schema=history.behavioral_schema,
            hour=hour,
            day_type=day_type,
            triage_event_type=history.triage_event_type,
            crop_spatially_trusted=getattr(vision, "spatial_crop_trusted", True),
        )
    except Exception as e:
        ctx.logger.error(f"Claude reasoning failed for event {event_id}: {e}")
        return

    confirmed_type = decision.get("confirmed_event_type", "UNKNOWN")
    severity = decision.get("severity", "MEDIUM")
    recommended_action = decision.get("recommended_action", "Please check your home.")
    suggested_service = decision.get("suggested_service", "none")

    # No Cloudinary frame — keep the triage classification so door/movement isn't relabeled as "sound" in the UI/email.
    if not has_frame and history.triage_event_type:
        if confirmed_type != history.triage_event_type:
            ctx.logger.info(
                "[4/5] MONITOR  no image — label locked to triage %s (model had %s)",
                history.triage_event_type,
                confirmed_type,
            )
        confirmed_type = history.triage_event_type

    ctx.logger.info(
        f"[4/5] MONITOR  {confirmed_type} ({severity}) — {recommended_action[:80]}"
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
                    "cropped_thumb_url": getattr(vision, "cropped_thumb_url", "") or "",
                    "monitor_reasoning": decision.get("reasoning", ""),
                    "status": "monitored",
                },
                "$unset": {"context_expanded_image_url": ""},
            },
        )
    except Exception as e:
        ctx.logger.error(f"Failed to update event {event_id}: {e}")

    # Speak the alert and push to frontend WebSocket clients
    event_label = label_for_event_type(confirmed_type)
    alert_text = f"{event_label}. {recommended_action}"
    try:
        await speak_async(alert_text, correction=False)
    except Exception as e:
        ctx.logger.debug(f"TTS speak failed: {e}")
    if event_id not in _alert_ui_sent:
        _alert_ui_sent.add(event_id)
        if len(_alert_ui_sent) > 2000:
            _alert_ui_sent.clear()
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                push_url = f"{settings.HOMEPULSE_API_BASE.rstrip('/')}/voice/push"
                await client.post(push_url, json={
                    "type": "alert",
                    "text": alert_text,
                    "data": {
                        "event_id": event_id,
                        "event_type": confirmed_type,
                        "label": event_label,
                        "severity": severity,
                        "recommended_action": recommended_action,
                        "image_url": vision.cropped_url or vision.raw_url or "",
                        "image_thumb_url": getattr(vision, "cropped_thumb_url", "") or "",
                    },
                })
        except Exception as e:
            ctx.logger.debug(f"WebSocket alert push failed (FastAPI may not be running): {e}")
    else:
        ctx.logger.info("[4/5] MONITOR  skipping duplicate UI alert for event %s", event_id[:8])

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
