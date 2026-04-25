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
import os
import json
import urllib.request
import urllib.error
from datetime import datetime

BASE_URL = "http://127.0.0.1:8000"

SCENARIOS = {
    "stove": {
        "sound_level": 210,
        "temperature_c": 48.0,    # well above 22 + 2.5*1.5 = 25.75°C baseline
        "magnetic_state": 0,
        "accel_x": 0.01,
        "accel_y": 0.02,
        "accel_z": 9.80,
        "pressure": 1013.0,
        "timestamp": datetime.utcnow().isoformat(),
    },
    "faucet": {
        "sound_level": 420,       # 300–500 range → FAUCET_RUNNING, above 200+2.5*50=325
        "temperature_c": 22.5,
        "magnetic_state": 0,
        "accel_x": 0.01,
        "accel_y": 0.01,
        "accel_z": 9.81,
        "pressure": 1013.0,
        "timestamp": datetime.utcnow().isoformat(),
    },
    "fridge": {
        "sound_level": 205,
        "temperature_c": 23.0,
        "magnetic_state": 1,      # door open → FRIDGE_OPEN
        "accel_x": 0.01,
        "accel_y": 0.01,
        "accel_z": 9.81,
        "pressure": 1013.0,
        "timestamp": datetime.utcnow().isoformat(),
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

    payload = SCENARIOS[scenario]
    print(f"\nInjecting '{scenario}' scenario:")
    print(f"  temp={payload['temperature_c']}°C  sound={payload['sound_level']}  mag={payload['magnetic_state']}")

    try:
        result = post("/sensor/simulate", payload)
        print(f"\n✅ Server response: {result['status']} — {result['message']}")
        print("\nWatch the agent terminal windows for the pipeline firing.")
        print("Check your inbox for the alert email (may take ~30 seconds).")
    except urllib.error.URLError as e:
        print(f"\n❌ Could not reach server: {e}")
        print("Make sure FastAPI is running:  uvicorn app.main:app --reload")


if __name__ == "__main__":
    main()
