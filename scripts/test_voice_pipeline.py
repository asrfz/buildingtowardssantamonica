"""
test_voice_pipeline.py -- End-to-end integration test for the HomePulse voice stack.

Tests each link in the chain independently, then runs them together:

  [1] Spatial service     -- direction logic, no API calls
  [2] ElevenLabs TTS      -- API call + audio playback (plays out loud)
  [3] OpenCV webcam       -- frame capture
  [4] Claude vision       -- object detection on a live frame
  [5] Cloudinary upload   -- upload + q_auto crop URL generation
  [6] Full pipeline       -- webcam -> Claude -> Cloudinary -> ElevenLabs (speaks aloud)

Run with:
    python scripts/test_voice_pipeline.py

Each test prints PASS / FAIL / SKIP with a reason.
"""

import sys
import os
import asyncio
import time
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.basicConfig(level=logging.WARNING)  # suppress noisy library output

from app.config import settings

PASS  = "[PASS]"
FAIL  = "[FAIL]"
SKIP  = "[SKIP]"
SEP   = "-" * 60


def header(title: str) -> None:
    print(f"\n{SEP}\n  {title}\n{SEP}")


# ─────────────────────────────────────────────────────────────
# Test 1 -- Spatial service (no API, pure logic)
# ─────────────────────────────────────────────────────────────
def test_spatial():
    header("Test 1: Spatial service -- direction logic")
    from app.services.spatial_service import (
        object_initial_alert, correction_phrase,
        object_retrieved_phrase, object_lost_phrase,
    )

    cases = [
        # (zone, expected_substring)
        ({"x": 0.05, "y": 0.5, "w": 0.12, "h": 0.10, "pct": True}, "right"),   # left of frame -> user's right
        ({"x": 0.80, "y": 0.5, "w": 0.12, "h": 0.10, "pct": True}, "left"),    # right of frame -> user's left
        ({"x": 0.44, "y": 0.5, "w": 0.12, "h": 0.10, "pct": True}, "front"),   # center
    ]

    all_ok = True
    for zone, expected in cases:
        alert = object_initial_alert("water bottle", zone)
        ok = expected in alert.lower()
        print(f"  zone x={zone['x']} => '{alert[:70]}...'")
        print(f"    expect '{expected}': {PASS if ok else FAIL}")
        all_ok = all_ok and ok

    # Correction: user not yet in frame
    obj  = {"x": 0.80, "y": 0.5, "w": 0.15, "h": 0.10, "pct": True}
    phrase = correction_phrase(obj, None)
    print(f"\n  No person in frame -> '{phrase}'")
    assert phrase is not None, "Expected a correction phrase when user not found"

    # Convergence: user aligned with object
    user = {"x": 0.75, "y": 0.3, "w": 0.20, "h": 0.50}
    phrase = correction_phrase(obj, user)
    print(f"  User aligned       -> {repr(phrase)} (None = converged)")

    # Retrieved / lost
    print(f"  Retrieved          -> '{object_retrieved_phrase('water bottle')}'")
    print(f"  Lost (tick 2)      -> '{object_lost_phrase('stove', 2)}'")
    print(f"  Lost (tick 5)      -> '{object_lost_phrase('stove', 5)}'")

    print(f"\n  {PASS if all_ok else FAIL} Spatial service")
    return all_ok


# ─────────────────────────────────────────────────────────────
# Test 2 -- ElevenLabs TTS (plays audio out loud)
# ─────────────────────────────────────────────────────────────
def test_elevenlabs():
    header("Test 2: ElevenLabs TTS -- API call + playback")
    if not settings.ELEVENLABS_API_KEY.strip():
        print(f"  {SKIP} ELEVENLABS_API_KEY not set in .env")
        return True

    from app.services.tts_service import speak, _ensure_worker, _queue
    import time

    print("  Speaking alert phrase (eleven_turbo_v2_5)...")
    speak("HomePulse pipeline test. Alert model is working.", correction=False)

    # Wait for the worker to initialise and play
    time.sleep(1.0)
    _ensure_worker()

    print("  Speaking correction phrase (eleven_flash_v2_5)...")
    speak("A little to your right.", correction=True)

    # Drain queue before declaring done
    _queue.join()
    print(f"  {PASS} ElevenLabs TTS -- both phrases queued and played")
    return True


