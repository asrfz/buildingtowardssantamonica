# HomePulse × MongoDB — Track Pitch

## What We Built

HomePulse is a real-time home safety AI for elderly and deaf users. It detects anomalies from Arduino sensor data — stove left on, water running, fridge left open, unexpected motion — and coordinates a multi-agent response pipeline that includes computer vision, escalation, and voice guidance.

MongoDB is the backbone of every decision the system makes. Every agent in the pipeline reads from or writes to MongoDB. It is not a logging layer — it is where the intelligence lives.

---

## Collections and How They're Used

### `sensor_baselines`
Each user has 48 baseline documents (24 hours × weekday/weekend). Every baseline stores per-field distributions (mean, std_dev) for temperature, sound level, magnetic state, accelerometer axes, and pressure. The `sensor_agent` queries this collection every 5 seconds to decide whether the latest Arduino reading is anomalous. Without this collection, there is no anomaly detection.

### `sensor_readings` — Vector Embeddings
This is the MongoDB track's centerpiece. Every sensor reading is converted into a **7-dimensional normalized vector** and stored here. The pipeline:

1. Z-score normalize each of the 7 sensor fields against the user's hourly baseline
2. L2-normalize the result to a unit vector (for cosine similarity)
3. Store with `is_anomaly: true/false` and the full raw payload

```
{ user_id, embedding: [float x7], is_anomaly: false, payload: {...}, timestamp_iso }
```

We query this collection using **MongoDB Atlas Vector Search (`$vectorSearch`)** to detect multi-variate anomalies — combinations of mildly unusual readings that wouldn't trip any single z-score threshold but are statistically far from the normal distribution in the full 7-dimensional space.

```python
pipeline = [
    {
        "$vectorSearch": {
            "index": "sensor_vector_index",
            "path": "embedding",
            "queryVector": embedding,
            "numCandidates": 50,
            "limit": 5,
            "filter": {
                "user_id": ObjectId(user_id),
                "is_anomaly": False,
            },
        }
    },
    {"$project": {"score": {"$meta": "vectorSearchScore"}}},
]
```

The returned cosine similarity score (averaged across 5 nearest normal neighbors) determines whether the reading is a **multi-variate anomaly** even when no single sensor tripped. This fires a `MULTIVARIATE_ANOMALY` event through the same pipeline as any other event type.

The vector corpus self-improves: every normal reading gets stored, so the system becomes a more accurate anomaly detector over time without any retraining.

**Atlas index spec:** type `vectorSearch`, 7 dimensions, cosine similarity, with filter fields on `user_id` and `is_anomaly`.

### `events`
The full lifecycle of every detected anomaly lives here. Events are written by `triage_agent` immediately when detection occurs, then updated by `monitor_agent` after Claude vision reasoning completes. Fields include: event type, severity, sensor payload, raw and cropped Cloudinary image URLs, optional **`context_expanded_image_url`** (Generative Fill / illustrative context), Claude's recommended action, triage confidence, and final status (`triaged → monitored → notified`).

The `dashboard_agent` queries this collection to answer natural language questions from caregivers via the ASI:One chat interface: "What happened at home this week?" pulls the last 7 days of events and feeds them into a Claude prompt.

### `behavioral_schema`
The `learning_agent` runs a daily refresh that re-analyzes all historical events per event type per user and updates per-type statistics: occurrence frequency, time-of-day distribution, and false positive rate. The `triage_agent` reads the false positive rate before every Claude triage call to calibrate Claude's confidence threshold — if the system has learned that stove alerts at 7pm are almost always false positives, it tells Claude that context.

### `sensor_baselines` (write path)
The `learning_agent` also adjusts the baseline's threshold multiplier per user based on their specific household behavior. This is stored back into the user document in `users` as `threshold_multiplier` — a dynamic value that tightens or loosens anomaly sensitivity per person.

### `agent_heartbeats`
The `heartbeat_agent` monitors whether `sensor_agent` has recently reported a reading. The `dashboard_agent` refreshes this collection every 90 seconds to keep the system appearing online during demo. The `dashboard_agent` reads it to determine whether to report the monitoring system as active or offline in response to status queries.

### `room_zones`
Pixel-coordinate or fractional bounding boxes for each room's zones of interest (stove, sink, fridge). Used as a fallback by `vision_service` when Claude vision cannot detect an object in the live frame. Claude dynamic detection takes priority; MongoDB serves as the calibrated fallback.

### `user_thresholds`
Per-resident calibrated bands for interpreting raw sensors (temperature, sound, **light_level**, pressure, magnetic). Seeded or computed so the same ADC value can mean “lights on” for one household and “lights off” for another. Consumed by `threshold_service` (`get_user_thresholds`, `upsert_user_thresholds`). This is the Mongo-backed answer to “thresholds depend on the person’s daily habits.”

