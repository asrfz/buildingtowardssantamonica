from datetime import datetime


def build_user_doc(name: str, email: str, emergency_contacts: list, threshold_multiplier: float = 2.5) -> dict:
    return {
        "name": name,
        "email": email,
        "emergency_contacts": emergency_contacts,
        "threshold_multiplier": threshold_multiplier,
        "created_at": datetime.utcnow(),
    }
