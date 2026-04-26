"""
voice_agent — HomePulse real-time voice guidance agent.

Two-phase operation:
    Phase 1 — Initial alert (event-driven):
        vision_agent  →  VoiceAlert  →  voice_agent
        Speaks a directional alert as soon as an object anomaly is confirmed.

    Phase 2 — Progressive correction loop (interval-driven, 3s per tick):
        For each active event, requests a fresh frame from the browser
        (same path as vision_agent — no OpenCV, no camera conflict), passes
        it to Claude, then speaks the spatial correction phrase.

Camera ownership:
    The browser holds the camera via getUserMedia. This agent requests frames
    via the same POST /voice/push → browser captures → POST /vision/frame →
    agent polls GET /vision/frame/{tick_id} pipeline used by vision_agent.
"""

import asyncio
import logging
import time
import httpx
from dataclasses import dataclass
from datetime import datetime

from uagents import Agent, Context
from uagents_core.contrib.protocols.chat import ChatMessage

from app.config import settings
from app.database import connect_db
from app.services.tts_service import speak, speak_async, stop_all
from app.services.spatial_service import (
    object_initial_alert,
    correction_phrase,
    object_retrieved_phrase,
    object_lost_phrase,
)
from app.services.claude_service import locate_object_and_user_in_frame
from agents.agent_messages import VoiceAlert

logger = logging.getLogger(__name__)

voice_agent = Agent(
    name="homepulse_voice",
    seed=settings.FETCHAI_AGENT_SEED + "_voice",
)

_FASTAPI_BASE = "http://localhost:8000"
MAX_TICKS = 10
NOT_FOUND_GRACE = 2


@dataclass
class CorrectionState:
    event_id: str
    user_id: str
    object_name: str
    last_object_zone: dict
    tick_count: int = 0
    not_found_ticks: int = 0


_active_corrections: dict[str, CorrectionState] = {}


async def _request_browser_frame(tick_id: str, timeout: float = 5.0) -> str | None:
    """
    Ask the browser to capture a frame for a correction tick, then poll for it.
    Uses a short 5s timeout since correction ticks fire every 3s.
    """
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            await client.post(f"{_FASTAPI_BASE}/voice/push", json={
                "type": "capture",
                "data": {"event_id": tick_id},
            })
    except Exception as e:
        logger.debug(f"[VoiceAgent] Capture request failed: {e}")
        return None

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        await asyncio.sleep(0.4)
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{_FASTAPI_BASE}/vision/frame/{tick_id}")
                if resp.status_code == 200:
                    return resp.json()["image_b64"]
        except Exception:
            pass

    logger.debug(f"[VoiceAgent] No frame received within {timeout}s for tick {tick_id}")
    return None


@voice_agent.on_event("startup")
async def startup(ctx: Context) -> None:
    await connect_db()
    ctx.logger.info(f"voice_agent online — address: {voice_agent.address}")
    speak("HomePulse voice guidance system is ready.", correction=False)


@voice_agent.on_message(VoiceAlert)
async def handle_voice_alert(ctx: Context, sender: str, msg: VoiceAlert) -> None:
    object_zone = {
        "x": msg.object_x,
        "y": msg.object_y,
        "w": msg.object_w,
        "h": msg.object_h,
        "pct": True,
    }

    alert_text = object_initial_alert(msg.object_name, object_zone)
    ctx.logger.info(f"[VoiceAlert] event={msg.event_id} object={msg.object_name} → '{alert_text}'")

    _active_corrections.pop(msg.event_id, None)
    stop_all()

    speak(alert_text, correction=False)

    _active_corrections[msg.event_id] = CorrectionState(
        event_id=msg.event_id,
        user_id=msg.user_id,
        object_name=msg.object_name,
        last_object_zone=object_zone,
    )


@voice_agent.on_message(ChatMessage)
async def handle_chat(ctx: Context, sender: str, msg: ChatMessage) -> None:
    await ctx.send(sender, ChatMessage(content="HomePulse voice_agent online"))


@voice_agent.on_interval(period=3.0)
async def correction_loop(ctx: Context) -> None:
    if not _active_corrections:
        return

    # Request one frame from the browser — shared across all active states this tick
    tick_id = f"voice_tick_{int(time.monotonic() * 1000)}"
    image_b64 = await _request_browser_frame(tick_id)
    if image_b64 is None:
        ctx.logger.debug("correction_loop: no browser frame — skipping tick")
        return

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
                ctx.logger.info(
                    f"correction_loop: {state.object_name} gone ({state.not_found_ticks} ticks) — marking retrieved"
                )
                speak(object_retrieved_phrase(state.object_name), correction=True)
                resolved.append(event_id)
            else:
                speak(object_lost_phrase(state.object_name, state.tick_count), correction=True)
            continue

        state.not_found_ticks = 0
        state.last_object_zone = {
            "x": obj["x"], "y": obj["y"],
            "w": obj["w"], "h": obj["h"],
            "pct": True,
        }

        user_zone = None
        if person.get("found"):
            user_zone = {"x": person["x"], "y": person["y"], "w": person["w"], "h": person["h"]}

        phrase = correction_phrase(state.last_object_zone, user_zone)

        if phrase is None:
            ctx.logger.info(f"correction_loop: convergence reached for event {event_id}")
            speak(object_retrieved_phrase(state.object_name), correction=True)
            resolved.append(event_id)
        else:
            ctx.logger.info(f"[Correction tick {state.tick_count}] {phrase}")
            speak(phrase, correction=True)

    for event_id in resolved:
        _active_corrections.pop(event_id, None)


if __name__ == "__main__":
    voice_agent.run()
