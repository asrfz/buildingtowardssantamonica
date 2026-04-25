from fastapi import APIRouter, HTTPException
from bson import ObjectId
from datetime import datetime
from app.database import get_db
from app.models.alert import AlertCancelResponse

router = APIRouter()


def _serialize(doc: dict) -> dict:
    doc["alert_id"] = str(doc.pop("_id"))
    doc["event_id"] = str(doc["event_id"])
    doc["user_id"] = str(doc["user_id"])
    return doc


@router.get("/{user_id}")
async def list_alerts(user_id: str, limit: int = 50) -> dict:
    db = get_db()
    docs = await db.alert_log.find(
        {"user_id": ObjectId(user_id)},
        sort=[("sent_at", -1)],
    ).to_list(limit)
    return {"alerts": [_serialize(d) for d in docs]}


@router.patch("/{alert_id}/cancel", response_model=AlertCancelResponse)
async def cancel_alert(alert_id: str) -> AlertCancelResponse:
    db = get_db()
    doc = await db.alert_log.find_one({"_id": ObjectId(alert_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Alert not found")
    if doc.get("cancelled"):
        return AlertCancelResponse(alert_id=alert_id, status="already_cancelled", message="Alert was already cancelled.")

    # Link back to event and mark as false positive
    await db.alert_log.update_one(
        {"_id": ObjectId(alert_id)},
        {"$set": {"cancelled": True, "cancelled_at": datetime.utcnow()}},
    )
    if doc.get("event_id"):
        from app.services.learning_service import record_outcome
        await record_outcome(str(doc["event_id"]), confirmed=False, db=db)

    return AlertCancelResponse(
        alert_id=alert_id,
        status="cancelled",
        message="Alert cancelled and marked as false positive.",
    )
