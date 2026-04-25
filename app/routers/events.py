from fastapi import APIRouter, HTTPException
from bson import ObjectId
from app.database import get_db
from app.models.event import EventConfirmRequest, EventDetail, EventResponse
from app.services.learning_service import record_outcome

router = APIRouter()


def _serialize(doc: dict) -> dict:
    doc["event_id"] = str(doc.pop("_id"))
    doc["user_id"] = str(doc["user_id"])
    return doc


@router.get("/{user_id}")
async def list_events(user_id: str, limit: int = 50) -> dict:
    db = get_db()
    docs = await db.events.find(
        {"user_id": ObjectId(user_id)},
        sort=[("detected_at", -1)],
    ).to_list(limit)
    return {"events": [_serialize(d) for d in docs]}


@router.get("/detail/{event_id}")
async def get_event(event_id: str) -> dict:
    db = get_db()
    doc = await db.events.find_one({"_id": ObjectId(event_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Event not found")
    return _serialize(doc)


@router.patch("/{event_id}/confirm", response_model=EventResponse)
async def confirm_event(event_id: str, body: EventConfirmRequest) -> EventResponse:
    """
    Confirm or cancel an event. Triggers learning_service to update baselines
    and behavioral schema.
    """
    db = get_db()
    doc = await db.events.find_one({"_id": ObjectId(event_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Event not found")

    await record_outcome(event_id, body.confirmed, db)

    status = "confirmed" if body.confirmed else "false_positive"
    return EventResponse(
        event_id=event_id,
        status=status,
        message=f"Event marked as {status}. Baselines updated.",
    )
