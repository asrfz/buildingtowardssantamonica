"""Shared test IDs and sample docs (used by tests/conftest and test files)."""
from datetime import datetime
from bson import ObjectId

DEMO_USER_ID = str(ObjectId())
DEMO_EVENT_ID = str(ObjectId())

BASELINE = {
    "temperature": {"mean": 22.0, "std_dev": 1.5},
    "sound_level": {"mean": 200, "std_dev": 50},
    "magnetic_state": {"mean": 0, "std_dev": 0.1},
    "accel_x": {"mean": 0.0, "std_dev": 0.05},
    "accel_y": {"mean": 0.0, "std_dev": 0.05},
    "accel_z": {"mean": 9.81, "std_dev": 0.1},
    "pressure": {"mean": 1013.0, "std_dev": 2.0},
}

DEMO_USER_DOC = {
    "_id": ObjectId(DEMO_USER_ID),
    "name": "Margaret Chen",
    "email": "test@example.com",
    "emergency_contacts": [{"name": "Son", "email": "son@example.com", "relationship": "son"}],
    "threshold_multiplier": 2.5,
    "created_at": datetime.utcnow(),
}

BEHAVIORAL_SCHEMA_DOC = {
    "user_id": ObjectId(DEMO_USER_ID),
    "event_type_history": {},
    "updated_at": datetime.utcnow(),
}
