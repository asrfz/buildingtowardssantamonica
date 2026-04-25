import logging
from datetime import datetime
from bson import ObjectId
from uagents import Agent, Context
from uagents.protocols.chat import ChatProtocol, ChatMessage
from app.config import settings
from app.database import connect_db, get_db
from app.services import claude_service, gmail_service
from agents.agent_messages import EscalationOrder

logger = logging.getLogger(__name__)

notification_agent = Agent(
    name="homepulse_notification",
    seed=settings.FETCHAI_AGENT_SEED + "_notification",
)
notification_agent.include(ChatProtocol())


@notification_agent.on_event("startup")
async def startup(ctx: Context) -> None:
    await connect_db()
    ctx.logger.info(f"notification_agent online — address: {notification_agent.address}")


@notification_agent.on_message(ChatMessage)
async def handle_chat(ctx: Context, sender: str, msg: ChatMessage) -> None:
    await ctx.send(sender, ChatMessage(content="HomePulse notification_agent online"))


@notification_agent.on_message(EscalationOrder)
async def notify(ctx: Context, sender: str, msg: EscalationOrder) -> None:
    db = get_db()

    user = await db.users.find_one({"_id": ObjectId(msg.user_id)})
    user_name = user["name"] if user else "Resident"

    ctx.logger.info(
        f"Writing alert email for {msg.event_type} ({msg.severity}) "
        f"→ {len(msg.recipients)} recipient(s)"
    )

    try:
        email_body = await claude_service.write_alert_email(
            event_type=msg.event_type,
            severity=msg.severity,
            recommended_action=msg.recommended_action,
            sensor_readings=msg.sensor_payload,
            user_name=user_name,
            cancel_window_seconds=msg.cancel_window_seconds,
            image_url=msg.image_url,
        )
    except Exception as e:
        ctx.logger.error(f"Claude email write failed: {e}")
        return

    subject = (
        f"[HomePulse {msg.severity}] "
        f"{msg.event_type.replace('_', ' ').title()} detected"
    )

    success = gmail_service._send(msg.recipients, subject, email_body)

    # Update event record in MongoDB
    try:
        await db.events.update_one(
            {"_id": ObjectId(msg.event_id)},
            {
                "$set": {
                    "notification_sent": success,
                    "email_body": email_body,
                    "notification_sent_at": datetime.utcnow(),
                    "status": "notified" if success else "notification_failed",
                }
            },
        )
    except Exception as e:
        ctx.logger.error(f"Failed to update event {msg.event_id}: {e}")

    if success:
        ctx.logger.info(f"Email sent for event {msg.event_id} to {msg.recipients}")
    else:
        ctx.logger.error(f"Email failed for event {msg.event_id}")


if __name__ == "__main__":
    notification_agent.run()
