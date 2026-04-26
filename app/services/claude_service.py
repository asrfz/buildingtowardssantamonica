import asyncio
import base64
import json
import re
import logging
import anthropic
import httpx
from app.config import settings

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"

# Instantiate once — reused across all calls
_client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)


def _parse_json(text: str) -> dict:
    """Strip optional markdown code fences and parse JSON."""
    text = text.strip()
    text = re.sub(r"^```json\s*", "", text)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def _normalize_llm_html_email_body(raw: str) -> str:
    """
    Claude sometimes returns markdown mixed into "HTML" emails: ```html fences, **bold**, etc.
    Gmail renders HTML only — strip artifacts so notifications look correct.
    """
    text = (raw or "").strip()
    if not text:
        return text

    fenced = re.match(
        r"^```(?:html|HTML)?\s*\r?\n?(.*)\r?\n?```\s*$",
        text,
        re.DOTALL,
    )
    if fenced:
        text = fenced.group(1).strip()
    else:
        text = re.sub(r"^```(?:html|HTML)?\s*\r?\n?", "", text, count=1)
        text = re.sub(r"\r?\n?```\s*$", "", text, count=1)
        text = text.strip()

    # Markdown **phrase** → <strong>phrase</strong>
    text = re.sub(r"\*\*([^*\n]+?)\*\*", r"<strong>\1</strong>", text)
    # Stray lines that are only a fence
    text = re.sub(r"^\s*```(?:html|HTML)?\s*$", "", text, flags=re.MULTILINE)
    return text.strip()


# ── Triage ──────────────────────────────────────────────────────────────────

