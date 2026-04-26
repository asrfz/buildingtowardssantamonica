import logging
from datetime import datetime
from bson import ObjectId
from uagents import Agent, Context
from uagents_core.contrib.protocols.chat import ChatMessage
from app.config import settings
from app.database import connect_db, get_db
from agents.agent_messages import TriageResult, UserHistoryContext, MONITOR_AGENT_ADDRESS

logger = logging.getLogger(__name__)

history_agent = Agent(
    name="homepulse_history",
    seed=settings.FETCHAI_AGENT_SEED + "_history",
)


@history_agent.on_event("startup")
async def startup(ctx: Context) -> None:
    await connect_db()
    ctx.logger.info(f"history_agent online — address: {history_agent.address}")


@history_agent.on_message(ChatMessage)
async def handle_chat(ctx: Context, sender: str, msg: ChatMessage) -> None:
    await ctx.send(sender, ChatMessage(content="HomePulse history_agent online"))


@history_agent.on_message(TriageResult)
async def pull_history(ctx: Context, sender: str, msg: TriageResult) -> None:
    db = get_db()

    # Pull last 10 events of this type for this user
    recent_events = await db.events.find(
        {
            "user_id": ObjectId(msg.user_id),
            "event_type": msg.event_type,
        },
        sort=[("detected_at", -1)],
    ).to_list(10)

    # Serialize for message passing (ObjectIds → strings)
    serialized_events = []
    for e in recent_events:
        serialized_events.append({
            "event_id": str(e["_id"]),
            "severity": e.get("severity", ""),
            "confirmed": e.get("confirmed"),
            "detected_at": e.get("detected_at", datetime.utcnow()).isoformat(),
            "status": e.get("status", ""),
        })

    # Pull behavioral schema
    schema_doc = await db.behavioral_schema.find_one({"user_id": ObjectId(msg.user_id)})
    behavioral_schema = {}
    if schema_doc:
        behavioral_schema = schema_doc.get("event_type_history", {})

    ctx.logger.info(
        f"[3a/5] HISTORY  event {msg.event_id[:8]}"
        f"  {len(serialized_events)} prior {msg.event_type} events found"
    )

    if not MONITOR_AGENT_ADDRESS:
        ctx.logger.warning("MONITOR_AGENT_ADDRESS not set")
        return

    await ctx.send(
        MONITOR_AGENT_ADDRESS,
        UserHistoryContext(
            event_id=msg.event_id,
            user_id=msg.user_id,
            sensor_payload=msg.sensor_payload,
            deviation_score=msg.deviation_score,
            recent_events=serialized_events,
            behavioral_schema=behavioral_schema,
            timestamp_iso=datetime.utcnow().isoformat(),
        ),
    )


if __name__ == "__main__":
    history_agent.run()
