"""
Print deterministic agent addresses for all HomePulse agents.

Run once after setting FETCHAI_AGENT_SEED in .env, then paste the output
into agents/agent_messages.py as the address constants.

Usage:
    python scripts/register_agents.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uagents import Agent
from app.config import settings

AGENTS = [
    ("dashboard",     "_dashboard"),   # user-facing ASI:One gateway — register this first
    ("sensor",        "_sensor"),
    ("triage",        "_triage"),
    ("history",       "_history"),
    ("vision",        "_vision"),
    ("monitor",       "_monitor"),
    ("escalation",    "_escalation"),
    ("notification",  "_notification"),
    ("learning",      "_learning"),
    ("report",        "_report"),
    ("heartbeat",     "_heartbeat"),
]

print("\n# Paste these into agents/agent_messages.py\n")
for name, suffix in AGENTS:
    a = Agent(name=f"homepulse_{name}", seed=settings.FETCHAI_AGENT_SEED + suffix)
    const_name = f"{name.upper()}_AGENT_ADDRESS"
    print(f'{const_name:<30} = "{a.address}"')
print()
print("# Register homepulse_dashboard on Agentverse first — it's the ASI:One entry point.")
