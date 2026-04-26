"""
HomePulse AI — End-to-End Pipeline Simulator

Runs sample sensor inputs through the full decision chain and prints
a step-by-step report of every decision made.

What this tests (without any agents or MongoDB running):
  1. Anomaly detection math against hardcoded baselines
  2. Real Claude triage call — does it say investigate or dismiss?
  3. Real Claude reasoning call — what severity + action does it recommend?
  4. Escalation logic — who gets notified, is there a cancel window?
  5. Real Claude email write — what would the email look like?

Requirements:
  - ANTHROPIC_API_KEY set in .env (or environment)
  - pip install anthropic pydantic pydantic-settings python-dotenv

Usage:
  python scripts/run_scenarios.py              # run all 3 scenarios
  python scripts/run_scenarios.py stove        # single scenario
  python scripts/run_scenarios.py stove faucet # multiple
"""
import asyncio
import sys
import os
import textwrap
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.anomaly_detector import score_reading, AnomalyResult
from app.services import claude_service
from app.utils.severity import compute_severity
from app.models.sensor import SensorPayload

# ── Hardcoded baseline (mirrors scripts/seed_demo.py) ───────────────────────
BASELINE = {
    "temperature": {"mean": 22.0, "std_dev": 1.5},
    "sound_level":  {"mean": 200,  "std_dev": 50},
    "magnetic_state": {"mean": 0,  "std_dev": 0.1},
}

DEMO_USER = {
    "_id": "000000000000000000000001",
    "name": "Margaret Chen",
    "email": "margaret@example.com",
    "emergency_contacts": [{"name": "David Chen", "email": "david@example.com"}],
    "threshold_multiplier": 2.5,
}

CANCEL_WINDOW_SECONDS = 60

# ── Scenarios ────────────────────────────────────────────────────────────────
SCENARIOS: dict[str, dict] = {
    "stove": {
        "label": "Stove Left On (3 AM)",
        "payload": {
            "sound_level": 210,
            "temperature_c": 48.0,
            "magnetic_state": 0,
            "accel_x": 0.01, "accel_y": 0.02, "accel_z": 9.80,
            "pressure": 1013.0,
        },
        "hour": 3,
        "day_type": "weekday",
        "fp_rate": 0.1,
    },
    "faucet": {
        "label": "Faucet Running (2 AM)",
        "payload": {
            "sound_level": 420,
            "temperature_c": 22.5,
            "magnetic_state": 0,
            "accel_x": 0.01, "accel_y": 0.01, "accel_z": 9.81,
            "pressure": 1013.0,
        },
        "hour": 2,
        "day_type": "weekday",
        "fp_rate": 0.15,
    },
    "fridge": {
        "label": "Fridge Left Open (1 AM)",
        "payload": {
            "sound_level": 205,
            "temperature_c": 23.0,
            "magnetic_state": 1,
            "accel_x": 0.01, "accel_y": 0.01, "accel_z": 9.81,
            "pressure": 1013.0,
        },
        "hour": 1,
        "day_type": "weekend",
        "fp_rate": 0.25,
    },
    "normal": {
        "label": "Normal Evening Reading (7 PM)",
        "payload": {
            "sound_level": 240,
            "temperature_c": 24.5,
            "magnetic_state": 0,
            "accel_x": 0.02, "accel_y": 0.01, "accel_z": 9.81,
            "pressure": 1013.0,
        },
        "hour": 19,
        "day_type": "weekday",
        "fp_rate": 0.5,
    },
    "dinner": {
        "label": "Cooking at Dinnertime (6 PM) — should be dismissed",
        "payload": {
            "sound_level": 350,
            "temperature_c": 29.0,
            "magnetic_state": 0,
            "accel_x": 0.5, "accel_y": 0.3, "accel_z": 9.7,
            "pressure": 1013.0,
        },
        "hour": 18,
        "day_type": "weekday",
        "fp_rate": 0.65,    # high FP rate at this time — Claude should be sceptical
    },
}


# ── Inline anomaly scorer (doesn't need MongoDB) ─────────────────────────────

