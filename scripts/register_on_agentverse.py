"""
Register all HomePulse agents on Agentverse.

Usage:
    set AGENTVERSE_KEY=your_agentverse_api_key
    set AGENT_SEED_PHRASE=your_fetchai_seed_phrase
    python scripts/register_on_agentverse.py

Get your AGENTVERSE_KEY from: https://agentverse.ai → Settings → API Keys
AGENT_SEED_PHRASE is the value of FETCHAI_AGENT_SEED in your .env file.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uagents_core.utils.registration import (
    register_chat_agent,
    RegistrationRequestCredentials,
)
from agents.agent_messages import (
    DASHBOARD_AGENT_ADDRESS,
    SENSOR_AGENT_ADDRESS,
    TRIAGE_AGENT_ADDRESS,
    HISTORY_AGENT_ADDRESS,
    VISION_AGENT_ADDRESS,
    MONITOR_AGENT_ADDRESS,
    ESCALATION_AGENT_ADDRESS,
    NOTIFICATION_AGENT_ADDRESS,
    LEARNING_AGENT_ADDRESS,
    REPORT_AGENT_ADDRESS,
    HEARTBEAT_AGENT_ADDRESS,
)

AGENTVERSE_KEY   = os.environ.get("AGENTVERSE_KEY", "")
SEED_PHRASE      = os.environ.get("AGENT_SEED_PHRASE", "")
BASE_URL         = "https://semioviparous-glamourously-kena.ngrok-free.dev"

if not AGENTVERSE_KEY or not SEED_PHRASE:
    print("ERROR: set AGENTVERSE_KEY and AGENT_SEED_PHRASE environment variables first.")
    sys.exit(1)

credentials = RegistrationRequestCredentials(
    agentverse_api_key=AGENTVERSE_KEY,
    agent_seed_phrase=SEED_PHRASE,
)

# Only the dashboard agent has an HTTP chat endpoint.
# Internal agents are registered without one (Agentverse still lists them).
AGENTS = [
    ("homepulse_dashboard",    DASHBOARD_AGENT_ADDRESS,    f"{BASE_URL}/dashboard/chat"),
    ("homepulse_sensor",       SENSOR_AGENT_ADDRESS,       None),
    ("homepulse_triage",       TRIAGE_AGENT_ADDRESS,       None),
    ("homepulse_history",      HISTORY_AGENT_ADDRESS,      None),
    ("homepulse_vision",       VISION_AGENT_ADDRESS,       None),
    ("homepulse_monitor",      MONITOR_AGENT_ADDRESS,      None),
    ("homepulse_escalation",   ESCALATION_AGENT_ADDRESS,   None),
    ("homepulse_notification", NOTIFICATION_AGENT_ADDRESS, None),
    ("homepulse_learning",     LEARNING_AGENT_ADDRESS,     None),
    ("homepulse_report",       REPORT_AGENT_ADDRESS,       None),
    ("homepulse_heartbeat",    HEARTBEAT_AGENT_ADDRESS,    None),
]

for name, address, endpoint in AGENTS:
    if not address:
        print(f"SKIP  {name} — address not set yet")
        continue

    try:
        register_chat_agent(
            address,
            endpoint or BASE_URL,
            active=True,
            credentials=credentials,
        )
        print(f"OK    {name} ({address[:20]}...)")
    except Exception as e:
        print(f"FAIL  {name}: {e}")
