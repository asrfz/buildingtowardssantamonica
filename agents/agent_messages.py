from uagents import Model
from typing import Optional

# ── Agent addresses ──────────────────────────────────────────────────────────
# Run `python scripts/register_agents.py` to print these, then paste them here.
# DASHBOARD_AGENT_ADDRESS: required for voice_input → dashboard (VoiceQuery). Empty = voice queries won't route.
# VOICE_INPUT_AGENT_ADDRESS: dashboard replies here (VoiceQueryResponse); can fall back to sender if wrong.
DASHBOARD_AGENT_ADDRESS     = "agent1qgcj7n4c3mtzk6smmgenl0mtgdxuxeway08kyn9zm0x0t7lduhe3kpcz3wd"
SENSOR_AGENT_ADDRESS        = "agent1qthfw9s49lm0vajvk4cpxpws35qmqz8d0g3zf9gqx3dw267gtpdvure95fr"
TRIAGE_AGENT_ADDRESS        = "agent1q0syk8pz50n9782exz46r0uwls9c2vlmkf7m09k3zhngal6zw4pgqwrjqef"
HISTORY_AGENT_ADDRESS       = "agent1qglju8pw38fa8l48353jwdgf84rd8rfee30rg7seqwqwfpwefvrmk9fj4c7"
VISION_AGENT_ADDRESS        = "agent1qwj8lct6dq9nrc97ajsn0yp6qkq3y8ca8ntcps2e3pjv6wyay6hf7vgvcuy"
MONITOR_AGENT_ADDRESS       = "agent1qtl5yptjsv883x23lkt6f73m6888z0npcm2leesc32glxtf2mmzxxazeupq"
ESCALATION_AGENT_ADDRESS    = "agent1q23jna0hlra5lrk8pyaf6sryksnrllrvx0mrefyhtl2p793ssd9wq4yv8ds"
NOTIFICATION_AGENT_ADDRESS  = "agent1qv7awy8whgjc0de3aylfzr2t0y0flh4d54h7yee0lu4fejpj2qyzxgdhkne"
LEARNING_AGENT_ADDRESS      = "agent1qwqyq0k9t9nk37lt7g4q2qsd8lzv7lju9k2lwzrhl9g5gpzuugckc0kzunc"
REPORT_AGENT_ADDRESS        = "agent1q2hlgw75yl6l49mx7u7pqej6sdu3jam2lykr7u48dftg2exfzvn2g79ztpv"
HEARTBEAT_AGENT_ADDRESS     = "agent1qtdma26fxnnfftn6zcntvkv42fah7r8zlz6lh64ns5my4vxzam5gg6anf4x"
VOICE_AGENT_ADDRESS         = "agent1q0c73gpcpwdjg96fnp8nnlzr2ta4t96czskfg7y9msfr49ukc5g2yjtw0kk"
VOICE_INPUT_AGENT_ADDRESS   = "agent1qwn686mp4zv87lves0rfc6wunufz7mze0ugsgzg4m5cd96m4jp22cfhrdg5"


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
    sensor_payload: dict  # same readings as triage; needed for email + audit


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


class VoiceQuery(Model):
    """
    voice_input_agent -> dashboard_agent

    Carries a spoken query captured via ElevenLabs Scribe STT after a wake word
    is detected. dashboard_agent processes it identically to an ASI:One chat
    message and sends back a VoiceQueryResponse.
    """
    query_id: str       # UUID -- used to correlate response
    user_id: str
    transcript: str     # question text (wake word already stripped)
    timestamp_iso: str


class VoiceQueryResponse(Model):
    """
    dashboard_agent -> voice_input_agent

    Contains the Claude-generated answer to a VoiceQuery. voice_input_agent
    pushes both transcript and answer to the FastAPI WebSocket so the visual
    overlay updates in real-time for the deaf user.
    """
    query_id: str
    answer: str
    transcript: str     # echoed back for display pairing
    timestamp_iso: str


class VoiceAlert(Model):
    """
    vision_agent → voice_agent

    Carries the object's fractional bounding box (0.0–1.0, from Claude vision
    detection) so voice_agent can immediately speak a directional alert and
    start the progressive correction loop without re-running detection.

    Fractional coords come from Claude vision; they match Cloudinary's fl_relative
    coordinate system used in the cropped alert image URL.
    """
    event_id: str
    user_id: str
    event_type: str
    object_name: str    # human-readable: "stove", "iron", "water bottle"
    object_x: float     # left edge as fraction of frame width  (0.0–1.0)
    object_y: float     # top  edge as fraction of frame height (0.0–1.0)
    object_w: float     # width  as fraction of frame width
    object_h: float     # height as fraction of frame height
    raw_url: str        # full-frame Cloudinary URL (for audit trail)
    severity: str
    timestamp_iso: str