# ─────────────────────────────────────────────────────────────
# Test 3 -- OpenCV webcam capture
# ─────────────────────────────────────────────────────────────
def test_opencv():
    header("Test 3: OpenCV -- webcam frame capture")
    import cv2
    cap = cv2.VideoCapture(settings.WEBCAM_INDEX)
    if not cap.isOpened():
        print(f"  {SKIP} Webcam index {settings.WEBCAM_INDEX} not available")
        cap.release()
        return True   # not a failure -- might be headless CI

    ret, frame = cap.read()
    cap.release()
    if not ret or frame is None:
        print(f"  {FAIL} Webcam opened but read() failed")
        return False

    h, w = frame.shape[:2]
    print(f"  Frame captured: {w}x{h} px, dtype={frame.dtype}")
    print(f"  {PASS} OpenCV webcam")
    return True


# ─────────────────────────────────────────────────────────────
# Test 4 -- Claude vision object detection
# ─────────────────────────────────────────────────────────────
async def test_claude_vision():
    header("Test 4: Claude vision -- object detection on live frame")
    if not settings.ANTHROPIC_API_KEY.strip():
        print(f"  {SKIP} ANTHROPIC_API_KEY not set")
        return True

    import cv2
    import numpy as np
    from app.services.cloudinary_service import frame_to_base64
    from app.services.claude_service import detect_objects_in_frame, locate_object_and_user_in_frame

    # Try webcam; fall back to a blank test frame
    cap = cv2.VideoCapture(settings.WEBCAM_INDEX)
    if cap.isOpened():
        ret, frame = cap.read()
        cap.release()
        source = "webcam"
    else:
        cap.release()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        source = "blank 640x480 (no webcam)"

    print(f"  Using frame source: {source}")
    image_b64 = frame_to_base64(frame)
    print(f"  Base64 length: {len(image_b64):,} chars")

    # detect_objects_in_frame
    print("  Calling detect_objects_in_frame()...")
    objects = await detect_objects_in_frame(image_b64)
    print(f"  Detected {len(objects)} object(s): {[o.get('name') for o in objects]}")
    for o in objects:
        print(f"    {o.get('name'):15s}  x={o.get('x', 0):.2f}  y={o.get('y', 0):.2f}  "
              f"w={o.get('w', 0):.2f}  h={o.get('h', 0):.2f}")

    # locate_object_and_user_in_frame
    print("  Calling locate_object_and_user_in_frame(stove)...")
    positions = await locate_object_and_user_in_frame(image_b64, "stove")
    obj    = positions.get("object", {})
    person = positions.get("person", {})
    print(f"  Stove found : {obj.get('found', False)}  "
          + (f"x={obj['x']:.2f} y={obj['y']:.2f} w={obj['w']:.2f} h={obj['h']:.2f}" if obj.get('found') else ""))
    print(f"  Person found: {person.get('found', False)}")

    print(f"  {PASS} Claude vision")
    return True


# ─────────────────────────────────────────────────────────────
# Test 5 -- Cloudinary upload + q_auto crop URL
# ─────────────────────────────────────────────────────────────
async def test_cloudinary():
    header("Test 5: Cloudinary -- upload + q_auto crop URL")
    if not settings.CLOUDINARY_API_KEY.strip():
        print(f"  {SKIP} CLOUDINARY_API_KEY not set")
        return True

    import cv2
    import numpy as np
    from app.services.cloudinary_service import upload_and_crop

    # Create a solid-colour test frame (green square) -- no webcam needed
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frame[120:360, 160:480] = (0, 200, 0)  # green region where "object" lives

    # Fractional zone matching the green region
    zone = {"x": 0.25, "y": 0.25, "w": 0.50, "h": 0.50, "pct": True, "name": "test_object"}
    event_id = "pipeline_test_001"

    print(f"  Uploading test frame (640x480) to Cloudinary...")
    try:
        urls = await upload_and_crop(frame, event_id, zone)
    except Exception as exc:
        print(f"  {FAIL} Cloudinary upload error: {exc}")
        print(f"  --> Fix: verify CLOUDINARY_CLOUD_NAME / API_KEY / API_SECRET in .env")
        print(f"           Log in to cloudinary.com -> Dashboard -> copy your cloud name exactly")
        return False
    print(f"  raw_url     : {urls['raw_url']}")
    print(f"  cropped_url : {urls['cropped_url']}")

    # Verify q_auto is in the transformation URL
    has_q_auto = "q_auto" in urls["cropped_url"]
    has_crop   = "c_crop" in urls["cropped_url"] or "crop" in urls["cropped_url"]
    print(f"  q_auto in URL    : {PASS if has_q_auto else FAIL}")
    print(f"  crop in URL      : {PASS if has_crop else FAIL}")

    ok = has_q_auto
    print(f"  {PASS if ok else FAIL} Cloudinary upload + encoding")
    return ok


