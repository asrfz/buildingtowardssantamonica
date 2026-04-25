"""
voice_agent — HomePulse real-time voice guidance agent.

Role in the FetchAI agent network:
    Sits at the end of the vision pipeline and bridges detected object coordinates
    into spoken audio output. FetchAI's uAgents framework acts as orchestrator:
    it handles all message routing and the on_interval correction ticker without
    any external scheduler or polling logic.

Two-phase operation:
    Phase 1 — Initial alert (event-driven):
        vision_agent  →  VoiceAlert  →  voice_agent
        Speaks a directional alert as soon as an object anomaly is confirmed
        and its position in the frame is known.

    Phase 2 — Progressive correction loop (interval-driven, 3 s per tick):
        voice_agent  →  [capture frame]  →  Claude vision  →  spatial_service
        Continuously guides the user toward the object until:
          a) The object disappears from frame (assumed retrieved), or
          b) The user's bounding box converges on the object's, or
          c) MAX_TICKS correction ticks elapse (~30 s safety timeout)

Cloudinary usage in this agent:
    Initial alert image — already uploaded by vision_agent with q_auto encoding.
    Correction ticks    — frames go directly to Claude as base64 (no Cloudinary
                          upload) because transient guidance frames don't need
                          storage or distribution; only the first alert image does.

FetchAI role:
    - on_message(VoiceAlert) : event-driven entry point from vision_agent
    - on_interval(3 s)       : drives the correction loop state machine
    - Module-level dict      : holds CorrectionState per active event_id;
                               FetchAI's async context ensures safe concurrent access

To get this agent's address (needed for VOICE_AGENT_ADDRESS in agent_messages.py):
    python -c "from agents.voice_agent import voice_agent; print(voice_agent.address)"
"""

import logging
import sys
import os
from dataclasses import dataclass, field
from datetime import datetime

from uagents import Agent, Context
from uagents_core.contrib.protocols.chat import ChatMessage

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings
from app.database import connect_db
from app.services.tts_service import speak, speak_async, stop_all
from app.services.spatial_service import (
    object_initial_alert,
    correction_phrase,
    object_retrieved_phrase,
    object_lost_phrase,
)
from app.services.vision_service import capture_frame
from app.services.claude_service import locate_object_and_user_in_frame
from app.services.cloudinary_service import frame_to_base64
from agents.agent_messages import VoiceAlert

logger = logging.getLogger(__name__)

voice_agent = Agent(
    name="homepulse_voice",
    seed=settings.FETCHAI_AGENT_SEED + "_voice",
)

# ── Correction loop state ────────────────────────────────────────────────────
# Keyed by event_id. Each entry lives until the object is retrieved or timeout.

MAX_TICKS = 10          # 10 × 3 s = 30 s maximum active guidance window
NOT_FOUND_GRACE = 2     # consecutive "object not found" ticks before declaring retrieved


@dataclass
class CorrectionState:
    event_id: str
    user_id: str
    object_name: str
    last_object_zone: dict          # most recent fractional bbox {x, y, w, h}
    tick_count: int = 0
    not_found_ticks: int = 0       # consecutive frames where object was missing


_active_corrections: dict[str, CorrectionState] = {}


# ── Startup ───────────────────────────────────────────────────────────────────

@voice_agent.on_event("startup")
async def startup(ctx: Context) -> None:
    await connect_db()
    ctx.logger.info(f"voice_agent online — address: {voice_agent.address}")
    speak("HomePulse voice guidance system is ready.", correction=False)


# ── Handle initial voice alert from vision_agent ──────────────────────────────

