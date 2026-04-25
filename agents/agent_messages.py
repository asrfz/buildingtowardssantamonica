from uagents import Model
from typing import Optional

# ── Agent addresses ──────────────────────────────────────────────────────────
# Run `python scripts/register_agents.py` to print these, then paste them here.
SENSOR_AGENT_ADDRESS        = ""
TRIAGE_AGENT_ADDRESS        = ""
HISTORY_AGENT_ADDRESS       = ""
VISION_AGENT_ADDRESS        = ""
MONITOR_AGENT_ADDRESS       = ""
ESCALATION_AGENT_ADDRESS    = ""
NOTIFICATION_AGENT_ADDRESS  = ""
LEARNING_AGENT_ADDRESS      = ""
REPORT_AGENT_ADDRESS        = ""
HEARTBEAT_AGENT_ADDRESS     = ""


# ── Message types ────────────────────────────────────────────────────────────
# NOTE: uAgents Model uses Pydantic v1. Avoid datetime fields — use ISO strings.
# Nested Pydantic models are not reliable; use dict for structured data.

class IrregularityEvent(Model):
    """sensor_agent → triage_agent"""
    user_id: str
    event_type: str
    severity: str
    deviation_score: float
    sensor_payload: dict
    timestamp_iso: str          # ISO 8601 string, e.g. "2025-04-25T14:32:00"


class TriageResult(Model):
    """triage_agent → history_agent + vision_agent (Milestone 2)"""
    user_id: str
    event_id: str               # MongoDB ObjectId as str
    event_type: str
    severity: str
    deviation_score: float
    sensor_payload: dict
    confidence: float
    triage_reason: str
    investigate: bool
    timestamp_iso: str


class UserHistoryContext(Model):
    """history_agent → monitor_agent (Milestone 2)"""
    event_id: str
    user_id: str
    sensor_payload: dict
    deviation_score: float
    recent_events: list
    behavioral_schema: dict
    timestamp_iso: str


class VisionResult(Model):
    """vision_agent → monitor_agent (Milestone 2)"""
    event_id: str
    user_id: str
    raw_url: str
    cropped_url: str
    zone_name: str
    timestamp_iso: str


class MonitorDecision(Model):
    """monitor_agent → escalation_agent (Milestone 2)"""
    event_id: str
    user_id: str
    confirmed_event_type: str
    severity: str
    recommended_action: str
    suggested_service: str
    image_url: str
    timestamp_iso: str


class EscalationOrder(Model):
    """escalation_agent → notification_agent"""
    event_id: str
    user_id: str
    recipients: list
    severity: str
    recommended_action: str
    cancel_window_seconds: int
    event_type: str
    sensor_payload: dict
    image_url: str


class HeartbeatStatus(Model):
    """heartbeat_agent → escalation_agent"""
    agent_name: str
    status: str                 # "online" | "offline"
    silence_seconds: float
    timestamp_iso: str
