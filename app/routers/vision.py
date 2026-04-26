"""
vision.py — Optional browser frame relay (legacy demos).

Primary vision path uses GET /sensor/live-frame-b64 (OpenCV in the API) from vision_agent / voice_agent.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

# event_id → base64 JPEG string; consumed (deleted) once retrieved
_pending_frames: dict[str, str] = {}


class FramePayload(BaseModel):
    event_id: str
    image_b64: str  # raw base64, no data-URI prefix


@router.post("/frame")
async def receive_frame(payload: FramePayload) -> dict:
    """Browser posts a captured frame here after receiving a 'capture' WS message.
    First writer wins — if multiple tabs post for the same event_id, only the first is kept.
    """
    _pending_frames.setdefault(payload.event_id, payload.image_b64)
    return {"ok": True}


@router.get("/frame/{event_id}")
async def get_frame(event_id: str) -> dict:
    """vision_agent polls this until the browser has posted the frame."""
    image_b64 = _pending_frames.pop(event_id, None)
    if image_b64 is None:
        raise HTTPException(status_code=404, detail="Frame not yet available")
    return {"image_b64": image_b64}
