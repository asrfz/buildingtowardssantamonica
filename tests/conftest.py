"""
Shared pytest fixtures for HomePulse AI tests.

All fixtures use an in-memory mock DB — no real MongoDB connection needed.
Sensor payloads cover all 3 demo scenarios plus edge cases.
"""
import pytest
import pytest_asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from bson import ObjectId
from test_support.constants import (
    BEHAVIORAL_SCHEMA_DOC,
    BASELINE,
    DEMO_EVENT_ID,
    DEMO_USER_DOC,
    DEMO_USER_ID,
)


# ── Sample sensor payloads ───────────────────────────────────────────────────

def _payload(**kwargs) -> dict:
    base = {
        "sound_level": 210,
        "temperature_c": 22.0,
        "magnetic_state": 0,
        "accel_x": 0.01,
        "accel_y": 0.02,
        "accel_z": 9.80,
        "pressure": 1013.0,
        "timestamp": datetime.utcnow().isoformat(),
    }
    base.update(kwargs)
    return base


@pytest.fixture
def normal_payload() -> dict:
    """Reading completely within all baselines — should not trigger."""
    return _payload(temperature_c=22.0, sound_level=210)


@pytest.fixture
def stove_payload() -> dict:
    """48°C — 17.3x above temperature baseline → STOVE_LEFT_ON. Low |a| = still / left-on."""
    return _payload(
        temperature_c=48.0,
        accel_x=0.0,
        accel_y=0.0,
        accel_z=0.2,  # |a| < 0.5 → not FIRE_RISK in _classify_temp_event
    )


@pytest.fixture
def faucet_payload() -> dict:
    """Sound 420 — 4.4x above sound baseline → FAUCET_RUNNING."""
    return _payload(sound_level=420, temperature_c=22.2)


@pytest.fixture
def fridge_payload() -> dict:
    """Magnetic state 1 (door open) → FRIDGE_OPEN."""
    return _payload(magnetic_state=1, temperature_c=22.5)


@pytest.fixture
def fire_payload() -> dict:
    """High temp + high acceleration → FIRE_RISK."""
    return _payload(temperature_c=65.0, sound_level=800, accel_x=2.5, accel_y=1.8, accel_z=12.0)


@pytest.fixture
def iron_payload() -> dict:
    """Moderate heat spike + near-zero acceleration → IRON_LEFT_ON."""
    return _payload(
        temperature_c=35.0,
        accel_x=0.0,
        accel_y=0.0,
        accel_z=0.15,  # |a| < 0.5, temp 35 ≤ 40 → iron
    )


@pytest.fixture
def fall_payload() -> dict:
    """Extreme acceleration → FALL_DETECTED region (classified as FIRE_RISK by temp classifier)."""
    return _payload(temperature_c=23.0, accel_x=8.0, accel_y=6.0, accel_z=2.0, sound_level=700)


@pytest.fixture
def water_drip_payload() -> dict:
    """Low but anomalous sound → WATER_DRIPPING."""
    return _payload(sound_level=280, temperature_c=22.1)


# ── Mock DB ──────────────────────────────────────────────────────────────────

def _make_collection(find_one_result=None, find_results=None):
    col = AsyncMock()
    col.find_one = AsyncMock(return_value=find_one_result)
    col.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId(DEMO_EVENT_ID)))
    col.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
    col.insert_many = AsyncMock()

    # find() returns a cursor-like object
    cursor = MagicMock()
    cursor.to_list = AsyncMock(return_value=find_results or [])
    cursor.sort = MagicMock(return_value=cursor)
    col.find = MagicMock(return_value=cursor)
    return col


@pytest.fixture
def mock_db():
    """
    In-memory mock DB with:
    - users collection: returns DEMO_USER_DOC
    - sensor_baselines: returns seeded baselines for any (hour, day_type) query
    - behavioral_schema: returns empty schema
    - events: insert/update succeed silently
    """
    db = MagicMock()

    baseline_doc = {
        "_id": ObjectId(),
        "user_id": ObjectId(DEMO_USER_ID),
        "hour_of_day": 3,
        "day_type": "weekday",
        **BASELINE,
    }

    db.users = _make_collection(find_one_result=DEMO_USER_DOC)
    db.sensor_baselines = _make_collection(find_one_result=baseline_doc)
    db.behavioral_schema = _make_collection(find_one_result=BEHAVIORAL_SCHEMA_DOC)
    db.events = _make_collection(find_one_result=None, find_results=[])
    db.agent_heartbeats = _make_collection()
    db.room_zones = _make_collection(find_one_result={
        "user_id": ObjectId(DEMO_USER_ID),
        "zones": {
            "stove":  {"x": 400, "y": 150, "w": 280, "h": 220},
            "sink":   {"x": 100, "y": 200, "w": 300, "h": 200},
            "fridge": {"x": 50,  "y": 100, "w": 200, "h": 350},
        },
    })

    return db


@pytest.fixture
def mock_db_no_baseline():
    """DB where sensor_baselines returns None — tests the no-baseline path."""
    db = MagicMock()
    db.sensor_baselines = _make_collection(find_one_result=None)
    db.users = _make_collection(find_one_result=DEMO_USER_DOC)
    db.behavioral_schema = _make_collection(find_one_result=BEHAVIORAL_SCHEMA_DOC)
    db.events = _make_collection()
    db.agent_heartbeats = _make_collection()
    return db
