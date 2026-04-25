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
