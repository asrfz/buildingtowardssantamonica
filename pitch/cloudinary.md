# HomePulse × Cloudinary — Track Pitch

## What We Built

HomePulse captures webcam frames the moment a sensor anomaly is confirmed. Those frames are uploaded to Cloudinary, transformed through a multi-stage encoding pipeline, and distributed to caregivers in alert emails and to the AI pipeline for multimodal reasoning. Cloudinary handles every image in the system — upload, crop, enhance, encode, and serve.

---

## The Encoding Pipeline

Every alert image goes through the same transformation chain:

```
Raw JPEG upload  →  c_crop  →  e_sharpen:80  →  e_improve  →  q_auto
```

### Stage 1 — Raw Upload

The OpenCV webcam frame is JPEG-encoded in memory and uploaded to Cloudinary under a consistent public ID:

```python
raw = cloudinary.uploader.upload(
    buffer.tobytes(),
    public_id=f"homepulse/raw/{event_id}",
    resource_type="image",
    overwrite=True,
)
```

The raw full-frame image is kept for audit trail purposes — `monitor_agent` includes the raw URL in the MongoDB event document and passes it to Claude for full-scene context when needed.

### Stage 2 — c_crop (Dynamic Zone Cropping)

The crop is applied using the zone bounding box detected by Claude vision. Claude returns fractional coordinates (0.0–1.0 as a fraction of the image dimensions). Cloudinary's `fl_relative` flag accepts these directly:

```python
if zone.get("pct"):
    crop_transform = {
        "crop": "crop",
        "x": zone["x"],
        "y": zone["y"],
        "width": zone["w"],
        "height": zone["h"],
        "flags": "relative",    # fractions, not pixels
    }
```

This means Claude's fractional bounding box output is used **directly** as Cloudinary crop parameters — no coordinate conversion, no scaling math. The same coordinate space that Claude uses for spatial voice guidance is the coordinate space Cloudinary uses for the alert thumbnail crop.

If Claude vision fails to detect the object, MongoDB-stored pixel coordinates from manual zone calibration serve as fallback (no `fl_relative` flag, absolute pixel values instead).

### Stage 3 — e_sharpen:80

Webcam footage is softer than reference photographs. A sharpening pass at intensity 80 compensates for motion blur and autofocus lag, making the cropped object zone crisp enough to be useful in a caregiver alert email — especially for small objects like burner knobs or dripping faucets.

### Stage 4 — e_improve

Cloudinary's content-aware auto-enhancement adjusts brightness, contrast, and saturation per-image based on the image's actual content. A dimly-lit nighttime kitchen gets different treatment than a bright midday scene. This runs without any manual calibration and handles the full range of lighting conditions that occur in a real home over 24 hours.

### Stage 5 — q_auto (Context-Aware Quality Encoding)

`q_auto` is the most important encoding choice in the pipeline. Cloudinary analyzes each image's visual complexity and selects the smallest file size that retains perceived visual quality:

- A blurry background behind a sharp stove burner → low quality for the background, high quality for the burner area
- A noisy nighttime frame → more aggressive compression without visible degradation
- A sharp daytime scene with clear detail → higher quality to preserve the diagnostic value

Webcam frames vary wildly in quality — exposure, noise, motion, lighting all shift throughout a day of real use. `q_auto` removes the manual quality tuning problem entirely. Alert thumbnails in emails are always crisp and appropriately compressed without a per-image quality knob.

```python
transformation = [
    _build_crop_transform(zone),
    {"effect": "sharpen:80"},
    {"effect": "improve"},
    {"quality": "auto"},
]

cropped_url = cloudinary.utils.cloudinary_url(
    f"homepulse/raw/{event_id}",
    transformation=transformation,
)[0]
```

The cropped URL is generated via `cloudinary_url()` — no second upload, no additional API call. Cloudinary applies the full transformation chain on-the-fly when the URL is requested.

---

## How Cloudinary Images Flow Through the System

```
vision_agent captures frame (OpenCV)
    → cloudinary_service.upload_and_crop()
        → raw upload → homepulse/raw/{event_id}
        → generate cropped_url with [crop, sharpen, improve, q_auto]
    → VisionResult(raw_url, cropped_url) → monitor_agent
        → monitor_agent passes cropped_url to Claude for multimodal reasoning
        → monitor_agent stores both URLs in MongoDB events collection
    → VoiceAlert(raw_url, object_bbox) → voice_agent
        → voice_agent speaks directional alert using bbox for spatial guidance
    → escalation_agent → notification_agent
        → Claude writes HTML email including <img src={cropped_url}>
        → email delivered to caregiver with cropped alert image inline
```

---

## What Cloudinary Does That the Code Doesn't

**Storage and CDN.** Cloudinary serves images directly from its CDN to email clients. No FastAPI endpoint needed to serve alert images, no S3 bucket, no signed URL expiry logic.

**Transformation on demand.** The raw frame is uploaded once. The crop, sharpen, improve, and q_auto transformations are applied every time the cropped URL is requested — if we change the transformation chain, every future request gets the new version without re-uploading.

**Format negotiation.** Cloudinary automatically serves WebP to browsers that accept it and JPEG to clients that don't. Email clients receive an appropriate format for their capabilities.

**Coordinate system bridging.** The `fl_relative` flag means Claude's output (0.0–1.0 fractions) can be passed to Cloudinary without any intermediate math. The object detection, the image crop, and the voice guidance spatial calculation all share the same coordinate space.

---

## Two Image Roles: Stored vs. Transient

**Stored images (Cloudinary):** The initial alert capture — uploaded once, served permanently, included in emails, stored in MongoDB. These need to be archived for audit trail and caregiver reference.

**Transient frames (base64 only):** The voice correction loop captures new frames every 3 seconds and sends them directly to Claude as base64. These are never uploaded to Cloudinary. They're guidance frames — diagnostically useful for a few seconds, not worth storing. This distinction keeps Cloudinary storage lean and API costs minimal.

---

## Why Cloudinary Specifically

**`fl_relative` + `q_auto` together.** The combination of fractional coordinate crops (matching Claude's output directly) and context-aware quality encoding (handling webcam variability automatically) is not available in a standard image processing library or storage service. This combination solves two real problems in the HomePulse pipeline with no additional code.

**No image server to maintain.** Alert images need to be accessible from email clients, from Claude's API (via HTTPS URL), and from the dashboard — across different networks, devices, and formats. Cloudinary handles all of this from a single upload.

**Transformation chain as a URL.** The entire crop-sharpen-improve-encode pipeline is encoded in the Cloudinary URL. Changing the pipeline is a one-line code change, not a batch re-processing job.
