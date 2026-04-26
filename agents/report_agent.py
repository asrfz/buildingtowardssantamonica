import logging
from datetime import datetime, timedelta
from bson import ObjectId
from uagents import Agent, Context
from uagents_core.contrib.protocols.chat import ChatMessage
from app.config import settings
from app.database import connect_db, get_db
from app.services import claude_service, gmail_service

logger = logging.getLogger(__name__)

report_agent = Agent(
    name="homepulse_report",
    seed=settings.FETCHAI_AGENT_SEED + "_report",
)

_7D = 60 * 60 * 24 * 7


@report_agent.on_event("startup")
async def startup(ctx: Context) -> None:
    await connect_db()
    ctx.logger.info(f"report_agent online — address: {report_agent.address}")


@report_agent.on_message(ChatMessage)
async def handle_chat(ctx: Context, sender: str, msg: ChatMessage) -> None:
    await ctx.send(sender, ChatMessage(content="HomePulse report_agent online"))


async def generate_and_send_weekly_report(user_id: str, db) -> bool:
    """
    Generate and send a weekly digest on demand.
    Called only when explicitly requested (e.g. via dashboard chat or voice command).
    """
    cutoff = datetime.utcnow() - timedelta(days=7)

    events = await db.events.find({
        "user_id": ObjectId(user_id),
        "detected_at": {"$gte": cutoff},
    }).to_list(100)

    user = await db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        logger.error(f"User {user_id} not found — cannot send report")
        return False

    user_name = user["name"]
    logger.info(f"Generating weekly digest for {user_name} — {len(events)} events")

    serialized = [
        {
            "event_type": e.get("event_type", ""),
            "severity": e.get("severity", ""),
            "confirmed": e.get("confirmed"),
            "detected_at": e.get("detected_at", datetime.utcnow()).strftime("%A %I:%M %p"),
            "status": e.get("status", ""),
        }
        for e in events
    ]

    try:
        digest_html = await claude_service.write_weekly_digest(
            events=serialized,
            user_name=user_name,
        )
    except Exception as e:
        logger.error(f"Claude digest failed: {e}")
        return False

    recipients = [user["email"]] + [c["email"] for c in user.get("emergency_contacts", [])]
    success = await gmail_service.send_weekly_digest(recipients, digest_html)
    if success:
        logger.info(f"Weekly digest sent to {recipients}")
    return success


if __name__ == "__main__":
    report_agent.run()
