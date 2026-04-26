"""
vision_agent — HomePulse visual confirmation and object localization agent.

Camera ownership:
  OpenCV capture runs in the FastAPI process (GET /sensor/live-frame-b64).
  The bureau agents call the API so only one process opens the webcam on Windows.

  Frame flow:
    1. GET /sensor/live-frame-b64 → base64 JPEG
    2. Claude analyzes the image → zone detection
    3. Cloudinary upload + crop → VisionResult → monitor_agent
    4. VoiceAlert → voice_agent (when Claude found fractional coords)
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
from app.services.claude_service import describe_unverified_alert_scene
from app.services.cloudinary_service import upload_and_crop_from_b64
from app.services.camera_snapshot_service import (
    crop_zone_document,
    find_snapshot_for_event,
    record_camera_snapshot,
)
from app.services.snapshot_cloudinary_gate import refund_upload_slot, try_consume_upload_slot
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



async def _request_backend_frame(event_id: str) -> str | None:
    """Fetch one OpenCV frame from the API (same webcam the dev console preview uses)."""
    base = _api_base()
    # Fail fast: long per-attempt timeouts stacked with preview-jpeg contention felt ~30s+.
    timeout = httpx.Timeout(6.0, connect=2.0)
    max_attempts = 5
    last_err: str | None = None
    for attempt in range(max_attempts):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(f"{base}/sensor/live-frame-b64")
                if resp.status_code != 200:
                    last_err = f"HTTP {resp.status_code}"
                    logger.warning(
                        "[Vision] live-frame-b64 %s event=%s attempt %s/%s",
                        last_err,
                        event_id[:8],
                        attempt + 1,
                        max_attempts,
                    )
                else:
                    data = resp.json()
                    b64 = data.get("image_b64")
                    if isinstance(b64, str) and b64.strip():
                        if attempt > 0:
                            logger.info(
                                "[Vision] live-frame-b64 ok after retry event=%s",
                                event_id[:8],
                            )
                        return b64
                    last_err = "empty image_b64"
        except Exception as e:
            last_err = str(e) or repr(e)
            logger.warning(
                "[Vision] live-frame-b64 error event=%s attempt %s/%s: %s",
                event_id[:8],
                attempt + 1,
                max_attempts,
                last_err,
            )
        if attempt < max_attempts - 1:
            await asyncio.sleep(0.35)
    if last_err:
        logger.warning(
            "[Vision] live-frame-b64 gave up event=%s: %s",
            event_id[:8],
            last_err,
        )
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

    ctx.logger.info(f"[3b/5] VISION  requesting API webcam frame  event={msg.event_id[:8]}")
    t0 = time.monotonic()
    image_b64 = await _request_backend_frame(msg.event_id)
    if image_b64 is None:
        ctx.logger.warning(f"[3b/5] VISION  no API frame — sending empty VisionResult")
        await _send_empty(ctx, msg)
        return

    elapsed = time.monotonic() - t0
    ctx.logger.info(f"[3b/5] VISION  frame received ({elapsed:.1f}s) — running Claude detection")
    zone = await get_zone_dynamic_or_fallback_b64(image_b64, msg.user_id, msg.event_type, db)
    if not zone:
        ctx.logger.warning(f"[3b/5] VISION  no zone found for {msg.event_type} — sending empty VisionResult")
        await _send_empty(ctx, msg)
        return

    spatial_trusted = zone.get("visual_verified") is True
    ctx.logger.info(
        "[3b/5] VISION  zone=%s spatial_trusted=%s coords=(%.2f,%.2f)",
        zone.get("name"),
        spatial_trusted,
        zone.get("x", 0),
        zone.get("y", 0),
    )

    context_msg = ""
    if not spatial_trusted:
        try:
            context_msg = (await describe_unverified_alert_scene(image_b64, msg.event_type)) or ""
        except Exception as e:
            ctx.logger.warning("[3b/5] VISION  unverified scene context failed: %s", e)

    may_upload = await try_consume_upload_slot(db, msg.user_id)
    if not may_upload:
        existing = await find_snapshot_for_event(db, user_id=msg.user_id, event_id=msg.event_id)
        if existing and (existing.get("url") or existing.get("cropped_url")):
            ctx.logger.info(
                "[3b/5] VISION  no upload slot — reusing stored snapshot for event=%s",
                msg.event_id[:8],
            )
            await _dispatch_vision_results(
                ctx,
                msg,
                zone,
                raw_url=existing.get("url") or "",
                cropped_url=existing.get("cropped_url") or "",
                cropped_thumb_url=existing.get("cropped_thumb_url") or "",
                initial_context_message=context_msg,
            )
        else:
            ctx.logger.info(
                "[3b/5] VISION  no upload slot and no prior snapshot — empty VisionResult event=%s",
                msg.event_id[:8],
            )
            await _send_empty(ctx, msg)
        return

    ctx.logger.info("[3b/5] VISION  upload slot acquired — uploading to Cloudinary")
    try:
        urls = await upload_and_crop_from_b64(
            image_b64,
            msg.event_id,
            zone,
            user_id=msg.user_id,
            event_type=msg.event_type,
        )
        ctx.logger.info(f"[3b/5] VISION  Cloudinary upload done  cropped={urls['cropped_url'][:60]}...")
    except Exception as e:
        ctx.logger.error(f"[3b/5] VISION  Cloudinary upload failed: {e}")
        await refund_upload_slot(db, msg.user_id)
        await _send_empty(ctx, msg)
        return

    try:
        sid = await record_camera_snapshot(
            db,
            user_id=msg.user_id,
            url=urls["raw_url"],
            cropped_url=urls.get("cropped_url") or "",
            cropped_thumb_url=urls.get("cropped_thumb_url") or "",
            public_id=str(urls.get("public_id") or f"homepulse/raw/{msg.event_id}"),
            width=urls.get("width"),
            height=urls.get("height"),
            source="vision",
            event_id=msg.event_id,
            event_type=msg.event_type,
            vision_crop_zone=crop_zone_document(zone),
        )
        if sid:
            ctx.logger.info(f"[3b/5] VISION  snapshot row in Mongo camera_snapshots id={sid[:8]}…")
    except Exception as e:
        ctx.logger.warning(f"[3b/5] VISION  camera_snapshots insert failed: {e}")

    await _dispatch_vision_results(
        ctx,
        msg,
        zone,
        raw_url=urls["raw_url"],
        cropped_url=urls["cropped_url"],
        cropped_thumb_url=urls.get("cropped_thumb_url") or "",
        initial_context_message=context_msg,
    )


async def _dispatch_vision_results(
    ctx: Context,
    msg: TriageResult,
    zone: dict,
    *,
    raw_url: str,
    cropped_url: str,
    cropped_thumb_url: str = "",
    initial_context_message: str = "",
) -> None:
    if MONITOR_AGENT_ADDRESS:
        await ctx.send(
            MONITOR_AGENT_ADDRESS,
            VisionResult(
                event_id=msg.event_id,
                user_id=msg.user_id,
                raw_url=raw_url,
                cropped_url=cropped_url,
                cropped_thumb_url=cropped_thumb_url or "",
                zone_name=zone.get("name", ""),
                timestamp_iso=datetime.utcnow().isoformat(),
                spatial_crop_trusted=zone.get("visual_verified") is True,
                crop_x=float(zone.get("x", 0)),
                crop_y=float(zone.get("y", 0)),
                crop_w=float(zone.get("w", 0)),
                crop_h=float(zone.get("h", 0)),
                crop_fractional=bool(zone.get("pct")),
            ),
        )
    else:
        ctx.logger.warning("[Vision] MONITOR_AGENT_ADDRESS not set")

    if VOICE_AGENT_ADDRESS and zone.get("pct"):
        trusted = zone.get("visual_verified") is True
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
                raw_url=raw_url,
                severity=msg.severity,
                timestamp_iso=datetime.utcnow().isoformat(),
                spatial_guidance_trusted=trusted,
                initial_context_message=(initial_context_message or "").strip() if not trusted else "",
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
            cropped_thumb_url="",
            zone_name="",
            timestamp_iso=datetime.utcnow().isoformat(),
            crop_x=0.0,
            crop_y=0.0,
            crop_w=0.0,
            crop_h=0.0,
            crop_fractional=True,
        ),
    )


if __name__ == "__main__":
    vision_agent.run()
