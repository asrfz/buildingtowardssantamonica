from fastapi import APIRouter, HTTPException
from bson import ObjectId
from datetime import datetime
from app.database import get_db
from app.models.user import UserCreate, UserResponse, UserUpdate
from app.schemas.user_schema import build_user_doc
from app.schemas.behavioral_schema import build_behavioral_schema_doc

router = APIRouter()


def _serialize(doc: dict) -> dict:
    doc["user_id"] = str(doc.pop("_id"))
    return doc


@router.post("", response_model=UserResponse)
async def create_user(body: UserCreate) -> UserResponse:
    db = get_db()
    doc = build_user_doc(
        name=body.name,
        email=body.email,
        emergency_contacts=[c.model_dump() for c in body.emergency_contacts],
        threshold_multiplier=body.threshold_multiplier,
    )
    result = await db.users.insert_one(doc)
    # Bootstrap behavioral schema
    await db.behavioral_schema.insert_one(build_behavioral_schema_doc(str(result.inserted_id)))
    doc["user_id"] = str(result.inserted_id)
    return UserResponse(**doc)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(user_id: str) -> UserResponse:
    db = get_db()
    doc = await db.users.find_one({"_id": ObjectId(user_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse(**_serialize(doc))


@router.patch("/{user_id}")
async def update_user(user_id: str, body: UserUpdate) -> dict:
    db = get_db()
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    if "emergency_contacts" in updates:
        updates["emergency_contacts"] = [
            c.model_dump() if hasattr(c, "model_dump") else c
            for c in updates["emergency_contacts"]
        ]
    await db.users.update_one({"_id": ObjectId(user_id)}, {"$set": updates})
    return {"user_id": user_id, "updated": list(updates.keys())}
