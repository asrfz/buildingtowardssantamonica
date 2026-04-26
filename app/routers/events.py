from fastapi import APIRouter, HTTPException, Query
from bson import ObjectId
from bson.errors import InvalidId
from app.database import get_db
from app.models.event import EventConfirmRequest, EventDetail, EventResponse
from app.services.camera_snapshot_service import CAMERA_SNAPSHOTS_COLL
from app.services.learning_service import record_outcome

router = APIRouter()


def _serialize(doc: dict) -> dict:
    doc["event_id"] = str(doc.pop("_id"))
    doc["user_id"] = str(doc["user_id"])
    return doc


@router.get("/snapshots/{user_id}")
async def list_camera_snapshots(user_id: str, limit: int = Query(48, ge=1, le=100)) -> dict:
    """
    Bureau camera frames stored in MongoDB (preview uploads + vision pipeline).
    Each item has Cloudinary URLs for the frontend gallery.
    """
    db = get_db()
    try:
        oid = ObjectId(user_id)
    except InvalidId:
        raise HTTPException(status_code=400, detail="Invalid user_id") from None
    docs = await db[CAMERA_SNAPSHOTS_COLL].find(
        {"user_id": oid},
        sort=[("created_at", -1)],
    ).to_list(limit)
    snapshots = []
    for d in docs:
        eid = d.get("event_id")
        snapshots.append(
            {
                "snapshot_id": str(d["_id"]),
                "url": d.get("url", ""),
                "cropped_url": d.get("cropped_url", ""),
                "cropped_thumb_url": d.get("cropped_thumb_url", ""),
                "public_id": d.get("public_id", ""),
                "source": d.get("source", ""),
                "event_id": str(eid) if eid else None,
                "event_type": d.get("event_type", ""),
                "width": d.get("width"),
                "height": d.get("height"),
                "created_at": d["created_at"].isoformat() if d.get("created_at") else "",
            }
        )
    return {"snapshots": snapshots}


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
