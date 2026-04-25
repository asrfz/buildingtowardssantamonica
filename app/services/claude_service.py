import asyncio
import json
import re
import logging
import anthropic
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

def _reason_about_event_sync(
    sensor_data: dict,
    deviation_score: float,
    image_url: str,
    user_history: dict,
    behavioral_schema: dict,
    hour: int,
    day_type: str,
) -> dict:
    prompt = f"""You are HomePulse, a household safety AI for elderly users.

Analyze this household anomaly and determine the appropriate response.

Sensor data: {sensor_data}
Deviation: {deviation_score:.1f}x above baseline
Time: {hour}:00 {day_type}
Cropped image URL: {image_url}
User's recent event history: {user_history}
User behavioral schema: {behavioral_schema}

Respond with JSON only:
{{
  "confirmed_event_type": "STOVE_LEFT_ON|FRIDGE_OPEN|FAUCET_RUNNING|WATER_DRIPPING|IRON_LEFT_ON|APPLIANCE_FAULT|FIRE_RISK|FALL_DETECTED",
  "severity": "LOW|MEDIUM|HIGH|CRITICAL",
  "recommended_action": "one sentence for the user",
  "suggested_service": "plumber|fire_department|appliance_repair|emergency_services|none",
  "reasoning": "two sentences max"
}}"""

    response = _client.messages.create(
        model=MODEL,
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_json(response.content[0].text)


async def reason_about_event(
    sensor_data: dict,
    deviation_score: float,
    image_url: str,
    user_history: dict,
    behavioral_schema: dict,
    hour: int,
    day_type: str,
) -> dict:
    return await asyncio.to_thread(
        _reason_about_event_sync,
        sensor_data,
        deviation_score,
        image_url,
        user_history,
        behavioral_schema,
        hour,
        day_type,
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
- Return only the HTML body content, no <html> or <body> tags"""

    response = _client.messages.create(
        model=MODEL,
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


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
- Return only HTML body content"""

    response = _client.messages.create(
        model=MODEL,
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


async def write_weekly_digest(
    events: list,
    user_name: str,
    caregiver_name: str | None = None,
) -> str:
    return await asyncio.to_thread(
        _write_weekly_digest_sync, events, user_name, caregiver_name
    )


# ── ASI:One dashboard query ──────────────────────────────────────────────────

def _answer_dashboard_query_sync(
    user_query: str,
    system_online: bool,
    last_seen_ago: str,
    user_name: str,
    events_summary: list,
    threshold_info: dict,
) -> str:
    prompt = f"""You are HomePulse, a smart home safety assistant for elderly users.
A caregiver or family member is asking you a question via ASI:One chat.

=== SYSTEM STATUS ===
Sensor system online: {system_online}
Last sensor heartbeat: {last_seen_ago}
Monitoring: {user_name}

=== EVENTS (last 7 days, newest first) ===
{events_summary if events_summary else "No events recorded in the last 7 days."}

=== BEHAVIORAL SCHEMA (per-event statistics) ===
{threshold_info if threshold_info else "No behavioral data yet."}

=== USER QUESTION ===
{user_query}

Answer in plain, warm, conversational language — as if you are a caring home safety assistant.
No markdown headers or bullet lists. Max 4 sentences. Be specific: use the event data above.

Rules on when to mention sensor status:
- ONLY mention the sensor being offline if the user is asking about current/live status, real-time monitoring, or whether the system is working RIGHT NOW.
- For questions about past events, weekly summaries, history, or specific incidents — do NOT mention the sensor status at all. Just answer the question from the event data.
- If there are CRITICAL or HIGH severity events relevant to the question, highlight those."""

    response = _client.messages.create(
        model=MODEL,
        max_tokens=300,
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
) -> str:
    return await asyncio.to_thread(
        _answer_dashboard_query_sync,
        user_query,
        system_online,
        last_seen_ago,
        user_name,
        events_summary,
        threshold_info,
    )


# ── Vision: dynamic object detection ────────────────────────────────────────

# Objects Claude will look for in frame
_DETECTABLE_OBJECTS = ["stove", "sink", "fridge", "oven", "microwave", "iron", "kettle", "toaster"]

_DETECT_PROMPT = """You are a household object detector for a home safety system.
Analyze this image and identify the bounding boxes of all visible household appliances.

Look for: stove, sink, fridge, oven, microwave, iron, kettle, toaster, water faucet.

For each object found, return its bounding box as a FRACTION of the image (0.0 to 1.0):
- x: left edge (fraction of image width)
- y: top edge (fraction of image height)
- w: width (fraction of image width)
- h: height (fraction of image height)

Respond with JSON only, no explanation:
{
  "objects": [
    {"name": "stove", "x": 0.1, "y": 0.4, "w": 0.3, "h": 0.25},
    {"name": "sink", "x": 0.6, "y": 0.3, "w": 0.2, "h": 0.2}
  ]
}

If no relevant objects are visible, return: {"objects": []}"""


def _detect_objects_sync(image_b64: str) -> list[dict]:
    response = _client.messages.create(
        model=MODEL,
        max_tokens=400,
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
                {"type": "text", "text": _DETECT_PROMPT},
            ],
        }],
    )
    result = _parse_json(response.content[0].text)
    return result.get("objects", [])


async def detect_objects_in_frame(image_b64: str) -> list[dict]:
    """Use Claude vision to detect household objects and return bounding boxes as fractions (0-1)."""
    return await asyncio.to_thread(_detect_objects_sync, image_b64)
