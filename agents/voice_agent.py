"""
voice_agent — HomePulse real-time voice guidance agent.

Two-phase operation:
    Phase 1 — Initial alert (event-driven):
        vision_agent  →  VoiceAlert  →  voice_agent
        Speaks a directional alert as soon as an object anomaly is confirmed.

    Phase 2 — Progressive correction loop (interval-driven, 3s per tick):
        For each active event, requests a fresh frame from GET /sensor/live-frame-b64
        (OpenCV in the API process), passes it to Claude, then speaks the correction phrase.

Camera ownership:
    Same as vision_agent — webcam via FastAPI only.
"""

import asyncio
import logging
import httpx
from dataclasses import dataclass
from datetime import datetime

from bson import ObjectId
from uagents import Agent, Context
from uagents_core.contrib.protocols.chat import ChatMessage

from app.config import settings
from app.database import connect_db, get_db
from app.services.gmail_service import send_voice_guidance_escalation_sync
from app.services.tts_service import speak, speak_async, stop_all
from app.services.spatial_service import (
    object_initial_alert,
    correction_phrase,
    object_retrieved_phrase,
    object_lost_phrase,
    unverified_alert_voice_fallback,
)
from app.services.claude_service import locate_object_and_user_in_frame
from agents.agent_messages import VoiceAlert

logger = logging.getLogger(__name__)


def _api_base() -> str:
    return settings.HOMEPULSE_API_BASE.rstrip("/")


voice_agent = Agent(
    name="homepulse_voice",
    seed=settings.FETCHAI_AGENT_SEED + "_voice",
)

MAX_TICKS = 10
NOT_FOUND_GRACE = 2
# Same spoken guidance this many times in a row → email emergency contact ("more than 3" → 4th hit)
VOICE_SAME_PHRASE_ESCALATE_STREAK = 4


@dataclass
class CorrectionState:
    event_id: str
    user_id: str
    object_name: str
    last_object_zone: dict
    tick_count: int = 0
    not_found_ticks: int = 0
    # Same spoken guidance 3 ticks in a row → email emergency contact
    last_spoken_norm: str | None = None
    same_phrase_streak: int = 0


_active_corrections: dict[str, CorrectionState] = {}


def _streak_should_escalate(state: CorrectionState, phrase: str) -> bool:
    norm = phrase.strip().lower()
    if not norm:
        return False
    if state.last_spoken_norm == norm:
        state.same_phrase_streak += 1
    else:
        state.last_spoken_norm = norm
        state.same_phrase_streak = 1
    return state.same_phrase_streak >= VOICE_SAME_PHRASE_ESCALATE_STREAK


def _reset_speech_streak(state: CorrectionState) -> None:
    state.last_spoken_norm = None
    state.same_phrase_streak = 0


async def _emergency_recipients(user_id: str) -> list[str]:
    if settings.EMERGENCY_NOTIFY_EMAIL.strip():
        return [settings.EMERGENCY_NOTIFY_EMAIL.strip()]
    try:
        db = get_db()
        user = await db.users.find_one({"_id": ObjectId(user_id)})
    except Exception:
        return []
    if not user:
        return []
    out: list[str] = []
    for c in user.get("emergency_contacts") or []:
        em = (c or {}).get("email")
        if em:
            out.append(em)
    if not out and user.get("email"):
        out.append(user["email"])
    return out


async def _escalate_repeated_phrase(ctx: Context, state: CorrectionState, phrase: str) -> None:
    recipients = await _emergency_recipients(state.user_id)
    if not recipients:
        ctx.logger.warning(
            "[VoiceAgent] Same guidance repeated 3x but no EMERGENCY_NOTIFY_EMAIL "
            "or emergency_contacts — cannot send email"
        )
        speak(
            "I need to reach someone but no emergency email is configured. Please check settings.",
            correction=True,
        )
        return
    loop = asyncio.get_running_loop()
    ok = await loop.run_in_executor(
        None,
        lambda: send_voice_guidance_escalation_sync(
            recipients,
            event_id=state.event_id,
            object_name=state.object_name,
            repeated_phrase=phrase[:500],
            user_id=state.user_id,
        ),
    )
    if ok:
        ctx.logger.info(
            "[VoiceAgent] Escalation email sent after repeated guidance → %s",
            recipients,
        )
        speak(
            "I've emailed your emergency contact to check in. Please stay safe.",
            correction=True,
        )
    else:
        speak(
            "I tried to notify your emergency contact but email did not send. Please ask someone for help.",
            correction=True,
        )


async def _request_live_frame(timeout: float = 5.0) -> str | None:
    """One OpenCV frame from the API (shared with vision_agent)."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{_api_base()}/sensor/live-frame-b64")
            if resp.status_code != 200:
                return None
            b64 = resp.json().get("image_b64")
            if isinstance(b64, str) and b64.strip():
                return b64
    except Exception as e:
        logger.debug(f"[VoiceAgent] live-frame-b64 failed: {e}")
    return None


@voice_agent.on_event("startup")
async def startup(ctx: Context) -> None:
    await connect_db()
    ctx.logger.info(f"voice_agent online — address: {voice_agent.address}")
    speak("HomePulse voice guidance system is ready.", correction=False)


@voice_agent.on_message(VoiceAlert)
async def handle_voice_alert(ctx: Context, sender: str, msg: VoiceAlert) -> None:
    trusted = getattr(msg, "spatial_guidance_trusted", True)
    if not trusted:
        phrase = (getattr(msg, "initial_context_message", None) or "").strip()
        if not phrase:
            phrase = unverified_alert_voice_fallback(msg.event_type)
        ctx.logger.info(
            "[VoiceAlert] event=%s unverified scene — context guidance (no spatial loop)",
            msg.event_id,
        )
        _active_corrections.pop(msg.event_id, None)
        stop_all()
        speak(phrase, correction=False)
        return

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

    image_b64 = await _request_live_frame()
    if image_b64 is None:
        ctx.logger.debug("correction_loop: no API frame — skipping tick")
        return

    resolved: list[str] = []

    for event_id, state in list(_active_corrections.items()):
        state.tick_count += 1

        if state.tick_count > MAX_TICKS:
            ctx.logger.info(f"correction_loop: timeout for event {event_id}")
            _reset_speech_streak(state)
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
                _reset_speech_streak(state)
                speak(object_retrieved_phrase(state.object_name), correction=True)
                resolved.append(event_id)
            else:
                lost_phrase = object_lost_phrase(state.object_name, state.tick_count)
                if _streak_should_escalate(state, lost_phrase):
                    await _escalate_repeated_phrase(ctx, state, lost_phrase)
                    resolved.append(event_id)
                else:
                    speak(lost_phrase, correction=True)
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
            _reset_speech_streak(state)
            speak(object_retrieved_phrase(state.object_name), correction=True)
            resolved.append(event_id)
        else:
            ctx.logger.info(f"[Correction tick {state.tick_count}] {phrase}")
            if _streak_should_escalate(state, phrase):
                await _escalate_repeated_phrase(ctx, state, phrase)
                resolved.append(event_id)
            else:
                speak(phrase, correction=True)

    for event_id in resolved:
        _active_corrections.pop(event_id, None)


if __name__ == "__main__":
    voice_agent.run()
