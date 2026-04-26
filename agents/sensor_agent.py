import logging
from datetime import datetime
from uagents import Agent, Context
from uagents_core.contrib.protocols.chat import ChatMessage
from app.config import settings
from app.database import connect_db, get_db
from app.services.anomaly_detector import score_reading
from app.models.sensor import SensorPayload
from app.utils.serial_reader import get_latest_reading, start_serial_reader
from agents.agent_messages import IrregularityEvent, TRIAGE_AGENT_ADDRESS

logger = logging.getLogger(__name__)

sensor_agent = Agent(
    name="homepulse_sensor",
    seed=settings.FETCHAI_AGENT_SEED + "_sensor",
)


@sensor_agent.on_event("startup")
async def startup(ctx: Context) -> None:
    await connect_db()
    start_serial_reader()
    ctx.logger.info(f"sensor_agent online — address: {sensor_agent.address}")


@sensor_agent.on_message(ChatMessage)
async def handle_chat(ctx: Context, sender: str, msg: ChatMessage) -> None:
    await ctx.send(sender, ChatMessage(content="HomePulse sensor_agent online"))


@sensor_agent.on_interval(period=5.0)
async def read_and_score(ctx: Context) -> None:
    raw = get_latest_reading()
    if not raw:
        return

    user_id = settings.DEFAULT_USER_ID
    if not user_id:
        ctx.logger.warning("DEFAULT_USER_ID not set — run scripts/seed_demo.py first")
        return

    try:
        payload = SensorPayload(**raw)
    except Exception as e:
        ctx.logger.warning(f"Invalid serial payload: {e}")
        return

    db = get_db()

    # Update heartbeat so heartbeat_agent knows we are alive
    await db.agent_heartbeats.update_one(
        {"agent": "sensor_agent"},
        {"$set": {"last_seen": datetime.utcnow()}},
        upsert=True,
    )

    result = await score_reading(user_id, payload, db)
    if not result.triggered:
        return

    _SEP = "─" * 56
    ctx.logger.info(_SEP)
    ctx.logger.info(
        f"ANOMALY DETECTED  {result.event_type}"
        f"  score={result.deviation_score:.1f}x  severity={result.severity}  sensor={result.sensor}"
    )
    ctx.logger.info(_SEP)

    if not TRIAGE_AGENT_ADDRESS:
        ctx.logger.warning("TRIAGE_AGENT_ADDRESS not set — run scripts/register_agents.py")
        return

    await ctx.send(
        TRIAGE_AGENT_ADDRESS,
        IrregularityEvent(
            user_id=user_id,
            event_type=result.event_type,
            severity=result.severity,
            deviation_score=result.deviation_score,
            sensor_payload=payload.model_dump(mode="json"),
            timestamp_iso=datetime.utcnow().isoformat(),
        ),
    )


if __name__ == "__main__":
    sensor_agent.run()
