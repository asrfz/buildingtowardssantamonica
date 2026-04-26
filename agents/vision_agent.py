"""
vision_agent — HomePulse visual confirmation and object localization agent.

Camera ownership model:
  The browser holds the webcam via getUserMedia and shows a live feed.
  When an irregularity is confirmed, this agent asks the browser for a frame
  rather than opening the camera via OpenCV (which would conflict on Windows).

  Frame request flow:
    1. POST /voice/push  {"type":"capture","data":{"event_id":"..."}}
    2. Browser captures a frame and POSTs base64 JPEG to POST /vision/frame
    3. This agent polls GET /vision/frame/{event_id} until the frame arrives (≤10s)
    4. Claude analyzes the base64 image → zone detection
    5. Cloudinary upload + crop → VisionResult → monitor_agent
    6. VoiceAlert → voice_agent (when Claude found fractional coords)
"""

import asyncio
import logging
import time
import httpx
from datetime import datetime
from uagents import Agent, Context
from uagents_core.contrib.protocols.chat import ChatMessage
from app.config import settings
from app.database import connect_db, get_db
from app.services.vision_service import get_zone_dynamic_or_fallback_b64
from app.services.cloudinary_service import upload_and_crop_from_b64
from agents.agent_messages import (
    TriageResult, VisionResult, VoiceAlert,
    MONITOR_AGENT_ADDRESS, VOICE_AGENT_ADDRESS,
)

logger = logging.getLogger(__name__)


def _api_base() -> str:
    return settings.HOMEPULSE_API_BASE.rstrip("/")


vision_agent = Agent(
    name="homepulse_vision",
    seed=settings.FETCHAI_AGENT_SEED + "_vision",
)



async def _request_browser_frame(event_id: str, timeout: float = 10.0) -> str | None:
    """
    Ask the browser to capture a frame, then poll until it arrives.
    Returns base64 JPEG string or None on timeout.
    """
    base = _api_base()
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            await client.post(f"{base}/voice/push", json={
                "type": "capture",
                "data": {"event_id": event_id},
            })
    except Exception as e:
        logger.warning(f"[Vision] Failed to send capture request: {e}")
        return None

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        await asyncio.sleep(0.5)
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{base}/vision/frame/{event_id}")
                if resp.status_code == 200:
                    return resp.json()["image_b64"]
        except Exception:
            pass

    logger.warning(f"[Vision] Browser frame not received within {timeout}s for event {event_id}")
    return None


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

    ctx.logger.info(f"[3b/5] VISION  requesting browser frame  event={msg.event_id[:8]}")
    t0 = time.monotonic()
    image_b64 = await _request_browser_frame(msg.event_id)
    if image_b64 is None:
        ctx.logger.warning(f"[3b/5] VISION  no browser frame received — sending empty VisionResult")
        await _send_empty(ctx, msg)
        return

    elapsed = time.monotonic() - t0
    ctx.logger.info(f"[3b/5] VISION  frame received ({elapsed:.1f}s) — running Claude detection")
    zone = await get_zone_dynamic_or_fallback_b64(image_b64, msg.user_id, msg.event_type, db)
    if not zone:
        ctx.logger.warning(f"[3b/5] VISION  no zone found for {msg.event_type} — sending empty VisionResult")
        await _send_empty(ctx, msg)
        return

    ctx.logger.info(f"[3b/5] VISION  detected zone={zone['name']}  coords=({zone['x']:.2f},{zone['y']:.2f})  uploading to Cloudinary")
    try:
        urls = await upload_and_crop_from_b64(image_b64, msg.event_id, zone)
        ctx.logger.info(f"[3b/5] VISION  Cloudinary upload done  cropped={urls['cropped_url'][:60]}...")
    except Exception as e:
        ctx.logger.error(f"[3b/5] VISION  Cloudinary upload failed: {e}")
        await _send_empty(ctx, msg)
        return

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
        ctx.logger.warning("[Vision] MONITOR_AGENT_ADDRESS not set")

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


async def _send_empty(ctx: Context, msg: TriageResult) -> None:
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
