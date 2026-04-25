from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


async def send_to_agent_dummy(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Placeholder for future agent handoff.
    Keep interface stable so real implementation can replace this later.
    """
    return {
        "status": "queued_dummy",
        "agent_name": "homepulse-agent-placeholder",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "payload_preview": {
            "arduino_file_path": payload.get("arduino_file_path"),
            "json_key_count": len(payload.get("json_keys", [])),
        },
    }
