"""
HomePulse Agent Bureau — starts all agents in a single process.

Usage:
    python run_agents.py

Keep FastAPI running separately:
    uvicorn app.main:app --reload --port 8000

Agent pipeline overview:
    sensor_agent
        → triage_agent (Claude: should we investigate?)
            → [parallel] history_agent  →  monitor_agent
            → [parallel] vision_agent   →  monitor_agent (VisionResult: Cloudinary raw + cropped URLs)
                                      ↘  voice_agent (VoiceAlert only when Claude zones are fractional)
    monitor_agent (Claude: reason with image URL + history)
        → escalation_agent (defers email if not already sent) → user says "send help…" via voice_input_agent
        → notification_agent (Claude email + Gmail)
    triage_agent: after 3 consecutive sensor anomaly ticks (see SENSOR_STREAK_EMAIL_THRESHOLD), announces + emails
        emergency contacts immediately (no voice ack required); escalation_agent skips duplicate deferral if notified.
    voice_agent: ElevenLabs TTS + OpenCV tick frames → base64 → Claude locate + spatial_service

    heartbeat_agent  — monitors sensor_agent liveness
    learning_agent   — 24-hour behavioral schema refresh
    report_agent     — 7-day weekly digest email
    dashboard_agent  — voice / chat queries (local bureau by default; set HOMEPULSE_DASHBOARD_MAILBOX for ASI:One only)
"""
import logging
import sys
import os
import socket
from typing import Optional, Tuple
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-5s  %(message)s",
    datefmt="%H:%M:%S",
)
# Suppress noisy third-party HTTP logs
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("uagents").setLevel(logging.WARNING)
logging.getLogger("fetchai").setLevel(logging.WARNING)

from app.config import settings


def _port_bind_probe(port: int) -> Tuple[bool, Optional[int]]:
    """Return (ok, errno) — True if 0.0.0.0:port can be bound now."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("0.0.0.0", port))
        return True, None
    except OSError as e:
        return False, e.errno
    finally:
        s.close()


def _resolve_bureau_port() -> int:
    preferred = int(settings.UAGENTS_BUREAU_PORT)
    candidates = [preferred] + [p for p in range(8002, 8012) if p != preferred]
    for p in candidates:
        ok, errno = _port_bind_probe(p)
        if ok:
            if p != preferred:
                logging.getLogger("run_agents").warning(
                    "Preferred uAgents port %s is in use; using %s instead "
                    "(free the old process or set UAGENTS_BUREAU_PORT)",
                    preferred,
                    p,
                )
            return p
    logging.getLogger("run_agents").error(
        "Could not probe a free bureau port in range; falling back to %s", preferred
    )
    return preferred


_BUREAU_PORT = _resolve_bureau_port()
print(f"[run_agents] uAgents Bureau HTTP port: {_BUREAU_PORT} (set UAGENTS_BUREAU_PORT in .env to override)")

from uagents import Bureau

from agents.noop_registration import AlmanacRegistrationSkipped
from agents.sensor_agent       import sensor_agent
from agents.triage_agent       import triage_agent
from agents.history_agent      import history_agent
from agents.vision_agent       import vision_agent
from agents.monitor_agent      import monitor_agent
from agents.escalation_agent   import escalation_agent
from agents.notification_agent import notification_agent
from agents.learning_agent     import learning_agent
from agents.report_agent       import report_agent
from agents.heartbeat_agent    import heartbeat_agent
from agents.dashboard_agent    import dashboard_agent
from agents.voice_agent        import voice_agent
from agents.voice_input_agent  import voice_input_agent

_bureau_kw: dict = {"port": _BUREAU_PORT}
if settings.UAGENTS_SKIP_ALMANAC_REGISTRATION:
    _bureau_kw["registration_policy"] = AlmanacRegistrationSkipped()
    logging.getLogger("run_agents").info(
        "Almanac batch registration skipped (UAGENTS_SKIP_ALMANAC_REGISTRATION). "
        "Set to false in .env if you need Agentverse registry updates from this bureau."
    )
bureau = Bureau(**_bureau_kw)

bureau.add(sensor_agent)
bureau.add(triage_agent)
bureau.add(history_agent)
bureau.add(vision_agent)
bureau.add(monitor_agent)
bureau.add(escalation_agent)
bureau.add(notification_agent)
bureau.add(learning_agent)
bureau.add(report_agent)
bureau.add(heartbeat_agent)
# Agentverse/ledger lookups can intermittently 502; keep core safety pipeline up.
try:
    bureau.add(dashboard_agent)
except Exception:
    logging.getLogger("run_agents").exception(
        "dashboard_agent not added (network/ledger issue); continuing without dashboard"
    )
bureau.add(voice_agent)
bureau.add(voice_input_agent)

if __name__ == "__main__":
    print("Starting all HomePulse agents (including voice_agent)...")
    bureau.run()