def score_inline(payload: dict, hour: int, day_type: str) -> AnomalyResult:
    """Score a reading against hardcoded baselines without MongoDB."""
    from app.services.anomaly_detector import _classify_temp_event, _classify_sound_event

    multiplier = DEMO_USER["threshold_multiplier"]
    p = SensorPayload(**payload, timestamp=datetime.utcnow())

    # Temperature check
    temp_dev = abs(p.temperature_c - BASELINE["temperature"]["mean"])
    if temp_dev > multiplier * BASELINE["temperature"]["std_dev"]:
        score = round(temp_dev / BASELINE["temperature"]["std_dev"], 2)
        return AnomalyResult(
            triggered=True,
            event_type=_classify_temp_event(p),
            deviation_score=score,
            severity=compute_severity(score),
            sensor="temperature",
        )

    # Sound check
    sound_dev = abs(p.sound_level - BASELINE["sound_level"]["mean"])
    if sound_dev > multiplier * BASELINE["sound_level"]["std_dev"]:
        score = round(sound_dev / BASELINE["sound_level"]["std_dev"], 2)
        return AnomalyResult(
            triggered=True,
            event_type=_classify_sound_event(p),
            deviation_score=score,
            severity=compute_severity(score),
            sensor="sound",
        )

    # Magnetic check
    if p.magnetic_state == 1 and round(BASELINE["magnetic_state"]["mean"]) == 0:
        return AnomalyResult(
            triggered=True,
            event_type="FRIDGE_OPEN",
            deviation_score=4.0,
            severity="MEDIUM",
            sensor="magnetic",
        )

    return AnomalyResult(triggered=False)


# ── Printing helpers ─────────────────────────────────────────────────────────

def _hr(char="─", width=62):
    print(char * width)

def _section(n: int, title: str):
    print(f"\n  [{n}] {title}")
    print("  " + "─" * 50)

def _ok(msg):   print(f"      ✅  {msg}")
def _warn(msg): print(f"      ⚠️   {msg}")
def _info(msg): print(f"      →   {msg}")


# ── Main simulation ──────────────────────────────────────────────────────────

