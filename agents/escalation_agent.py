import logging
from bson import ObjectId
from uagents import Agent, Context
from uagents_core.contrib.protocols.chat import ChatMessage
from app.config import settings
from app.database import connect_db, get_db
from agents.agent_messages import MonitorDecision, EscalationOrder, NOTIFICATION_AGENT_ADDRESS

logger = logging.getLogger(__name__)

escalation_agent = Agent(
    name="homepulse_escalation",
    seed=settings.FETCHAI_AGENT_SEED + "_escalation",
)


@escalation_agent.on_event("startup")
async def startup(ctx: Context) -> None:
    await connect_db()
    ctx.logger.info(f"escalation_agent online — address: {escalation_agent.address}")


@escalation_agent.on_message(ChatMessage)
async def handle_chat(ctx: Context, sender: str, msg: ChatMessage) -> None:
    await ctx.send(sender, ChatMessage(content="HomePulse escalation_agent online"))


@escalation_agent.on_message(MonitorDecision)
async def escalate(ctx: Context, sender: str, msg: MonitorDecision) -> None:
    db = get_db()

    user = await db.users.find_one({"_id": ObjectId(msg.user_id)})
    if not user:
        ctx.logger.error(f"User {msg.user_id} not found — cannot escalate")
        return

    # Severity ladder: LOW is logged only, others notify
    if msg.severity == "LOW":
        ctx.logger.info(f"Event {msg.event_id} is LOW severity — logged, no notification sent")
        await db.events.update_one(
            {"_id": ObjectId(msg.event_id)},
            {"$set": {"status": "logged_low"}},
        )
        return

    recipients: list[str] = [user["email"]]
    if msg.severity in ("HIGH", "CRITICAL"):
        for contact in user.get("emergency_contacts", []):
            recipients.append(contact["email"])

    cancel_window = 0 if msg.severity == "CRITICAL" else settings.CANCEL_WINDOW_SECONDS

    ctx.logger.info(
        f"Escalating event {msg.event_id} ({msg.severity}) "
        f"to {len(recipients)} recipient(s), cancel_window={cancel_window}s"
    )

    if not NOTIFICATION_AGENT_ADDRESS:
        ctx.logger.warning("NOTIFICATION_AGENT_ADDRESS not set")
        return

    await ctx.send(
        NOTIFICATION_AGENT_ADDRESS,
        EscalationOrder(
            event_id=msg.event_id,
            user_id=msg.user_id,
            recipients=recipients,
            severity=msg.severity,
            recommended_action=msg.recommended_action,
            cancel_window_seconds=cancel_window,
            event_type=msg.confirmed_event_type,
            sensor_payload={},   # already stored in MongoDB at this point
            image_url=msg.image_url,
        ),
    )


if __name__ == "__main__":
    escalation_agent.run()
