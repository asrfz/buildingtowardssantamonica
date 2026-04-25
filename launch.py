import os
from uagents_core.utils.registration import (
    register_chat_agent,
    RegistrationRequestCredentials,
)

BASE_URL    = "https://semioviparous-glamourously-kena.ngrok-free.dev"
AGENTVERSE_KEY = os.environ["AGENTVERSE_KEY"]
SEED_PHRASE    = os.environ["AGENT_SEED_PHRASE"]

# Each agent gets its own unique seed suffix so they derive distinct addresses.
AGENTS = [
    ("homepulse",              f"{BASE_URL}/dashboard/chat", "_dashboard"),
    ("homepulse_sensor",       BASE_URL,                     "_sensor"),
    ("homepulse_triage",       BASE_URL,                     "_triage"),
    ("homepulse_history",      BASE_URL,                     "_history"),
    ("homepulse_vision",       BASE_URL,                     "_vision"),
    ("homepulse_monitor",      BASE_URL,                     "_monitor"),
    ("homepulse_escalation",   BASE_URL,                     "_escalation"),
    ("homepulse_notification", BASE_URL,                     "_notification"),
    ("homepulse_learning",     BASE_URL,                     "_learning"),
    ("homepulse_report",       BASE_URL,                     "_report"),
    ("homepulse_heartbeat",    BASE_URL,                     "_heartbeat"),
]

for name, endpoint, suffix in AGENTS:
    credentials = RegistrationRequestCredentials(
        agentverse_api_key=AGENTVERSE_KEY,
        agent_seed_phrase=SEED_PHRASE + suffix,
    )
    try:
        register_chat_agent(name, endpoint, active=True, credentials=credentials)
        print(f"OK    {name}")
    except Exception as e:
        print(f"FAIL  {name}: {e}")
