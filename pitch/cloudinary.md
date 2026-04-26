# HomePulse × Cloudinary — Track Pitch

## Cloudinary feature index {#cloudinary-feature-index}

Every Cloudinary capability this repo uses, with jump links:

| ID | Feature | Where |
|----|---------|--------|
| [feat-upload](#feat-upload) | `uploader.upload` — raw bytes, `public_id`, `resource_type=image`, `overwrite` | Alerts, previews, calibration |
| [feat-tags](#feat-tags) | Upload `tags` (comma-separated) | All uploads |
| [feat-public-id-layout](#feat-public-id-layout) | Namespaced `public_id` paths | `homepulse/raw/…`, `homepulse/snapshots/…`, etc. |
| [feat-secure-url](#feat-secure-url) | `secure_url` from upload response | Stored in Mongo / API |
| [feat-cloudinary-url](#feat-cloudinary-url) | `cloudinary.utils.cloudinary_url` — delivery URLs without second upload | `cropped_url`, `cropped_thumb_url` |
| [feat-crop-relative](#feat-crop-relative) | `crop=crop` + `flags=relative` (fractional x,y,w,h) | Zone from vision (0–1 coords) |
| [feat-crop-absolute](#feat-crop-absolute) | `crop=crop` with integer x,y,w,h | Zone from Mongo calibration |
| [feat-named-transform](#feat-named-transform) | Named transformation after crop (`transformation` key) | Optional `CLOUDINARY_NAMED_TRANSFORM_POSTCROP` |
| [feat-sharpen](#feat-sharpen) | `e_sharpen:80` | Default post-crop; always on thumbnail chain |
| [feat-improve](#feat-improve) | `e_improve` | Delivery tail |
| [feat-q-auto](#feat-q-auto) | `q_auto` | Delivery tail |
| [feat-f-auto](#feat-f-auto) | `f_auto` (`fetch_format: auto`) | Delivery tail |
| [feat-dpr-auto](#feat-dpr-auto) | `dpr_auto` | Caregiver-facing full + thumb chains |
| [feat-c-limit](#feat-c-limit) | `c_limit` + max width | `cropped_thumb_url` |
| [feat-destroy](#feat-destroy) | `uploader.destroy` + `invalidate=True` | False-positive confirm (optional) |

---

## What we built {#what-we-built}

HomePulse captures webcam frames when a sensor anomaly is confirmed. Frames upload to Cloudinary once; we serve **two** derived delivery URLs from the same `public_id` (full crop chain and width-limited thumb). Images flow to caregivers (email, dashboard, voice push), multimodal AI, and audit fields in MongoDB. Cloudinary provides storage, CDN, and on-the-fly transformation.

---

## Encoding pipeline {#encoding-pipeline}

### Alert capture (`homepulse/raw/{event_id}`) {#alert-pipeline}

1. **Raw upload** — JPEG bytes uploaded with tags (see [feat-tags](#feat-tags)).
2. **Zone crop** — `c_crop` from Claude vision (fractional) or calibration (pixels); see [feat-crop-relative](#feat-crop-relative) / [feat-crop-absolute](#feat-crop-absolute).
3. **Post-crop** — Either a **named** Cloudinary transformation ([feat-named-transform](#feat-named-transform)) when `CLOUDINARY_NAMED_TRANSFORM_POSTCROP` is set, or inline: sharpen → improve → `q_auto` → `f_auto` → `dpr_auto` ([feat-sharpen](#feat-sharpen) through [feat-dpr-auto](#feat-dpr-auto)).
4. **Thumbnail chain** — Same crop, then sharpen → **`c_limit,w_<max>`** ([feat-c-limit](#feat-c-limit)) → improve → `q_auto` → `f_auto` → `dpr_auto`. Max width from `CLOUDINARY_ALERT_THUMB_MAX_WIDTH` (default 480). Thumbnail always uses the inline tail (even when the full crop uses a named transform), so list/email tiles stay predictable.

```
Raw JPEG upload  →  c_crop  →  (named transform | sharpen → improve → q_auto → f_auto → dpr_auto)
                    └ same crop → sharpen → c_limit,w_MAX → improve → q_auto → f_auto → dpr_auto  (thumb)
```

Implementation: `app/services/cloudinary_service.py`.

### Other uploads {#other-uploads}

| Path | Purpose | Tags (examples) |
|------|---------|-----------------|
| `homepulse/snapshots/preview/{userId}/{key}` | Dev preview snapshot | `homepulse`, `preview`, `uid_…` |
| `homepulse/reference/calibration` | Zone calibration reference | `homepulse`, `calibration` |

---

## How images flow through the system {#system-flow}

```
vision_agent captures frame
  → cloudinary_service.upload_and_crop()
      → upload homepulse/raw/{event_id} [feat-upload, feat-tags, feat-public-id-layout]
      → cropped_url + cropped_thumb_url via cloudinary_url [feat-cloudinary-url]
  → VisionResult → monitor_agent
      → MongoDB: raw_image_url, cropped_image_url, cropped_thumb_url
      → /voice/push: image_url, image_thumb_url
  → notification_agent / voice_input_agent
      → email & alerts prefer thumb where appropriate
```

When a user marks an event **not** a real incident (`confirmed=false`), `learning_service` may call **`destroy`** on `homepulse/raw/{event_id}` if `CLOUDINARY_DESTROY_ON_FALSE_POSITIVE` is true ([feat-destroy](#feat-destroy)).

---

## What Cloudinary does that the code doesn’t {#platform-value}

**Storage and CDN.** Images load from Cloudinary’s CDN in email clients and browsers; no dedicated image origin in FastAPI.

**Transformation on demand.** One upload; crop and effects are applied per request. Changing the chain updates future deliveries without re-uploading.

**Format negotiation.** `f_auto` serves WebP/AVIF where supported and falls back appropriately elsewhere.

**Coordinate bridging.** `fl_relative` maps Claude’s 0–1 box directly to Cloudinary crop parameters — same space as spatial voice guidance.

---

## Stored vs transient frames {#stored-vs-transient}

**Stored (Cloudinary):** Alert raw + derived URLs; preview snapshots; calibration reference. Tagged for organization and Media Library filtering.

**Transient (base64 only):** Voice correction loop frames go straight to Claude; not uploaded.

---

## Environment variables {#env-vars}

| Variable | Role |
|----------|------|
| `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET` | SDK auth |
| `CLOUDINARY_ALERT_THUMB_MAX_WIDTH` | Thumb `c_limit` width (px) |
| `CLOUDINARY_NAMED_TRANSFORM_POSTCROP` | Optional named transform after crop (full chain only) |
| `CLOUDINARY_DESTROY_ON_FALSE_POSITIVE` | Delete raw asset on false-positive confirm |

---

## Feature notes (anchors) {#feature-notes}

### feat-upload {#feat-upload}

Python SDK `cloudinary.uploader.upload` with in-memory JPEG bytes, fixed or generated `public_id`, `resource_type="image"`, and `overwrite` as needed.

### feat-tags {#feat-tags}

Alerts: `homepulse`, `alert`, `evt_{event_id}`, optional `uid_{user}`, `type_{event_type}`. Previews: `homepulse`, `preview`, `uid_{user}`. Calibration: `homepulse`, `calibration`.

### feat-public-id-layout {#feat-public-id-layout}

- `homepulse/raw/{event_id}` — anomaly frame (destroy target on false positive).
- `homepulse/snapshots/preview/{userId}/{key}` — preview uploads.
- `homepulse/reference/calibration` — single overwrite reference.

### feat-secure-url {#feat-secure-url}

Upload responses expose `secure_url` for the unmodified asset; we persist it as `raw_image_url` / snapshot `url`.

### feat-cloudinary-url {#feat-cloudinary-url}

`cloudinary.utils.cloudinary_url(public_id, transformation=[...])` builds HTTPS delivery URLs for `cropped_image_url` and `cropped_thumb_url` without a second stored object.

### feat-crop-relative {#feat-crop-relative}

When the zone dict has `pct: True`, crop uses fractional x, y, width, height with `flags: relative`.

### feat-crop-absolute {#feat-crop-absolute}

Calibration fallback: integer pixel x, y, width, height, no relative flag.

### feat-named-transform {#feat-named-transform}

If `CLOUDINARY_NAMED_TRANSFORM_POSTCROP` is non-empty, post-crop steps are replaced by `{"transformation": "<name>"}` as defined in the Cloudinary console.

### feat-sharpen {#feat-sharpen}

`{"effect": "sharpen:80"}` on webcam imagery for crisper evidence crops.

### feat-improve {#feat-improve}

`{"effect": "improve"}` — content-aware auto enhancement.

### feat-q-auto {#feat-q-auto}

`{"quality": "auto"}` — perceptual quality vs size.

### feat-f-auto {#feat-f-auto}

`{"fetch_format": "auto"}` — modern formats where supported.

### feat-dpr-auto {#feat-dpr-auto}

`{"dpr": "auto"}` on caregiver-facing full and thumb chains for HiDPI displays.

### feat-c-limit {#feat-c-limit}

After crop and sharpen, `{"width": W, "crop": "limit"}` caps display width while preserving aspect ratio.

### feat-destroy {#feat-destroy}

`cloudinary.uploader.destroy(public_id, resource_type="image", invalidate=True)` removes the raw alert asset when a false positive is confirmed (config-gated).

---

## Why Cloudinary for HomePulse {#why-cloudinary}

**`fl_relative` + `q_auto` + `f_auto` + `dpr_auto`** — Fractional crops aligned with vision output, plus automatic quality, format, and DPR without custom image servers.

**URL-encoded pipelines** — The transformation chain lives in the delivery URL; ops can adjust named transforms in the console for the full-crop path when using that mode.

**Tags + destroy** — Media Library hygiene and optional cleanup when users correct the model.
