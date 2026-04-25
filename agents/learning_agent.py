import logging
from uagents import Agent, Context
from uagents.protocols.chat import ChatProtocol, ChatMessage
from app.config import settings
from app.database import connect_db, get_db
from app.services.learning_service import refresh_behavioral_schema, adjust_threshold

logger = logging.getLogger(__name__)

learning_agent = Agent(
    name="homepulse_learning",
    seed=settings.FETCHAI_AGENT_SEED + "_learning",
)
learning_agent.include(ChatProtocol())

# 24 hours in seconds
_24H = 60 * 60 * 24


@learning_agent.on_event("startup")
async def startup(ctx: Context) -> None:
    await connect_db()
    ctx.logger.info(f"learning_agent online — address: {learning_agent.address}")


@learning_agent.on_message(ChatMessage)
async def handle_chat(ctx: Context, sender: str, msg: ChatMessage) -> None:
    await ctx.send(sender, ChatMessage(content="HomePulse learning_agent online"))


@learning_agent.on_interval(period=float(_24H))
async def daily_refresh(ctx: Context) -> None:
    user_id = settings.DEFAULT_USER_ID
    if not user_id:
        ctx.logger.warning("DEFAULT_USER_ID not set — skipping learning refresh")
        return

    db = get_db()
    ctx.logger.info("Running daily behavioral schema refresh")

    await refresh_behavioral_schema(user_id, db)

    # Adjust threshold for all tracked event types
    schema = await db.behavioral_schema.find_one({"user_id": __import__("bson").ObjectId(user_id)})
    if schema:
        for event_type in schema.get("event_type_history", {}):
            await adjust_threshold(user_id, event_type, db)

    ctx.logger.info("Daily learning refresh complete")


if __name__ == "__main__":
    learning_agent.run()
