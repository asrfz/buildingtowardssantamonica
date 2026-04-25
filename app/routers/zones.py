from fastapi import APIRouter, HTTPException
from bson import ObjectId
from app.database import get_db
from app.models.zone import ZoneMapUpdate, ZoneMapResponse

router = APIRouter()


@router.get("/{user_id}", response_model=ZoneMapResponse)
async def get_zones(user_id: str) -> ZoneMapResponse:
    db = get_db()
    doc = await db.room_zones.find_one({"user_id": ObjectId(user_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="No zones configured for this user")
    return ZoneMapResponse(user_id=user_id, zones=doc["zones"])


@router.post("/{user_id}", response_model=ZoneMapResponse)
async def set_zones(user_id: str, body: ZoneMapUpdate) -> ZoneMapResponse:
    db = get_db()
    zones_dict = {
        k: v.model_dump() for k, v in body.zones.model_dump().items() if v is not None
    }
    await db.room_zones.update_one(
        {"user_id": ObjectId(user_id)},
        {"$set": {"zones": zones_dict}},
        upsert=True,
    )
    return ZoneMapResponse(user_id=user_id, zones=body.zones)