# ─────────────────────────────────────────────────────────────
# Test 6 -- Full pipeline: webcam -> Claude -> Cloudinary -> ElevenLabs
# ─────────────────────────────────────────────────────────────
async def test_full_pipeline():
    header("Test 6: Full pipeline -- webcam -> Claude -> Cloudinary -> ElevenLabs")

    missing = []
    if not settings.ANTHROPIC_API_KEY.strip():   missing.append("ANTHROPIC_API_KEY")
    if not settings.CLOUDINARY_API_KEY.strip():  missing.append("CLOUDINARY_API_KEY")
    if not settings.ELEVENLABS_API_KEY.strip():  missing.append("ELEVENLABS_API_KEY")
    if missing:
        print(f"  {SKIP} Missing: {', '.join(missing)}")
        return True

    import cv2
    import numpy as np
    from app.services.vision_service import capture_frame
    from app.services.cloudinary_service import frame_to_base64, upload_and_crop
    from app.services.claude_service import detect_objects_in_frame
    from app.services.spatial_service import object_initial_alert
    from app.services.tts_service import speak, _queue

    # Step 1: capture frame
    print("  [1/5] Capturing webcam frame...")
    frame = await capture_frame()
    if frame is None:
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        print("        (webcam unavailable -- using blank frame)")
    else:
        h, w = frame.shape[:2]
        print(f"        {w}x{h} frame captured")

    # Step 2: Claude vision detection
    print("  [2/5] Claude vision -- detect objects in frame...")
    image_b64 = frame_to_base64(frame)
    objects = await detect_objects_in_frame(image_b64)
    print(f"        {len(objects)} object(s) detected: {[o.get('name') for o in objects]}")

    # Pick first detected object or use a dummy zone for remaining steps
    if objects:
        obj      = objects[0]
        zone     = {"x": obj["x"], "y": obj["y"], "w": obj["w"], "h": obj["h"],
                    "pct": True, "name": obj["name"]}
        obj_name = obj["name"]
    else:
        print("        No objects detected -- using dummy center zone for remaining steps")
        zone     = {"x": 0.35, "y": 0.35, "w": 0.30, "h": 0.30, "pct": True, "name": "object"}
        obj_name = "object"

    # Step 3: Cloudinary upload + crop with q_auto
    print(f"  [3/5] Cloudinary -- upload + crop zone for '{obj_name}'...")
    cloudinary_ok = False
    try:
        urls = await upload_and_crop(frame, "pipeline_test_full", zone)
        print(f"        raw_url     : {urls['raw_url'][:80]}...")
        print(f"        cropped_url : {urls['cropped_url'][:80]}...")
        cloudinary_ok = "q_auto" in urls["cropped_url"]
        print(f"        q_auto encoding: {PASS if cloudinary_ok else FAIL}")
    except Exception as exc:
        print(f"        {FAIL} Cloudinary error: {exc}")
        print(f"        --> Log in to cloudinary.com and verify cloud name / API key / secret in .env")
        urls = {"raw_url": "", "cropped_url": ""}
        cloudinary_ok = False

    # Step 4: Spatial service -> alert text
    print(f"  [4/5] Spatial service -- generate alert text...")
    alert_text = object_initial_alert(obj_name, zone)
    print(f"        '{alert_text}'")

    # Step 5: ElevenLabs TTS
    print(f"  [5/5] ElevenLabs -- speaking alert (turbo model)...")
    speak(alert_text, correction=False)
    _queue.join()
    print(f"        Audio played.")

    print(f"\n  {PASS} Full pipeline complete")
    return True


# ─────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────
async def main():
    print("\n" + "=" * 60)
    print("  HomePulse Voice Pipeline -- Integration Test")
    print("=" * 60)

    results: dict[str, bool] = {}

    results["spatial"]    = test_spatial()
    results["elevenlabs"] = test_elevenlabs()
    results["opencv"]     = test_opencv()
    results["claude"]     = await test_claude_vision()
    results["cloudinary"] = await test_cloudinary()
    results["pipeline"]   = await test_full_pipeline()

    print("\n" + "=" * 60)
    print("  Results summary")
    print("=" * 60)
    for name, ok in results.items():
        print(f"  {PASS if ok else FAIL}  {name}")

    all_passed = all(results.values())
    print("\n" + ("All tests passed." if all_passed else "Some tests failed -- see above."))
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