@voice_agent.on_message(VoiceAlert)
async def handle_voice_alert(ctx: Context, sender: str, msg: VoiceAlert) -> None:
    """
    Triggered by vision_agent once it has:
      1. Confirmed the event via Claude triage
      2. Detected the object's position with Claude vision
      3. Uploaded the alert image to Cloudinary with q_auto encoding

    The fractional bounding box in VoiceAlert matches the Cloudinary fl_relative
    coordinates used in the cropped alert image — same coordinate space.
    """
    object_zone = {
        "x": msg.object_x,
        "y": msg.object_y,
        "w": msg.object_w,
        "h": msg.object_h,
        "pct": True,
    }

    alert_text = object_initial_alert(msg.object_name, object_zone)
    ctx.logger.info(f"[VoiceAlert] event={msg.event_id} object={msg.object_name} → '{alert_text}'")

    # Cancel any queued correction speech before speaking the new alert
    # so it doesn't get buried behind old phrases in the queue
    _active_corrections.pop(msg.event_id, None)
    stop_all()

    # Initial alert uses eleven_turbo_v2_5 (higher quality, warm delivery)
    speak(alert_text, correction=False)

    _active_corrections[msg.event_id] = CorrectionState(
        event_id=msg.event_id,
        user_id=msg.user_id,
        object_name=msg.object_name,
        last_object_zone=object_zone,
    )


# ── ASI:One / chat passthrough ────────────────────────────────────────────────

@voice_agent.on_message(ChatMessage)
async def handle_chat(ctx: Context, sender: str, msg: ChatMessage) -> None:
    await ctx.send(sender, ChatMessage(content="HomePulse voice_agent online"))


# ── Progressive correction loop (every 3 s) ───────────────────────────────────

@voice_agent.on_interval(period=3.0)
async def correction_loop(ctx: Context) -> None:
    """
    Runs every 3 seconds while there are active correction states.

    For each active event:
      1. Capture a fresh webcam frame (OpenCV)
      2. Send it to Claude vision as base64 — NO Cloudinary upload for ticks
         (only the initial alert image is stored in Cloudinary)
      3. Ask Claude to locate the object AND any person in the frame
      4. Use spatial_service to compute a correction phrase
      5. Speak the correction via tts_service
      6. Clear state when done (retrieved / converged / timeout)
    """
    if not _active_corrections:
        return

    frame = await capture_frame()
    if frame is None:
        ctx.logger.warning("correction_loop: webcam unavailable — skipping tick")
        return

    # Encode once; reuse for all active states in this tick
    image_b64 = frame_to_base64(frame)

    resolved: list[str] = []

    for event_id, state in list(_active_corrections.items()):
        state.tick_count += 1

        if state.tick_count > MAX_TICKS:
            ctx.logger.info(f"correction_loop: timeout for event {event_id}")
            speak("I've lost track of the situation. Please check your surroundings carefully.", correction=True)
            resolved.append(event_id)
            continue

        try:
            positions = await locate_object_and_user_in_frame(image_b64, state.object_name)
        except Exception as exc:
            ctx.logger.warning(f"correction_loop: Claude detection error: {exc}")
            continue

        obj = positions.get("object", {})
        person = positions.get("person", {})

        if not obj.get("found"):
            state.not_found_ticks += 1
            if state.not_found_ticks >= NOT_FOUND_GRACE:
                # Object gone from frame for 2+ consecutive ticks → retrieved
                ctx.logger.info(
                    f"correction_loop: {state.object_name} gone ({state.not_found_ticks} ticks) "
                    f"for event {event_id} — marking retrieved"
                )
                speak(object_retrieved_phrase(state.object_name), correction=True)
                resolved.append(event_id)
            else:
                speak(object_lost_phrase(state.object_name, state.tick_count), correction=True)
            continue

        # Object still visible — reset not-found counter and update position
        state.not_found_ticks = 0
        state.last_object_zone = {
            "x": obj["x"], "y": obj["y"],
            "w": obj["w"], "h": obj["h"],
            "pct": True,
        }

        user_zone = None
        if person.get("found"):
            user_zone = {
                "x": person["x"], "y": person["y"],
                "w": person["w"], "h": person["h"],
            }

        phrase = correction_phrase(state.last_object_zone, user_zone)

        if phrase is None:
            # spatial_service determined user has converged on the object
            ctx.logger.info(f"correction_loop: convergence reached for event {event_id}")
            speak(object_retrieved_phrase(state.object_name), correction=True)
            resolved.append(event_id)
        else:
            ctx.logger.info(f"[Correction tick {state.tick_count}] {phrase}")
            speak(phrase, correction=True)   # eleven_flash_v2_5 — ultra-low latency

    for event_id in resolved:
        _active_corrections.pop(event_id, None)


if __name__ == "__main__":
    voice_agent.run()
