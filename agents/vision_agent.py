"""
vision_agent — HomePulse visual confirmation and object localization agent.

Responsibilities:
  1. Receive TriageResult from triage_agent (confirmed anomaly)
  2. Capture a webcam frame (OpenCV)
  3. Detect the relevant object's position using Claude vision
     (fractional bounding box, 0.0–1.0 coordinate space)
  4. Upload the frame to Cloudinary:
       - Raw full frame stored at homepulse/raw/{event_id}
       - Cropped + encoded URL built with c_crop + fl_relative + q_auto
         (q_auto = Cloudinary context-aware encoding — picks optimal quality
          per image content so alert thumbnails are always crisp)
  5. Send VisionResult to monitor_agent (cropped URL for email alerts)
  6. Send VoiceAlert to voice_agent (object coordinates for spoken guidance)

VoiceAlert is sent when the final zone is fractional (Claude vision, or
MongoDB pixel zones normalized to 0–1 in vision_service). Cloudinary and
voice share the same coordinate space.
"""

import logging
from datetime import datetime
from uagents import Agent, Context
from uagents_core.contrib.protocols.chat import ChatMessage
from app.config import settings
from app.database import connect_db, get_db
from app.services.vision_service import capture_frame, get_zone_dynamic_or_fallback
from app.services.cloudinary_service import upload_and_crop
from agents.agent_messages import (
    TriageResult, VisionResult, VoiceAlert,
    MONITOR_AGENT_ADDRESS, VOICE_AGENT_ADDRESS,
)

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

    # Try Claude vision first (returns pct=True + fractional coords).
    # Falls back to stored MongoDB pixel zones if detection fails.
    zone = await get_zone_dynamic_or_fallback(frame, msg.user_id, msg.event_type, db)
    if not zone:
        ctx.logger.warning(f"No zone found for {msg.event_type} — sending empty VisionResult")
        await _send_empty(ctx, msg)
        return

    try:
        # Upload raw frame + generate Cloudinary cropped URL with q_auto encoding.
        # q_auto lets Cloudinary pick optimal JPEG quality per image content
        # rather than applying a fixed quality that may waste bytes on noisy frames.
        urls = await upload_and_crop(frame, msg.event_id, zone)
        ctx.logger.info(f"Vision captured for event {msg.event_id} zone={zone['name']}")
    except Exception as e:
        ctx.logger.error(f"Cloudinary upload failed: {e}")
        await _send_empty(ctx, msg)
        return

    # Send cropped image URL downstream for email alert generation
    if MONITOR_AGENT_ADDRESS:
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
    else:
        ctx.logger.warning("MONITOR_AGENT_ADDRESS not set")

    # Send object coordinates to voice_agent (fractional 0–1, pct=True).
    if VOICE_AGENT_ADDRESS and zone.get("pct"):
        await ctx.send(
            VOICE_AGENT_ADDRESS,
            VoiceAlert(
                event_id=msg.event_id,
                user_id=msg.user_id,
                event_type=msg.event_type,
                object_name=zone["name"],
                object_x=zone["x"],
                object_y=zone["y"],
                object_w=zone["w"],
                object_h=zone["h"],
                raw_url=urls["raw_url"],
                severity=msg.severity,
                timestamp_iso=datetime.utcnow().isoformat(),
            ),
        )
        ctx.logger.info(f"VoiceAlert sent for {zone['name']} at ({zone['x']:.2f}, {zone['y']:.2f})")
    elif not VOICE_AGENT_ADDRESS:
        ctx.logger.debug("VOICE_AGENT_ADDRESS not set — skipping voice alert")


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
