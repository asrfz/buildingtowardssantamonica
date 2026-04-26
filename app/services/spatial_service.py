"""
spatial_service — Translates fractional bounding-box coordinates into
plain-language directional guidance for the HomePulse voice pipeline.

Coordinate system (Cloudinary / Claude vision output):
    x : 0.0 = left edge of frame,  1.0 = right edge
    y : 0.0 = top  edge of frame,  1.0 = bottom edge
    w, h : fraction of frame dimensions

Camera perspective:
    FRAME_PERSPECTIVE = "facing"
        Camera is pointed at the user (e.g. laptop webcam).
        Left in frame → user's RIGHT; right in frame → user's LEFT.
        Requires x-axis inversion when translating to spoken direction.

    FRAME_PERSPECTIVE = "side"
        Camera monitors the room from the side (corner mount, shelf).
        Left in frame ≈ user's left. No inversion.

Change FRAME_PERSPECTIVE to match your physical camera placement.
"""

FRAME_PERSPECTIVE: str = "facing"

# ── Internal helpers ──────────────────────────────────────────────────────────

def _center_x(zone: dict) -> float:
    return zone["x"] + zone["w"] / 2.0


def _center_y(zone: dict) -> float:
    return zone["y"] + zone["h"] / 2.0


def _to_user_x(frame_x: float) -> float:
    """Convert frame x-fraction to user's left-right reference frame."""
    return (1.0 - frame_x) if FRAME_PERSPECTIVE == "facing" else frame_x


def _horizontal_label(user_x: float) -> str:
    if user_x < 0.33:
        return "left"
    elif user_x > 0.67:
        return "right"
    return "center"


def _distance_label(w: float, h: float) -> str:
    """Estimate distance from bounding-box area. Larger box → closer object."""
    area = w * h
    if area >= 0.12:
        return "It looks very close to you."
    elif area >= 0.04:
        return "It appears to be a short walk away."
    return "It seems to be further away — look carefully."


# ── Public API ────────────────────────────────────────────────────────────────

def object_initial_alert(object_name: str, zone: dict) -> str:
    """
    Compose the first spoken alert when an object event is detected.

    zone: fractional bounding box {x, y, w, h} from Claude vision /
          Cloudinary coordinate detection.
    """
    user_x = _to_user_x(_center_x(zone))
    direction = _horizontal_label(user_x)
    dist_hint = _distance_label(zone["w"], zone["h"])

    if direction == "center":
        location = "directly in front of you"
    else:
        location = f"to your {direction}"

    return (
        f"Heads up! Your {object_name} is {location}. "
        f"{dist_hint} "
        f"I'll guide you to it."
    )


def correction_phrase(object_zone: dict, user_zone: dict | None) -> str | None:
    """
    Generate a directional correction to steer the user toward the object.

    Returns None when the user has converged on the object (stop the loop).

    object_zone : last known fractional bbox of the object
    user_zone   : fractional bbox of the person, or None if not yet in frame
    """
    obj_user_x = _to_user_x(_center_x(object_zone))

    if user_zone is None:
        direction = _horizontal_label(obj_user_x)
        if direction == "center":
            return "Walk straight ahead — it's right in front of you."
        return f"Head toward your {direction} to find it."

    person_user_x = _to_user_x(_center_x(user_zone))
    diff = obj_user_x - person_user_x   # positive → object is to user's right

    # Within 10 % of frame width AND the bounding boxes are overlapping vertically → converged
    person_area = user_zone["w"] * user_zone["h"]
    if abs(diff) < 0.10 and person_area > 0.05:
        return None  # converged

    if diff > 0.35:
        return "You're too far left — move right."
    elif diff < -0.35:
        return "You're too far right — move left."
    elif diff > 0.12:
        return "A little to your right."
    elif diff < -0.12:
        return "A little to your left."
    else:
        return "You're almost there — reach down and grab it."


def object_retrieved_phrase(object_name: str) -> str:
    return f"Great job! Looks like you found your {object_name}. Well done."


def object_lost_phrase(object_name: str, ticks: int) -> str:
    if ticks <= 3:
        return f"Still searching for your {object_name}. Keep moving in that direction."
    return (
        f"I can't see your {object_name} anymore. "
        f"It may have rolled or been moved. Please look around carefully."
    )
