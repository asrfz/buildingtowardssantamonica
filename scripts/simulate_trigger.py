# -*- coding: utf-8 -*-
"""
Inject a simulated hot sensor reading to trigger the full agent pipeline.
Use this when you don't have Arduino hardware connected.

Requires the FastAPI server to be running:
    uvicorn app.main:app --reload

Then in another terminal:
    python scripts/simulate_trigger.py [scenario]

Scenarios: stove (default), faucet, fridge
"""
import sys
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone

BASE_URL = "http://127.0.0.1:8000"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


SCENARIOS = {
    "stove": {
        "sound_level": 210,
        "temperature_c": 48.0,
        "magnetic_state": 0,
        "accel_x": 0.01,
        "accel_y": 0.02,
        "accel_z": 9.80,
        "pressure": 1013.0,
        "timestamp": None,  # filled at runtime
    },
    "faucet": {
        "sound_level": 420,
        "temperature_c": 22.5,
        "magnetic_state": 0,
        "accel_x": 0.01,
        "accel_y": 0.01,
        "accel_z": 9.81,
        "pressure": 1013.0,
        "timestamp": None,
    },
    "fridge": {
        "sound_level": 205,
        "temperature_c": 23.0,
        "magnetic_state": 1,
        "accel_x": 0.01,
        "accel_y": 0.01,
        "accel_z": 9.81,
        "pressure": 1013.0,
        "timestamp": None,
    },
}


def post(path: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def main() -> None:
    scenario = sys.argv[1] if len(sys.argv) > 1 else "stove"
    if scenario not in SCENARIOS:
        print(f"Unknown scenario '{scenario}'. Choose: {', '.join(SCENARIOS)}")
        sys.exit(1)

    payload = {**SCENARIOS[scenario], "timestamp": now_iso()}

    print(f"\nInjecting '{scenario}' scenario:")
    print(f"  temp={payload['temperature_c']}C  sound={payload['sound_level']}  mag={payload['magnetic_state']}")

    try:
        result = post("/sensor/simulate", payload)
        print(f"\n[OK] {result['status']} - {result['message']}")
        print("Watch FastAPI logs for the pipeline. Check inbox for alert email (~30s).")
    except urllib.error.URLError as e:
        print(f"\n[ERROR] Could not reach server: {e}")
        print("Make sure FastAPI is running:  uvicorn app.main:app --reload")


if __name__ == "__main__":
    main()