def _triage_event_sync(
    event_type: str,
    deviation_score: float,
    sensor_payload: dict,
    hour: int,
    day_type: str,
    recent_false_positive_rate: float,
) -> dict:
    prompt = f"""You are HomePulse, a household safety AI for elderly users.

A sensor anomaly was detected. Decide if this is worth investigating.

Event type: {event_type}
Deviation score: {deviation_score:.1f}x above baseline
Sensor readings: {sensor_payload}
Time: {hour}:00, {day_type}
Recent false positive rate for this event type: {recent_false_positive_rate:.0%}

Respond with JSON only:
{{"investigate": true, "confidence": 0.0, "reason": "one sentence"}}"""

    response = _client.messages.create(
        model=MODEL,
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_json(response.content[0].text)


async def triage_event(
    event_type: str,
    deviation_score: float,
    sensor_payload: dict,
    hour: int,
    day_type: str,
    recent_false_positive_rate: float,
) -> dict:
    return await asyncio.to_thread(
        _triage_event_sync,
        event_type,
        deviation_score,
        sensor_payload,
        hour,
        day_type,
        recent_false_positive_rate,
    )


# ── Full event reasoning (Milestone 2 — monitor_agent) ──────────────────────

_MEDIA_ALLOW = {"image/jpeg", "image/png", "image/gif", "image/webp"}


def _reason_about_event_sync(
    sensor_data: dict,
    deviation_score: float,
    image_url: str,
    user_history: dict,
    behavioral_schema: dict,
    hour: int,
    day_type: str,
    image_b64: str | None = None,
    image_media_type: str = "image/jpeg",
    triage_event_type: str = "",
    crop_spatially_trusted: bool = True,
) -> dict:
    has_image = bool(image_b64 and image_media_type in _MEDIA_ALLOW)
    locked_type = (triage_event_type or "").strip() or "UNCONFIRMED_SENSOR_EVENT"

    crop_warning = ""
    if has_image and not crop_spatially_trusted:
        crop_warning = """
**Image caveat:** This crop is aligned to a stored room map, not proof that a specific object (sink, stove, fridge, etc.) caused the alert or appears as labeled. Only describe objects or layouts you can actually see. For sound-like alerts, suggest ordinary explanations when appropriate (TV, music, speaker, phone, another person, pet, HVAC, outside noise) without insisting on a particular source you cannot verify.
"""

    if has_image:
        prompt = f"""You are HomePulse, a household safety AI for elderly users.

Analyze this household anomaly and determine the appropriate response.
You can see the cropped alert image attached.
{crop_warning}
Sensor data: {sensor_data}
Deviation: {deviation_score:.1f}x above baseline
Time: {hour}:00 {day_type}
User's recent event history: {user_history}
User behavioral schema: {behavioral_schema}

Respond with JSON only:
{{
  "confirmed_event_type": "STOVE_LEFT_ON|FRIDGE_OPEN|FAUCET_RUNNING|WATER_DRIPPING|IRON_LEFT_ON|APPLIANCE_FAULT|FIRE_RISK|FALL_DETECTED|MULTIVARIATE_ANOMALY|SOUND_ANOMALY|TEMPERATURE_ANOMALY|DOOR_SENSOR_ANOMALY|LIGHT_STATE_CHANGED|OBJECT_DROPPED|UNCONFIRMED_SENSOR_EVENT",
  "severity": "LOW|MEDIUM|HIGH|CRITICAL",
  "recommended_action": "one sentence for the user",
  "suggested_service": "plumber|fire_department|appliance_repair|emergency_services|none",
  "reasoning": "two sentences max"
}}"""
    else:
        prompt = f"""You are HomePulse, a household safety AI for elderly users.

**No camera image is available for this alert.** Do not use past incidents, behavioral history, or patterns from other days — that context has been withheld on purpose.

You must **keep the same coarse classification as triage** (sensor-only). Do not rename it to a specific appliance (e.g. do not output FRIDGE_OPEN, STOVE_LEFT_ON, or FAUCET_RUNNING) unless you have a verified image.

Triage classification (use this exact string for confirmed_event_type): {locked_type}

Sensor data: {sensor_data}
Deviation: {deviation_score:.1f}x above baseline
Time: {hour}:00 {day_type}

Write ONE short recommended_action that matches locked_type:
- If locked_type is DOOR_SENSOR_ANOMALY: ask them to check doors, windows, and entryways — do NOT talk about unexplained noise or sound levels unless the sensor data clearly shows sound.
- If locked_type is SOUND_ANOMALY: ask them to listen and check the area where noise was unusual — do NOT blame doors unless sensor data shows door/magnetic.
- If locked_type is TEMPERATURE_ANOMALY: focus on heat/cold and safe checks.
Otherwise stay aligned with locked_type. Do not use generic "walk through your home for any sound" when the alert is door- or motion-class.

Respond with JSON only:
{{
  "confirmed_event_type": "{locked_type}",
  "severity": "LOW|MEDIUM|HIGH|CRITICAL",
  "recommended_action": "one sentence for the user",
  "suggested_service": "plumber|fire_department|appliance_repair|emergency_services|none",
  "reasoning": "two sentences max — cite only current sensor readings"
}}"""

    if image_b64 and image_media_type in _MEDIA_ALLOW:
        user_content: list[dict] | str = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": image_media_type,
                    "data": image_b64,
                },
            },
            {"type": "text", "text": prompt},
        ]
    else:
        user_content = prompt

    response = _client.messages.create(
        model=MODEL,
        max_tokens=400,
        messages=[{"role": "user", "content": user_content}],
    )
    decision = _parse_json(response.content[0].text)
    if not has_image:
        decision["confirmed_event_type"] = locked_type
    return decision


async def _fetch_monitor_image(
    image_url: str,
) -> tuple[str | None, str]:
    """Return (base64, media_type) for Cloudinary/HTTPS image URLs; no auth needed for public URLs."""
    if not image_url or not image_url.strip():
        return None, "image/jpeg"
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            r = await client.get(image_url)
            r.raise_for_status()
            raw = (r.headers.get("content-type") or "image/jpeg").split(";")[0].strip()
            if raw not in _MEDIA_ALLOW:
                raw = "image/jpeg"
            return base64.b64encode(r.content).decode("utf-8"), raw
    except Exception as e:
        logger.warning("Monitor: could not fetch image for multimodal reasoning: %s", e)
        return None, "image/jpeg"


async def reason_about_event(
    sensor_data: dict,
    deviation_score: float,
    image_url: str,
    user_history: dict,
    behavioral_schema: dict,
    hour: int,
    day_type: str,
    triage_event_type: str = "",
    crop_spatially_trusted: bool = True,
) -> dict:
    b64, media = await _fetch_monitor_image(image_url)
    return await asyncio.to_thread(
        _reason_about_event_sync,
        sensor_data,
        deviation_score,
        image_url,
        user_history,
        behavioral_schema,
        hour,
        day_type,
        b64,
        media,
        triage_event_type,
        crop_spatially_trusted,
    )


