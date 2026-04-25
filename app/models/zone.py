from pydantic import BaseModel


class ZoneBounds(BaseModel):
    x: int
    y: int
    w: int
    h: int


class ZoneMap(BaseModel):
    stove: ZoneBounds | None = None
    sink: ZoneBounds | None = None
    fridge: ZoneBounds | None = None


class ZoneMapResponse(BaseModel):
    user_id: str
    zones: ZoneMap


class ZoneMapUpdate(BaseModel):
    zones: ZoneMap
