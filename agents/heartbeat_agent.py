import logging
from datetime import datetime
from bson import ObjectId
from uagents import Agent, Context
from uagents_core.contrib.protocols.chat import ChatMessage
from app.config import settings
from app.database import connect_db, get_db
from app.services import gmail_service

logger = logging.getLogger(__name__)

heartbeat_agent = Agent(
    name="homepulse_heartbeat",
    seed=settings.FETCHAI_AGENT_SEED + "_heartbeat",
)

_offline_alert_sent = False  # debounce — only send once until sensor comes back


@heartbeat_agent.on_event("startup")
async def startup(ctx: Context) -> None:
    await connect_db()
    ctx.logger.info(f"heartbeat_agent online — address: {heartbeat_agent.address}")


@heartbeat_agent.on_message(ChatMessage)
async def handle_chat(ctx: Context, sender: str, msg: ChatMessage) -> None:
    await ctx.send(sender, ChatMessage(content="HomePulse heartbeat_agent online"))


@heartbeat_agent.on_interval(period=60.0)
async def check_heartbeat(ctx: Context) -> None:
    global _offline_alert_sent

    db = get_db()
    record = await db.agent_heartbeats.find_one({"agent": "sensor_agent"})

    if not record:
        ctx.logger.debug("No heartbeat record yet — sensor_agent may not have started")
        return

    last_seen: datetime = record["last_seen"]
    silence_seconds = (datetime.utcnow() - last_seen).total_seconds()

    if silence_seconds > settings.HEARTBEAT_TIMEOUT_SECONDS:
        if not _offline_alert_sent:
            ctx.logger.warning(
                f"sensor_agent silent for {silence_seconds:.0f}s — firing offline alert"
            )
            user_id = settings.DEFAULT_USER_ID
            if user_id:
                user = await db.users.find_one({"_id": ObjectId(user_id)})
                if user:
                    await gmail_service.send_system_offline_alert(user)
            _offline_alert_sent = True
    else:
        if _offline_alert_sent:
            ctx.logger.info("sensor_agent is back online")
        _offline_alert_sent = False


if __name__ == "__main__":
    heartbeat_agent.run()
