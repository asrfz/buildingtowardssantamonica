import logging
from datetime import datetime
from uagents import Agent, Context
from uagents_core.contrib.protocols.chat import ChatMessage
from app.config import settings
from app.database import connect_db, get_db
from app.services.vision_service import capture_frame, get_zone_for_event
from app.services.cloudinary_service import upload_and_crop
from agents.agent_messages import TriageResult, VisionResult, MONITOR_AGENT_ADDRESS

logger = logging.getLogger(__name__)

vision_agent = Agent(
    name="homepulse_vision",
    seed=settings.FETCHAI_AGENT_SEED + "_vision",
)


@vision_agent.on_event("startup")
async def startup(ctx: Context) -> None:
    await connect_db()
    ctx.logger.info(f"vision_agent online — address: {vision_agent.address}")


@vision_agent.on_message(ChatMessage)
async def handle_chat(ctx: Context, sender: str, msg: ChatMessage) -> None:
    await ctx.send(sender, ChatMessage(content="HomePulse vision_agent online"))


@vision_agent.on_message(TriageResult)
async def capture_and_upload(ctx: Context, sender: str, msg: TriageResult) -> None:
    db = get_db()

    frame = await capture_frame()
    if frame is None:
        ctx.logger.warning("Webcam unavailable — sending empty VisionResult")
        await _send_empty(ctx, msg)
        return

    zone = await get_zone_for_event(msg.user_id, msg.event_type, db)
    if not zone:
        ctx.logger.warning(f"No zone mapping for {msg.event_type} — sending empty VisionResult")
        await _send_empty(ctx, msg)
        return

    try:
        urls = await upload_and_crop(frame, msg.event_id, zone)
        ctx.logger.info(f"Vision captured for event {msg.event_id} zone={zone['name']}")
    except Exception as e:
        ctx.logger.error(f"Cloudinary upload failed: {e}")
        await _send_empty(ctx, msg)
        return

    if not MONITOR_AGENT_ADDRESS:
        ctx.logger.warning("MONITOR_AGENT_ADDRESS not set")
        return

    await ctx.send(
        MONITOR_AGENT_ADDRESS,
        VisionResult(
            event_id=msg.event_id,
            user_id=msg.user_id,
            raw_url=urls["raw_url"],
            cropped_url=urls["cropped_url"],
            zone_name=zone.get("name", ""),
            timestamp_iso=datetime.utcnow().isoformat(),
        ),
    )


async def _send_empty(ctx: Context, msg: TriageResult) -> None:
    """Send a VisionResult with empty URLs so monitor_agent isn't left waiting."""
    if not MONITOR_AGENT_ADDRESS:
        return
    await ctx.send(
        MONITOR_AGENT_ADDRESS,
        VisionResult(
            event_id=msg.event_id,
            user_id=msg.user_id,
            raw_url="",
            cropped_url="",
            zone_name="",
            timestamp_iso=datetime.utcnow().isoformat(),
        ),
    )


if __name__ == "__main__":
    vision_agent.run()
