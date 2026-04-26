# HomePulse × Anthropic — Track Pitch

## What We Built

HomePulse is a real-time home safety AI for elderly and deaf users. Claude (`claude-sonnet-4-6`) is the reasoning layer that turns raw sensor numbers and webcam frames into language humans can act on. It appears at five distinct points in the pipeline — not as a chatbot, but as a decision-making component embedded in an autonomous agent system.

---

## Where Claude Is Used

### 1. Triage — Should We Investigate?

Every anomaly detected by the sensor pipeline goes through a Claude triage call before any alert is sent. Claude receives:

- Event type (e.g., `STOVE_LEFT_ON`)
- Deviation score (how far above baseline the reading was)
- Raw sensor payload (temperature, sound, accelerometer, pressure)
- Time of day and day type (weekday/weekend)
- The user's historical false positive rate for this event type

Claude decides whether this anomaly is worth investigating. This filters out cases like a loud sound at 7pm that matches the user's historical dinner preparation pattern, or a temperature spike that the behavioral schema has already flagged as a frequent false positive.

```json
{"investigate": true, "confidence": 0.87, "reason": "Temperature 31°C at 2am with no recent activity is unusual for this household."}
```

Without this step, every sensor blip would generate an alert. Claude is the noise filter.

### 2. Multimodal Event Reasoning — What Actually Happened?

After `triage_agent` confirms an event warrants investigation, `history_agent` and `vision_agent` run in parallel. When both return, `monitor_agent` calls Claude with the full picture:

- Raw sensor readings
- Deviation score
- The Cloudinary-cropped alert image (fetched as base64 for multimodal input)
- Last 10 events of the same type for this user
- User's behavioral schema (false positive rates, frequency patterns)
- Time of day

(HomePulse also stores an optional Cloudinary **context-expanded** URL — AI-filled borders on the full frame — for the dev UI only; monitor reasoning uses the zone crop.)

Claude sees the actual webcam frame of what triggered the alert. It reasons across all of this context and returns:

```json
{
  "confirmed_event_type": "STOVE_LEFT_ON",
  "severity": "HIGH",
  "recommended_action": "Please check the kitchen — the stove appears to be on with no one nearby.",
  "suggested_service": "none",
  "reasoning": "Thermal reading 34°C with no accelerometer activity for 18 minutes. Image shows active burner with no person visible."
}
```

This is true multimodal reasoning: Claude is looking at a photo of the kitchen and combining it with sensor telemetry to confirm whether a stove is actually on. No hardcoded image classification, no fine-tuned model — just Claude vision applied to a real-world safety scenario.

### 3. Alert Email Generation

`notification_agent` calls Claude to write the HTML email that goes to the user and their emergency contacts. Claude receives the confirmed event type, severity, recommended action, sensor readings, the Cloudinary image URL, and the user's cancel window.

The prompt instructs Claude to write for elderly users specifically: warm language, no jargon, large-text suggestions in the HTML, a severity badge, and a cancel option for non-CRITICAL events. Claude generates the entire email body — structure, tone, and content — tailored to the event.

```python
prompt = f"""Write a warm, clear HTML email alert for {user_name}, an elderly user.
Event: {event_type.replace("_", " ").title()}
Severity: {severity}
Recommended action: {recommended_action}
...
Requirements:
- Warm, simple language — no technical jargon
- Large readable text suggestions in the HTML
- Include severity badge (red for HIGH/CRITICAL, ...)
- Include cancel option if not CRITICAL"""
```

### 4. Dynamic Object Detection — Vision for Zone Calibration

`vision_agent` uses Claude vision to detect household objects in webcam frames and return their bounding boxes as fractions of the image (0.0–1.0):

```json
{
  "objects": [
    {"name": "stove", "x": 0.1, "y": 0.4, "w": 0.3, "h": 0.25},
    {"name": "sink", "x": 0.6, "y": 0.3, "w": 0.2, "h": 0.2}
  ]
}
```