# ── Alert email ──────────────────────────────────────────────────────────────

def _write_alert_email_sync(
    event_type: str,
    severity: str,
    recommended_action: str,
    sensor_readings: dict,
    image_url: str,
    user_name: str,
    cancel_window_seconds: int,
) -> str:
    prompt = f"""Write a warm, clear HTML email alert for {user_name}, an elderly user.

Event: {event_type.replace("_", " ").title()}
Severity: {severity}
Recommended action: {recommended_action}
Sensor readings: {sensor_readings}
Image URL: {image_url if image_url else "N/A"}
Cancel window: {cancel_window_seconds} seconds

Requirements:
- Warm, simple language — no technical jargon
- Large readable text suggestions in the HTML
- Include the cropped image if image URL is provided
- Include severity badge (red for HIGH/CRITICAL, orange for MEDIUM, yellow for LOW)
- Include cancel option if not CRITICAL
- Keep it concise — elderly users should understand it at a glance
- Return only the HTML body fragment: no outer <html>, <body>, or <!DOCTYPE>
- Valid HTML only: use tags like <div>, <p>, <strong>, <span>, <img> with inline styles
- Do NOT wrap the answer in markdown code fences (no ``` or ```html)
- Do NOT use markdown emphasis (no ** or __); use <strong>...</strong> instead"""

    response = _client.messages.create(
        model=MODEL,
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text
    normalized = _normalize_llm_html_email_body(raw)
    if normalized != (raw or "").strip():
        logger.info("Alert email: normalized LLM output (markdown fences or ** removed)")
    return normalized


async def write_alert_email(
    event_type: str,
    severity: str,
    recommended_action: str,
    sensor_readings: dict,
    user_name: str,
    cancel_window_seconds: int,
    image_url: str = "",
) -> str:
    return await asyncio.to_thread(
        _write_alert_email_sync,
        event_type,
        severity,
        recommended_action,
        sensor_readings,
        image_url,
        user_name,
        cancel_window_seconds,
    )


# ── Weekly digest ────────────────────────────────────────────────────────────

def _write_weekly_digest_sync(
    events: list,
    user_name: str,
    caregiver_name: str | None = None,
) -> str:
    prompt = f"""Write a warm, readable weekly home safety digest for {user_name}.
{"This is being sent to caregiver: " + caregiver_name if caregiver_name else ""}

Events this week: {events}

Requirements:
- Plain, friendly language
- Summarize what happened (find patterns, don't list every event)
- Highlight any recurring issues
- Give 1-2 gentle actionable recommendations
- End on a reassuring note
- Return only HTML body fragment (no <html>/<body> wrapper)
- No markdown fences or **bold** — use <strong> and real HTML tags only"""

    response = _client.messages.create(
        model=MODEL,
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text
    return _normalize_llm_html_email_body(raw)


async def write_weekly_digest(
    events: list,
    user_name: str,
    caregiver_name: str | None = None,
) -> str:
    return await asyncio.to_thread(
        _write_weekly_digest_sync, events, user_name, caregiver_name
    )


# ── ASI:One dashboard query ──────────────────────────────────────────────────

def compact_user_profile_for_prompt(user: dict | None) -> dict:
    """Subset of the users collection document safe to pass into the dashboard prompt."""
    if not user:
        return {}
    contacts = user.get("emergency_contacts") or []
    simplified: list[dict] = []
    if isinstance(contacts, list):
        for c in contacts:
            if isinstance(c, dict):
                simplified.append({
                    "name": c.get("name", ""),
                    "relationship": c.get("relationship", ""),
                    "email": c.get("email", ""),
                    "phone": c.get("phone", ""),
                })
    return {
        "name": user.get("name", ""),
        "email": user.get("email", ""),
        "emergency_contacts": simplified,
        "threshold_multiplier": user.get("threshold_multiplier"),
    }


def _answer_dashboard_query_sync(
    user_query: str,
    system_online: bool,
    last_seen_ago: str,
    user_name: str,
    events_summary: list,
    threshold_info: dict,
    user_profile: dict,
) -> str:
    profile_block = (
        user_profile
        if user_profile
        else "No profile details on file."
    )
    prompt = f"""You are HomePulse, a smart home safety assistant.
The user may be on voice (wake word + spoken question) or text chat. Replies will often be read aloud — optimize for listening.

=== SYSTEM STATUS ===
Sensor system online: {system_online}
Last sensor heartbeat: {last_seen_ago}
Primary resident / monitoring context: {user_name}

=== USER PROFILE (account) ===
{profile_block}

=== EVENTS / ALERTS (last 7 days, newest first — these are incidents the system logged) ===
{events_summary if events_summary else "No events recorded in the last 7 days."}

=== BEHAVIORAL SCHEMA (per-event statistics) ===
{threshold_info if threshold_info else "No behavioral data yet."}

=== USER QUESTION ===
{user_query}

How to answer:
- Default to SHORT answers: one to three sentences. No long unsolicited recaps.
- If the USER QUESTION is casual (greeting, filler, "I'm here", small talk) and does NOT ask about home, monitoring, profile, or incidents: reply in ONE short sentence offering help. Do NOT mention EVENTS, sensor activity, "this morning", or past alerts at all.
- Give a fuller summary (up to about six sentences) only when the user clearly asks what happened, for a recap, status overview, "this morning", "tell me everything", or similar.
- NEVER volunteer phrases like "Would you like a quick rundown?", "want me to go through", or similar unless they explicitly asked for a summary, rundown, or details.
- Questions about "my profile", "my account", "who is on file", emergency contacts, or their email: use USER PROFILE. If a field is missing or empty, say so briefly.
- Questions about past incidents, alerts, or "what went wrong": use EVENTS. Mention severity or time when helpful. Do not dump every event unless they ask for a full list.
- For "how many" or "list my incidents", you may briefly enumerate the most relevant few from EVENTS.

Style: plain, warm, conversational. No markdown headers or bullet lists.

Rules on sensor / heartbeat wording:
- ONLY mention sensors offline or heartbeat if they ask whether monitoring is working right now, live status, or "is the system up".
- For history-only questions, do not lead with sensor status.
- If CRITICAL or HIGH severity events are relevant, mention them."""

    response = _client.messages.create(
        model=MODEL,
        max_tokens=450,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


async def answer_dashboard_query(
    user_query: str,
    system_online: bool,
    last_seen_ago: str,
    user_name: str,
    events_summary: list,
    threshold_info: dict,
    user_profile: dict | None = None,
) -> str:
    return await asyncio.to_thread(
        _answer_dashboard_query_sync,
        user_query,
        system_online,
        last_seen_ago,
        user_name,
        events_summary,
        threshold_info,
        user_profile or {},
    )


# ── Vision: dynamic object detection ────────────────────────────────────────

# Objects Claude will look for in frame
_SENSOR_HINTS: dict[str, str] = {
    "TEMPERATURE_ANOMALY":  "The temperature sensor fired — prioritize heat sources: stove burners, irons, ovens, candles, fire, smoke.",
    "SOUND_ANOMALY":        "The sound sensor fired — prioritize: running water, dripping taps, falling objects, breaking glass, alarms.",
    "DOOR_SENSOR_ANOMALY":  "A magnetic door sensor fired — prioritize open doors, fridge doors, cabinet doors, windows.",
    "OBJECT_DROPPED":       "A drop/impact was detected — prioritize fallen objects, spilled liquids, a person who may have fallen.",
    "MULTIVARIATE_ANOMALY": "Multiple sensors fired simultaneously — identify the most visually prominent safety concern.",
    "FALL_DETECTED":        "A fall was detected — prioritize people on the floor or in unusual positions.",
    "FIRE_RISK":            "Fire risk detected — prioritize flames, smoke, or glowing burners.",
}

_DETECT_PROMPT_TEMPLATE = """You are the visual inspection system for a home safety AI.

A sensor event was triggered. Context: {sensor_hint}

Examine this image and locate any object or situation that could explain the alert.
Do not limit yourself to a fixed list — identify whatever is actually visible and relevant.
Examples of what you might find: a stove burner left on, a water bottle knocked over, a running faucet,
an open fridge door, a fallen person, a burning candle, a leaking pipe, a dropped phone, fire, smoke, etc.

For each relevant object or situation, return its bounding box as a FRACTION of the image (0.0 to 1.0):
- x: left edge, y: top edge, w: width, h: height

Order results by safety relevance (most important first).

Respond with JSON only, no explanation:
{{
  "objects": [
    {{"name": "stove burner on", "x": 0.1, "y": 0.4, "w": 0.3, "h": 0.25}},
    {{"name": "water bottle on floor", "x": 0.6, "y": 0.7, "w": 0.1, "h": 0.15}}
  ]
}}

If nothing relevant is visible, return: {{"objects": []}}"""


def _detect_objects_sync(image_b64: str, event_type: str = "") -> list[dict]:
    hint = _SENSOR_HINTS.get(event_type, "A sensor anomaly was detected — identify any safety-relevant object or situation.")
    prompt = _DETECT_PROMPT_TEMPLATE.format(sensor_hint=hint)
    response = _client.messages.create(
        model=MODEL,
        max_tokens=500,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": image_b64,
                    },
                },
                {"type": "text", "text": prompt},
            ],
        }],
    )
    result = _parse_json(response.content[0].text)
    return result.get("objects", [])