### `incident_reports`
Structured post-escalation records created by `notification_agent` via `create_incident_report` for MEDIUM+ events. Each document includes human-readable `event_label`, `risk_score`, 7-D **sensor embedding** (cosine-normalized from the incident payload), image URLs, and resolution status. Linked from `events.incident_report_id`.

**Similar incidents:** `GET /incidents/similar/<incident_id>?user_id=...` runs **`$vectorSearch`** on `incident_vector_index` (same cluster as operational data).

**Risk over time:** `GET /incidents/risk-timeline/<user_id>` aggregates incidents by day (`$group` + `$sum` of `risk_score`) for pitch-ready “what happened to this user over time?”

### Searchable events (Atlas Search + fallback)
Events store **`user_id_str`** (string) and **`event_label`** (e.g. “Stove Left On”) at insert time (`build_event_doc`) and refresh `event_label` when `monitor_agent` confirms a type. That feeds **Atlas Search** index `sensor_event_search`:

- **API:** `GET /search/events?q=stove+left+on` — natural language → matching events with **exact `detected_at` timestamps** (e.g. every time the stove was left on).
- **Incidents:** `GET /search/incidents?q=...` uses index `incident_text_search`.

**Atlas-only scripts:** `python scripts/create_search_index.py` (requires Atlas; not localhost). Indexes: `sensor_event_search`, `incident_text_search`, `incident_vector_index`.

**Local / demo:** If `$search` is unavailable, `search_service` **falls back to regex** on the same fields so queries still return results without Atlas.

### Patterns (aggregations, not ML training)
`GET /search/patterns/<user_id>` (`pattern_service.get_full_pattern_report`) runs MongoDB **aggregation pipelines** on `events` / `incident_reports`: frequency by event type, hour-of-day histograms, simple week-over-week trends — “which situations happen more often” for the pitch without a separate analytics warehouse.

### `sensor_readings` (vectors)
Every scored reading can be stored as a **7-dimensional normalized embedding** with `is_anomaly`; **`$vectorSearch`** against normal neighbors powers **multivariate** anomaly detection (`vector_service` / `anomaly_detector`).

### `users`
Name, email, emergency contacts, threshold multiplier. `escalation_agent` reads the contact list to determine who receives notifications for HIGH and CRITICAL severity events.

### Demo data scripts
- `python scripts/seed_demo.py` — minimal user, baselines, zones, behavioral schema.
- `python scripts/seed_history.py` — richer synthetic history (readings, thresholds, events with labels, incidents with embeddings) for screenshots and search demos.

---

## MongoDB features to name in the pitch (checklist)

| Feature | Where |
|--------|--------|
| **Atlas Vector Search** | `sensor_readings` multivariate anomalies; `incident_reports` “similar incidents” |
| **Atlas Search ($search)** | `/search/events`, `/search/incidents` with fuzzy text |
| **Aggregation framework** | Risk timeline, pattern report, behavioral refresh |
| **Transactions** | Incident insert + event `incident_report_id` link |
| **Flexible documents** | Different shapes per collection without migrations |
| **Motor (async)** | FastAPI + agents stay non-blocking |

---

## Why MongoDB Specifically

**Flexible schema across document types.** Each collection has a different structure — baselines have hourly stats, events have vision URLs, behavioral schema has nested per-event-type dicts. Pydantic models handle type safety on the Python side; MongoDB stores whatever structure each agent needs without migration friction.

**Motor async driver.** The entire agent pipeline is async (FastAPI + uAgents). Motor's async driver means database calls are non-blocking inside the event loop — no thread pool overhead for the dozens of queries flying between agents on every event.

**Atlas Vector Search as native infrastructure.** The vector search index runs inside the same cluster as the rest of the data. There's no separate vector database to maintain, no data sync, no additional authentication layer. The `$vectorSearch` aggregation stage filters by `user_id` and `is_anomaly` in a single query — a multi-tenant anomaly detector in one pipeline stage.

**Time to demo.** MongoDB Atlas free tier handles everything — no cluster management, no operations overhead. For a hackathon system that needs to be reliable across a live demo with real sensors generating readings every 5 seconds, that matters.

---

## Data Flow Summary

```
Arduino sensor reading (every 5s)
    → sensor_agent
        → anomaly_detector
            → query sensor_baselines (z-score check)
            → compute 7-dim embedding
            → store in sensor_readings
            → $vectorSearch against sensor_readings (multi-variate check)
        → if anomalous: write to events
            → triage_agent updates events (triage_reason, confidence)
                → monitor_agent updates events (image URLs, recommended_action)
                    → escalation_agent reads users (recipients)
                        → notification_agent updates events (status: notified)

learning_agent (daily)
    → reads events → writes behavioral_schema → adjusts sensor_baselines

dashboard_agent (on query)
    → reads events (last 7 days) + behavioral_schema + agent_heartbeats
    → feeds into Claude → returns caregiver answer
```

Every read. Every write. Every decision. MongoDB.
