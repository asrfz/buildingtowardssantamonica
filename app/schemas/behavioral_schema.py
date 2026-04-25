from datetime import datetime
from bson import ObjectId


def build_behavioral_schema_doc(user_id: str) -> dict:
    return {
        "user_id": ObjectId(user_id),
        "event_type_history": {},
        "updated_at": datetime.utcnow(),
    }
