"""
Unit tests for app/services/anomaly_detector.py

Tests cover:
- Normal readings that should NOT trigger
- Each demo scenario (stove, faucet, fridge)
- Severity thresholds (LOW / MEDIUM / HIGH / CRITICAL)
- Edge cases (no baseline, missing user)
- Event type classification logic

No API keys or MongoDB connection needed — uses mock DB from conftest.py.
"""
import pytest
from datetime import datetime
from app.services.anomaly_detector import score_reading
from app.utils.severity import compute_severity
from app.models.sensor import SensorPayload
from test_support.constants import DEMO_USER_ID


def _make_payload(data: dict) -> SensorPayload:
    """Merge partial overrides with a full valid demo payload (all sensor fields)."""
    base = {
        "sound_level": 210,
        "temperature_c": 22.0,
        "magnetic_state": 0,
        "accel_x": 0.0,
        "accel_y": 0.0,
        "accel_z": 1.0,
        "gyro_magnitude": 5.0,
        "light_level": 512,
        "pressure": 1013.0,
        "timestamp": datetime.utcnow().isoformat(),
    }
    base.update(data)
    if "timestamp" in data and isinstance(data["timestamp"], datetime):
        base["timestamp"] = data["timestamp"].isoformat()
    return SensorPayload(**base)


# ── Normal readings ──────────────────────────────────────────────────────────

class TestNormalReadings:
    async def test_all_within_baseline_does_not_trigger(self, mock_db, normal_payload):
        payload = _make_payload(normal_payload)
        result = await score_reading(DEMO_USER_ID, payload, mock_db)
        assert result.triggered is False

    async def test_borderline_temp_does_not_trigger(self, mock_db):
        """25.7°C is just below the 25.75°C threshold (22 + 2.5×1.5)."""
        payload = _make_payload({"temperature_c": 25.7, "sound_level": 210})
        result = await score_reading(DEMO_USER_ID, payload, mock_db)
        assert result.triggered is False

    async def test_borderline_sound_does_not_trigger(self, mock_db):
        """Sound 399 is just below cutoff (|Δ| ≤ 4.0×σ → 200 + 4.0×50 = 400)."""
        payload = _make_payload({"temperature_c": 22.0, "sound_level": 399})
        result = await score_reading(DEMO_USER_ID, payload, mock_db)
        assert result.triggered is False


# ── Demo scenarios ───────────────────────────────────────────────────────────

class TestStoveScenario:
    async def test_high_temp_triggers(self, mock_db, stove_payload):
        payload = _make_payload(stove_payload)
        result = await score_reading(DEMO_USER_ID, payload, mock_db)
        assert result.triggered is True
        assert result.sensor == "temperature"

    async def test_stove_event_type(self, mock_db, stove_payload):
        payload = _make_payload(stove_payload)
        result = await score_reading(DEMO_USER_ID, payload, mock_db)
        assert result.event_type == "TEMPERATURE_ANOMALY"

    async def test_stove_deviation_score(self, mock_db, stove_payload):
        """48°C − 22°C = 26°C deviation; 26 / 1.5 = 17.33x."""
        payload = _make_payload(stove_payload)
        result = await score_reading(DEMO_USER_ID, payload, mock_db)
        assert result.deviation_score == pytest.approx(17.33, abs=0.1)

    async def test_stove_is_critical_severity(self, mock_db, stove_payload):
        payload = _make_payload(stove_payload)
        result = await score_reading(DEMO_USER_ID, payload, mock_db)
        assert result.severity == "CRITICAL"  # 17.33x >= 15 threshold


class TestFaucetScenario:
    async def test_high_sound_triggers(self, mock_db, faucet_payload):
        payload = _make_payload(faucet_payload)
        result = await score_reading(DEMO_USER_ID, payload, mock_db)
        assert result.triggered is True
        assert result.sensor == "sound"

    async def test_faucet_event_type(self, mock_db, faucet_payload):
        payload = _make_payload(faucet_payload)
        result = await score_reading(DEMO_USER_ID, payload, mock_db)
        assert result.event_type == "SOUND_ANOMALY"

    async def test_faucet_deviation_score(self, mock_db, faucet_payload):
        """420 − 200 = 220; 220 / 50 = 4.4x."""
        payload = _make_payload(faucet_payload)
        result = await score_reading(DEMO_USER_ID, payload, mock_db)
        assert result.deviation_score == pytest.approx(4.4, abs=0.1)

    async def test_faucet_is_medium_severity(self, mock_db, faucet_payload):
        """4.4x is in MEDIUM range (4–8)."""
        payload = _make_payload(faucet_payload)
        result = await score_reading(DEMO_USER_ID, payload, mock_db)
        assert result.severity == "MEDIUM"


