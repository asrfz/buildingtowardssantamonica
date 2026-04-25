from datetime import datetime
from bson import ObjectId


def build_zone_doc(user_id: str, zones: dict) -> dict:
    return {
        "user_id": ObjectId(user_id),
        "zones": zones,
        "created_at": datetime.utcnow(),
    }