async def detect_objects_in_frame(image_b64: str, event_type: str = "") -> list[dict]:
    """Use Claude vision to detect safety-relevant objects; event_type guides what to prioritize."""
    return await asyncio.to_thread(_detect_objects_sync, image_b64, event_type)


_UNVERIFIED_SCENE_PROMPT = """You are HomePulse, a calm in-home safety voice assistant.

The sensors reported: {event_type}
We did **not** get a reliable match between that alert and a specific object in this frame (the image may be a wide shot or the cause may be off-camera).

Look at what is **actually visible**. Write 2–3 short sentences for text-to-speech:
- Only mention people, screens, speakers, pets, windows, or appliances if you can **clearly** see them.
- Offer **plausible, everyday** explanations when helpful: TV or music, phone or laptop audio, smart speaker, another person talking, pet, fan or HVAC, traffic or neighbors outside, something in another room, etc.
- Do **not** say a sink, stove, fridge, or other object is "in front of them" unless it is **clearly** visible.
- Do **not** invent details not supported by the image.
- No bullet points, no JSON, no quotation marks around the whole message."""


def _describe_unverified_alert_scene_sync(image_b64: str, event_type: str) -> str:
    prompt = _UNVERIFIED_SCENE_PROMPT.format(event_type=event_type or "SENSOR_EVENT")
    response = _client.messages.create(
        model=MODEL,
        max_tokens=220,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": image_b64,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    )
    return (response.content[0].text or "").strip()


async def describe_unverified_alert_scene(image_b64: str, event_type: str) -> str | None:
    """
    When vision could not label a real object for the alert (calibration fallback),
    produce grounded spoken guidance from the frame — not fake directional object claims.
    """
    if not image_b64 or not image_b64.strip():
        return None
    try:
        text = await asyncio.to_thread(_describe_unverified_alert_scene_sync, image_b64, event_type)
        return text or None
    except Exception as e:
        logger.warning("describe_unverified_alert_scene failed: %s", e)
        return None


# ── Voice correction: locate object + person in frame ────────────────────────

_LOCATE_PROMPT = """You are a spatial awareness system for a home safety assistant.

Analyze this image and find:
1. The {object_name} — give its bounding box
2. Any person visible anywhere in the frame — give their bounding box

Bounding box values are fractions of the image (0.0 = left/top edge, 1.0 = right/bottom edge):
  x = left edge, y = top edge, w = width, h = height

Respond with JSON only — no explanation:
{{
  "object": {{"found": true, "x": 0.1, "y": 0.4, "w": 0.15, "h": 0.12}},
  "person": {{"found": false}}
}}

If something is not visible set found to false and omit x/y/w/h."""


def _locate_object_and_user_sync(image_b64: str, object_name: str) -> dict:
    prompt = _LOCATE_PROMPT.format(object_name=object_name)
    response = _client.messages.create(
        model=MODEL,
        max_tokens=250,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": image_b64,
                    },
                },
                {"type": "text", "text": prompt},
            ],
        }],
    )
    return _parse_json(response.content[0].text)


async def locate_object_and_user_in_frame(image_b64: str, object_name: str) -> dict:
    """
    Detect where a specific object and any person are in a webcam frame.

    Returns fractional bounding boxes (0.0–1.0) for use by spatial_service
    to compute directional corrections for the voice agent.

    Called every correction tick (every ~3 s) — uses base64 directly so
    frames are NOT uploaded to Cloudinary (no cost/latency for guidance ticks).
    """
    return await asyncio.to_thread(_locate_object_and_user_sync, image_b64, object_name)
