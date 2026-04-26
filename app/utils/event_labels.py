"""Human-readable labels for event_type — used by events, incidents, and Atlas Search."""

EVENT_LABELS: dict[str, str] = {
    "STOVE_LEFT_ON": "Stove Left On",
    "IRON_LEFT_ON": "Iron Left On",
    "FIRE_RISK": "Fire Risk",
    "FRIDGE_OPEN": "Fridge Left Open",
    "FAUCET_RUNNING": "Faucet Running",
    "WATER_DRIPPING": "Water Dripping",
    "APPLIANCE_FAULT": "Appliance Fault",
    "FALL_DETECTED": "Fall Detected",
    "OBJECT_DROPPED": "Object Dropped",
    "MULTIVARIATE_ANOMALY": "Multi-Sensor Anomaly",
    "TEMPERATURE_ANOMALY": "Temperature Anomaly",
    "SOUND_ANOMALY": "Sound Anomaly",
    "DOOR_SENSOR_ANOMALY": "Door Sensor Change",
    "LIGHTS_OFF": "Lights Left Off",
    "LIGHTS_ON": "Lights On",
    "LIGHT_STATE_CHANGED": "Light State Changed",
}


def label_for_event_type(event_type: str) -> str:
    return EVENT_LABELS.get(event_type, event_type.replace("_", " ").title())
