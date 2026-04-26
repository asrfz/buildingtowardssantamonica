import logging
from datetime import datetime
from bson import ObjectId
from uagents import Agent, Context
from uagents_core.contrib.protocols.chat import ChatMessage
from app.config import settings
from app.database import connect_db, get_db
from app.services import claude_service, gmail_service
from app.services.incident_service import create_incident_report
from app.utils.event_labels import label_for_event_type
from agents.agent_messages import EscalationOrder

logger = logging.getLogger(__name__)

notification_agent = Agent(
    name="homepulse_notification",
    seed=settings.FETCHAI_AGENT_SEED + "_notification",
)


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
        f"[EMAIL]  drafting {msg.event_type} ({msg.severity})"
        f"  → {len(msg.recipients)} recipient(s)"
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

    subject = f"[HomePulse {msg.severity}] {label_for_event_type(msg.event_type)}"

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
                },
                "$unset": {
                    "pending_email_recipients": "",
                    "pending_email_cancel_window_seconds": "",
                },
            },
        )
    except Exception as e:
        ctx.logger.error(f"Failed to update event {msg.event_id}: {e}")

    if success:
        ctx.logger.info(f"[EMAIL]  sent to {msg.recipients}")
        ctx.logger.info(f"[EMAIL]  subject: {subject}")
    else:
        ctx.logger.error(f"[EMAIL]  FAILED for event {msg.event_id}")

    # Auto-create incident report for MEDIUM+ severity events
    if msg.severity in ("MEDIUM", "HIGH", "CRITICAL"):
        try:
            ev_doc = await db.events.find_one({"_id": ObjectId(msg.event_id)})
            raw_u = (ev_doc or {}).get("raw_image_url") or ""
            crop_u = (ev_doc or {}).get("cropped_image_url") or ""
            image_urls = {
                "raw": raw_u or msg.image_url,
                "cropped": crop_u or msg.image_url,
                "thumb": msg.image_url,
            }
            report_id = await create_incident_report(
                event_id=msg.event_id,
                user_id=msg.user_id,
                event_type=msg.event_type,
                severity=msg.severity,
                sensor_payload=msg.sensor_payload,
                recommended_action=msg.recommended_action,
                image_urls=image_urls,
                db=db,
                resolution="notified" if success else "notification_failed",
            )
            ctx.logger.info(f"[EMAIL]  incident report created: {report_id}")
        except Exception as e:
            ctx.logger.warning(f"Incident report creation failed (non-blocking): {e}")


if __name__ == "__main__":
    notification_agent.run()
