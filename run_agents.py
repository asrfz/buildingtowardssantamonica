"""
Start all HomePulse agents in a single process using uAgents Bureau.

Usage:
    python run_agents.py

Keep FastAPI running separately:
    uvicorn app.main:app --reload --port 8000
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

if __name__ == "__main__":
    print("Starting all HomePulse agents...")
    bureau.run()
