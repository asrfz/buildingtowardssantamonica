from datetime import datetime
from bson import ObjectId


def build_alert_doc(event_id: str, user_id: str, recipients: list, severity: str, subject: str) -> dict:
    return {
        "event_id": ObjectId(event_id),
        "user_id": ObjectId(user_id),
        "recipients": recipients,
        "severity": severity,
        "subject": subject,
        "sent_at": datetime.utcnow(),
        "cancelled": False,
        "cancelled_at": None,
    }