These fractional coordinates are used directly by the Cloudinary transformation pipeline (`fl_relative` flag) to crop the alert image to the exact object zone. The same coordinates go to `voice_agent` for spatial guidance. Claude vision eliminates the need for pre-calibrated room zones — it detects dynamically, with MongoDB zones serving as a fallback.

### 5. Progressive Spatial Correction — Per-Tick Object Tracking

The voice correction loop in `voice_agent` calls Claude vision every 3 seconds. Claude receives a live webcam frame (as base64, never stored in Cloudinary) and is asked to locate both the object and any person in the frame:

```json
{
  "object": {"found": true, "x": 0.15, "y": 0.42, "w": 0.12, "h": 0.10},
  "person": {"found": true, "x": 0.60, "y": 0.20, "w": 0.20, "h": 0.55}
}
```

`spatial_service` converts these positions into directional language, accounting for camera perspective inversion, and ElevenLabs speaks the correction. Claude is the spatial perception layer — running at 3-second cadence to guide a deaf or elderly user toward something they need to address.

### 6. ASI:One Dashboard Chat

`dashboard_agent` handles natural language queries from caregivers via ASI:One and from deaf users via voice input. Claude receives:

- System online status (sensor heartbeat age)
- The user's name
- Last 7 days of events (type, severity, timestamp, recommended action)
- Behavioral schema statistics

Claude answers in warm, conversational language, with specific rules about when to mention system status vs. when to just answer the historical question:

> "This morning at 9:47 AM, the fridge was detected as open for 12 minutes. HomePulse sent a notification and Margaret closed it shortly after."

### 7. Weekly Digest Email

`report_agent` runs weekly and calls Claude with the full week's event list. Claude doesn't list every event — it synthesizes patterns, highlights recurring issues, offers 1-2 gentle recommendations, and ends on a reassuring note. The output is a warm HTML email suitable for a caregiver who wants a high-level picture of the week.

---

## Why Claude Specifically

**Multimodal out of the box.** The same API call handles text-only triage and image+text event reasoning. No separate vision service, no additional SDK. `claude-sonnet-4-6` accepts base64 image data natively, which is how we pass webcam frames without requiring public URLs for every correction tick.

**Instruction-following at system scale.** Every Claude call in HomePulse returns structured JSON that the calling agent parses and routes. Claude reliably produces the exact JSON schema asked for — `investigate: true/false`, `confirmed_event_type`, `severity`, `suggested_service` — without post-processing guards or retry loops for most cases.

**Context-aware writing.** Claude generates HTML emails and weekly digests that are genuinely appropriate for elderly users — not just readable, but warm and specific to the user's name, history, and situation. This is difficult to achieve with templates and impossible to achieve with smaller models.

**Decision-making under uncertainty.** Claude is asked to triage events using partial information (sensor data only, no image) and to reason about events using full multimodal context. It handles both gracefully, adjusting its confidence and recommendations based on the richness of the available data.

---

## Claude in the Pipeline

```
sensor_agent detects anomaly
    → triage_agent → Claude: "investigate?" [text-only, 200 tokens]
        → [parallel]
            history_agent: retrieves context from MongoDB
            vision_agent → Claude: "what objects are visible?" [vision, 400 tokens]
                → Cloudinary upload with fractional crop
                → voice_agent → Claude: "where is object + person?" [vision, 250 tokens]
                                              × every 3s × up to 10 ticks
        → monitor_agent → Claude: "what happened + what to do?" [vision + text, 400 tokens]
            → escalation_agent
                → notification_agent → Claude: "write the email" [text, 800 tokens]

learning_agent (daily) → behavioral_schema update [no Claude]
report_agent (weekly) → Claude: "write the digest" [text, 600 tokens]
dashboard_agent (on query) → Claude: "answer the caregiver" [text, 300 tokens]
voice_input_agent (on wake word) → dashboard_agent → Claude [text, 300 tokens]
```

Claude runs at triage, vision detection, spatial correction, event reasoning, email composition, digest generation, and conversational query answering. It is not a feature — it is the intelligence layer that connects raw sensor data to human action.
