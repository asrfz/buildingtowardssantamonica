import logging
import time
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

# Same collection name as app.routers.sensor.SIMULATION_QUEUE_COLL
_SIM_COLL = "sensor_simulation_queue"

# Consecutive anomaly ticks (score triggered or force_triage). Reset when a tick is normal.
_alert_streak: int = 0
# (user_id, event_type) -> monotonic time when another full pipeline may fire
_anomaly_cooldown_until: dict[tuple[str, str], float] = {}

sensor_agent = Agent(
    name="homepulse_sensor",
    seed=settings.FETCHAI_AGENT_SEED + "_sensor",
)


@sensor_agent.on_event("startup")
async def startup(ctx: Context) -> None:
    await connect_db()
    if settings.ARDUINO_SERIAL_ENABLED:
        start_serial_reader()
        ctx.logger.info(
            "sensor_agent online — serial reader on %s",
            settings.ARDUINO_SERIAL_PORT,
        )
    else:
        ctx.logger.warning(
            "sensor_agent online — ARDUINO_SERIAL_ENABLED=false (no COM open; use /sensor/simulate)"
        )
    ctx.logger.info(f"sensor_agent address: {sensor_agent.address}")


@sensor_agent.on_message(ChatMessage)
async def handle_chat(ctx: Context, sender: str, msg: ChatMessage) -> None:
    await ctx.send(sender, ChatMessage(content="HomePulse sensor_agent online"))


async def _pop_simulation_doc(db):
    """FIFO doc from FastAPI /sensor/simulate — works across processes."""
    return await db[_SIM_COLL].find_one_and_delete({}, sort=[("created_at", 1)])


def _anomaly_on_cooldown(user_id: str, event_type: str) -> float:
    """Return seconds remaining on cooldown, or 0 if a new pipeline may run."""
    cd = float(settings.SENSOR_ANOMALY_COOLDOWN_SECONDS or 0)
    if cd <= 0:
        return 0.0
    until = _anomaly_cooldown_until.get((user_id, event_type), 0.0)
    return max(0.0, until - time.monotonic())


def _arm_anomaly_cooldown(user_id: str, event_type: str) -> None:
    cd = float(settings.SENSOR_ANOMALY_COOLDOWN_SECONDS or 0)
    if cd > 0:
        _anomaly_cooldown_until[(user_id, event_type)] = time.monotonic() + cd


@sensor_agent.on_interval(period=5.0)
async def read_and_score(ctx: Context) -> None:
    global _alert_streak
    user_id = settings.DEFAULT_USER_ID
    if not user_id:
        ctx.logger.warning("DEFAULT_USER_ID not set — run scripts/seed_demo.py first")
        return

    db = get_db()

    sim_doc = await _pop_simulation_doc(db)
    if sim_doc:
        raw = sim_doc["payload"]
        force_triage = sim_doc.get("force_triage")
    else:
        raw = get_latest_reading()
        force_triage = None

    if not raw:
        return

    try:
        payload = SensorPayload(**raw)
    except Exception as e:
        ctx.logger.warning(f"Invalid serial payload: {e}")
        return

    # Update heartbeat so heartbeat_agent knows we are alive
    await db.agent_heartbeats.update_one(
        {"agent": "sensor_agent"},
        {"$set": {"last_seen": datetime.utcnow()}},
        upsert=True,
    )

    if not TRIAGE_AGENT_ADDRESS:
        ctx.logger.warning("TRIAGE_AGENT_ADDRESS not set — run scripts/register_agents.py")
        return

    if isinstance(force_triage, dict) and force_triage.get("event_type"):
        et = str(force_triage["event_type"])
        remain = _anomaly_on_cooldown(user_id, et)
        if remain > 0:
            ctx.logger.info(
                "FORCED SIMULATION suppressed (cooldown %.0fs left) event_type=%s",
                remain,
                et,
            )
            return
        _alert_streak += 1
        streak = _alert_streak
        sev = str(force_triage.get("severity", "HIGH"))
        score = float(force_triage.get("deviation_score", 5.0))
        reason = str(force_triage.get("reason", "forced_simulation"))
        _SEP = "─" * 56
        ctx.logger.info(_SEP)
        ctx.logger.info(f"FORCED SIMULATION → triage  {et}  severity={sev}  score={score}  streak={streak}")
        ctx.logger.info(_SEP)
        await ctx.send(
            TRIAGE_AGENT_ADDRESS,
            IrregularityEvent(
                user_id=user_id,
                event_type=et,
                severity=sev,
                deviation_score=score,
                sensor_payload=payload.model_dump(mode="json"),
                sensor_reason=reason,
                timestamp_iso=datetime.utcnow().isoformat(),
                consecutive_sensor_triggers=streak,
            ),
        )
        _arm_anomaly_cooldown(user_id, et)
        if streak >= settings.SENSOR_STREAK_EMAIL_THRESHOLD:
            _alert_streak = 0
        return

    result = await score_reading(user_id, payload, db)
    if not result.triggered:
        _alert_streak = 0
        return

    remain = _anomaly_on_cooldown(user_id, result.event_type)
    if remain > 0:
        ctx.logger.info(
            "ANOMALY suppressed (cooldown %.0fs left) %s score=%.1fx — not opening another full pipeline",
            remain,
            result.event_type,
            result.deviation_score,
        )
        return

    _alert_streak += 1
    streak = _alert_streak

    _SEP = "─" * 56
    ctx.logger.info(_SEP)
    ctx.logger.info(
        f"ANOMALY DETECTED  {result.event_type}"
        f"  score={result.deviation_score:.1f}x  severity={result.severity}  sensor={result.sensor}"
        f"  streak={streak}"
    )
    ctx.logger.info(_SEP)

    await ctx.send(
        TRIAGE_AGENT_ADDRESS,
        IrregularityEvent(
            user_id=user_id,
            event_type=result.event_type,
            severity=result.severity,
            deviation_score=result.deviation_score,
            sensor_payload=payload.model_dump(mode="json"),
            sensor_reason=result.reason,
            timestamp_iso=datetime.utcnow().isoformat(),
            consecutive_sensor_triggers=streak,
        ),
    )
    _arm_anomaly_cooldown(user_id, result.event_type)
    if streak >= settings.SENSOR_STREAK_EMAIL_THRESHOLD:
        _alert_streak = 0


if __name__ == "__main__":
    sensor_agent.run()