class TestFridgeScenario:
    async def test_magnetic_open_triggers(self, mock_db, fridge_payload):
        payload = _make_payload(fridge_payload)
        result = await score_reading(DEMO_USER_ID, payload, mock_db)
        assert result.triggered is True

    async def test_fridge_event_type(self, mock_db, fridge_payload):
        payload = _make_payload(fridge_payload)
        result = await score_reading(DEMO_USER_ID, payload, mock_db)
        assert result.event_type == "DOOR_SENSOR_ANOMALY"

    async def test_closed_fridge_does_not_trigger(self, mock_db):
        payload = _make_payload({"temperature_c": 22.0, "sound_level": 210, "magnetic_state": 0})
        result = await score_reading(DEMO_USER_ID, payload, mock_db)
        assert result.triggered is False


# ── Arduino IMU edge flags (inputs.ino) ─────────────────────────────────────

class TestArduinoImuTriggers:
    async def test_motion_only_triggers_object_dropped(self, mock_db):
        """Previously required motion AND gyro; shaking often trips only one."""
        payload = _make_payload({"motion_triggered": 1, "gyro_triggered": 0})
        result = await score_reading(DEMO_USER_ID, payload, mock_db)
        assert result.triggered is True
        assert result.event_type == "OBJECT_DROPPED"
        assert result.sensor == "accelerometer"

    async def test_gyro_only_triggers_object_dropped(self, mock_db):
        payload = _make_payload({"motion_triggered": 0, "gyro_triggered": 1})
        result = await score_reading(DEMO_USER_ID, payload, mock_db)
        assert result.triggered is True
        assert result.event_type == "OBJECT_DROPPED"

    async def test_imu_takes_priority_over_sound(self, mock_db):
        """Hard IMU path runs before z-score sound."""
        payload = _make_payload(
            {"motion_triggered": 1, "sound_level": 900}
        )  # 900 would be sound anomaly vs demo baseline
        result = await score_reading(DEMO_USER_ID, payload, mock_db)
        assert result.triggered is True
        assert result.event_type == "OBJECT_DROPPED"


# ── Severity thresholds ──────────────────────────────────────────────────────

class TestSeverityThresholds:
    def test_low_severity(self):
        assert compute_severity(2.0) == "LOW"

    def test_medium_severity_lower_bound(self):
        assert compute_severity(4.0) == "MEDIUM"

    def test_medium_severity_upper_bound(self):
        assert compute_severity(7.9) == "MEDIUM"

    def test_high_severity_lower_bound(self):
        assert compute_severity(8.0) == "HIGH"

    def test_high_severity_upper_bound(self):
        assert compute_severity(14.9) == "HIGH"

    def test_critical_severity(self):
        assert compute_severity(15.0) == "CRITICAL"

    def test_extreme_score_is_critical(self):
        assert compute_severity(99.0) == "CRITICAL"


# ── Edge cases ───────────────────────────────────────────────────────────────

class TestEdgeCases:
    async def test_no_baseline_returns_not_triggered(self, mock_db_no_baseline, stove_payload):
        """When no baseline exists, should not trigger (can't score without reference)."""
        payload = _make_payload(stove_payload)
        result = await score_reading(DEMO_USER_ID, payload, mock_db_no_baseline)
        assert result.triggered is False
        assert result.reason == "no_baseline"

    async def test_temp_takes_priority_over_sound(self, mock_db):
        """Both temp and sound anomalous — temp should fire first (checked first in detector)."""
        payload = _make_payload({"temperature_c": 48.0, "sound_level": 500})
        result = await score_reading(DEMO_USER_ID, payload, mock_db)
        assert result.triggered is True
        assert result.sensor == "temperature"

    async def test_negative_temp_deviation_also_triggers(self, mock_db):
        """Temperature far below baseline (e.g. freezer door open) should also trigger."""
        payload = _make_payload({"temperature_c": -10.0, "sound_level": 210})
        result = await score_reading(DEMO_USER_ID, payload, mock_db)
        assert result.triggered is True
        assert result.sensor == "temperature"