async def run_scenario(name: str, scenario: dict) -> None:
    _hr("═")
    print(f"  SCENARIO: {scenario['label'].upper()}")
    _hr("═")

    payload = scenario["payload"]
    hour = scenario["hour"]
    day_type = scenario["day_type"]
    fp_rate = scenario["fp_rate"]

    # ── Step 1: Sensor reading ─────────────────────────────────────────────
    _section(1, "SENSOR READING")
    _info(f"temp={payload['temperature_c']}°C  "
          f"(baseline: {BASELINE['temperature']['mean']} ± {BASELINE['temperature']['std_dev']}°C)")
    _info(f"sound={payload['sound_level']}  "
          f"(baseline: {BASELINE['sound_level']['mean']} ± {BASELINE['sound_level']['std_dev']})")
    _info(f"magnetic={payload['magnetic_state']}  time={hour}:00  day_type={day_type}")

    # ── Step 2: Anomaly detection ──────────────────────────────────────────
    _section(2, "ANOMALY DETECTION  (pure math — no LLM)")
    result = score_inline(payload, hour, day_type)

    if not result.triggered:
        _warn("NOT triggered — reading within baseline. Pipeline stops here.")
        print()
        return

    _ok(f"Triggered: {result.event_type}")
    _info(f"Deviation score: {result.deviation_score:.2f}x above baseline")
    _info(f"Sensor:    {result.sensor}")
    _info(f"Severity:  {result.severity}")

    # ── Step 3: Claude triage ──────────────────────────────────────────────
    _section(3, "TRIAGE  (Claude call #1 — noise filter)")
    _info(f"False positive rate for {result.event_type}: {fp_rate:.0%}")

    try:
        triage = await claude_service.triage_event(
            event_type=result.event_type,
            deviation_score=result.deviation_score,
            sensor_payload=payload,
            hour=hour,
            day_type=day_type,
            recent_false_positive_rate=fp_rate,
        )
    except Exception as e:
        _warn(f"Claude triage failed: {e}")
        return

    investigate = triage.get("investigate", False)
    confidence  = triage.get("confidence", 0.0)
    reason      = triage.get("reason", "")

    if investigate:
        _ok(f"investigate=True  (confidence={confidence:.2f})")
    else:
        _warn(f"investigate=False  (confidence={confidence:.2f})")
    _info(f"Claude reason: \"{reason}\"")

    if not investigate:
        print("\n  ⛔  Event DISMISSED by triage. Pipeline stops here.")
        print()
        return

    # ── Step 4: Claude full reasoning (monitor_agent in real pipeline) ────
    _section(4, "FULL REASONING  (Claude call #2 — monitor_agent)")
    _info("Simulating with empty history and no image (vision agent bypassed)")

    try:
        decision = await claude_service.reason_about_event(
            sensor_data=payload,
            deviation_score=result.deviation_score,
            image_url="",
            user_history=[],
            behavioral_schema={},
            hour=hour,
            day_type=day_type,
            triage_event_type=result.event_type,
        )
    except Exception as e:
        _warn(f"Claude reasoning failed: {e}")
        return

    confirmed_type = decision.get("confirmed_event_type", result.event_type)
    severity       = decision.get("severity", result.severity)
    action         = decision.get("recommended_action", "")
    service        = decision.get("suggested_service", "none")
    reasoning      = decision.get("reasoning", "")

    _ok(f"Confirmed event type: {confirmed_type}")
    _info(f"Severity:  {severity}")
    _info(f"Action:    {action}")
    _info(f"Service:   {service}")
    _info(f"Reasoning: {reasoning}")

    # ── Step 5: Escalation logic ───────────────────────────────────────────
    _section(5, "ESCALATION  (rule-based — no LLM)")

    if severity == "LOW":
        _warn("LOW severity — logged only, no email sent.")
        print()
        return

    recipients = [DEMO_USER["email"]]
    if severity in ("HIGH", "CRITICAL"):
        for contact in DEMO_USER.get("emergency_contacts", []):
            recipients.append(contact["email"])

    cancel_window = 0 if severity == "CRITICAL" else CANCEL_WINDOW_SECONDS

    _ok(f"Recipients:    {recipients}")
    _info(f"Cancel window: {cancel_window}s {'(none — CRITICAL)' if cancel_window == 0 else ''}")

    # ── Step 6: Claude email ───────────────────────────────────────────────
    _section(6, "EMAIL  (Claude call #3 — notification_agent)")

    try:
        email_html = await claude_service.write_alert_email(
            event_type=confirmed_type,
            severity=severity,
            recommended_action=action,
            sensor_readings=payload,
            user_name=DEMO_USER["name"],
            cancel_window_seconds=cancel_window,
            image_url="",
        )
    except Exception as e:
        _warn(f"Claude email failed: {e}")
        return

    subject = f"[HomePulse {severity}] {confirmed_type.replace('_', ' ').title()} detected"
    _ok(f"Subject: {subject}")
    _info("Email body preview (first 400 chars of HTML):")
    preview = email_html[:400].replace("\n", " ").strip()
    print()
    for line in textwrap.wrap(f"      {preview}...", width=70):
        print(line)

    print()
    _ok(f"Email would be sent to: {recipients}")
    print()


async def main() -> None:
    args = sys.argv[1:]
    to_run = args if args else ["stove", "faucet", "fridge"]

    unknown = [a for a in to_run if a not in SCENARIOS]
    if unknown:
        print(f"Unknown scenario(s): {unknown}")
        print(f"Available: {list(SCENARIOS.keys())}")
        sys.exit(1)

    print("\n" + "═" * 62)
    print("  HomePulse AI — Pipeline Simulator")
    print(f"  Running {len(to_run)} scenario(s): {to_run}")
    print("═" * 62)

    for name in to_run:
        await run_scenario(name, SCENARIOS[name])

    print("═" * 62)
    print("  Simulation complete.")
    print("═" * 62 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
