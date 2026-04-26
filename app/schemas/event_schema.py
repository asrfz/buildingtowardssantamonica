from datetime import datetime
from bson import ObjectId
from app.utils.event_labels import label_for_event_type


def build_event_doc(
    user_id: str,
    event_type: str,
    severity: str,
    deviation_score: float,
    sensor_payload: dict,
    status: str = "detected",
) -> dict:
    return {
        "user_id": ObjectId(user_id),
        "user_id_str": user_id,
        "event_type": event_type,
        "event_label": label_for_event_type(event_type),
        "severity": severity,
        "deviation_score": deviation_score,
        "sensor_payload": sensor_payload,
        "status": status,
        "confirmed": None,
        "detected_at": datetime.utcnow(),
        "resolved_at": None,
        "notification_sent": False,
        "notification_sent_at": None,
        "email_body": None,
        "triage_reason": None,
        "triage_confidence": None,
        "cropped_image_url": None,
        "raw_image_url": None,
        "context_expanded_image_url": None,
    }
