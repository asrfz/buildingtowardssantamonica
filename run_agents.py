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
        → escalation_agent → notification_agent (Claude email + Gmail)
    voice_agent: ElevenLabs TTS + OpenCV tick frames → base64 → Claude locate + spatial_service

    heartbeat_agent  — monitors sensor_agent liveness
    learning_agent   — 24-hour behavioral schema refresh
    report_agent     — 7-day weekly digest email
    dashboard_agent  — ASI:One chat gateway (Agentverse mailbox)
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from uagents import Bureau

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

bureau = Bureau(port=8002)

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
bureau.add(dashboard_agent)
bureau.add(voice_agent)
bureau.add(voice_input_agent)

if __name__ == "__main__":
    print("Starting all HomePulse agents (including voice_agent)...")
    bureau.run()
