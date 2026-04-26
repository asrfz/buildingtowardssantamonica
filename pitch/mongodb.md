# HomePulse × MongoDB — Track Pitch

## MongoDB feature index {#mongodb-feature-index}

Capabilities we rely on, with anchors for judges and engineers:

| ID | Capability | Where in repo |
|----|------------|----------------|
| [feat-motor-async](#feat-motor-async) | **Motor** (`AsyncIOMotorClient`) — non-blocking I/O from FastAPI + uAgents | `app/database.py` |
| [feat-flexible-schema](#feat-flexible-schema) | **Document model** — different shapes per collection, indexes where needed | Collections below |
| [feat-aggregation](#feat-aggregation) | **Aggregation pipeline** — search fallbacks, patterns, risk timeline, vector queries | `search_service`, `pattern_service`, `vector_service`, `incident_service` |
| [feat-vector-search](#feat-vector-search) | **Atlas Vector Search** (`$vectorSearch`) — multivariate sensor anomalies; similar incidents | `vector_service`, `incident_service` |
| [feat-atlas-search](#feat-atlas-search) | **Atlas Search** (`$search`) — fuzzy event/incident text | `search_service` |
| [feat-regex-fallback](#feat-regex-fallback) | **Regex fallback** when `$search` unavailable (local Mongo) | `search_service` |
| [feat-transactions](#feat-transactions) | **Multi-document consistency** — incident insert + event link | `incident_service` |
| [feat-upsert-gate](#feat-upsert-gate) | **Atomic find_and_update / upsert** — Cloudinary upload slot gate | `snapshot_cloudinary_gate` |

---

## What we built {#what-we-built}

HomePulse is a real-time home safety system. **MongoDB is the system of record**: baselines, live and historical sensor embeddings, the full **event lifecycle**, per-user calibration and learning, incident reports, simulation queues, optional Atlas search/vector indexes, and small operational collections (heartbeats, snapshot gate, camera snapshots). Agents and FastAPI **share one database** (`MONGODB_URI`, `MONGODB_DB_NAME` in `app/config.py`).

This is not a passive log store. **Triage reads false-positive priors** before calling Claude; **monitor** writes multimodal outcomes; **learning** refreshes behavioral stats and threshold multipliers on a timer. The product’s “memory” lives here.

---

## Architecture: how the app talks to MongoDB {#mongo-architecture}

### Connection lifecycle {#feat-motor-async}

- **`connect_db()`** creates `AsyncIOMotorClient`, runs **`ping`** on the admin DB, and fails fast if the cluster is unreachable (`app/database.py`).
- **`get_db()`** returns `AsyncIOMotorDatabase` for `settings.MONGODB_DB_NAME`. Every agent’s `startup` handler and every FastAPI router that needs data calls **`connect_db()`** once per process (or relies on the app lifespan).

### Why Motor fits HomePulse

The safety pipeline is **async end-to-end** (FastAPI + uAgents). Motor keeps **Mongo I/O off the critical path** of the event loop without ad hoc thread pools for routine queries. The same patterns work in **`monitor_agent`** (after vision+history merge) and in **`GET /events`** (batch reads for the UI).

### Flexible documents {#feat-flexible-schema}

We store **rich, nested** structures where they match the domain: hourly baselines, behavioral schema keyed by event type, raw sensor payloads on events, Cloudinary URLs, optional incident embeddings. Python layers (`event_schema`, services) enforce shape at write time; MongoDB does not require upfront relational migrations for every new field (e.g. adding **`cropped_thumb_url`** to events).

---

## Collections and how they’re used {#collections}

### `users` {#coll-users}

Profile, emergency contacts, **`threshold_multiplier`** (adjusted by **`learning_service.adjust_threshold`**). **`escalation_agent`** reads contacts for HIGH/CRITICAL paths. **`users.py`** seeds a companion **`behavioral_schema`** row on insert.

### `sensor_baselines` {#coll-sensor-baselines}

Per-user, per-hour (weekday/weekend) statistics for z-score anomaly detection. **`anomaly_detector`**, **`baseline_service`**, **`sensor_agent`** path. **`sensor.py`** can list baselines for debugging. **`learning_agent`** does not rewrite this collection directly for the multiplier—that lives on **`users`**; calibration scripts may update baselines.

### `sensor_readings` {#coll-sensor-readings}

Stores **7-D normalized embeddings** (and metadata) for **normal vs anomalous** readings. Powers **multivariate** anomaly detection via **`$vectorSearch`** in **`vector_service`** (filter by `user_id`, `is_anomaly: false` neighbors). The corpus grows with **normal** points, improving neighborhood density over time.

### `events` {#coll-events}

Lifecycle of each anomaly: **`triage_agent`** inserts; **`monitor_agent`** sets confirmed type, severity, reasoning, **`raw_image_url`**, **`cropped_image_url`**, **`cropped_thumb_url`**, status; **`escalation_agent`** / **`notification_agent`** update notification fields; **`learning_service`** updates confirmation/learning fields. **`history_agent`** reads recent rows for **`monitor_agent`**. **`dashboard_agent`** and HTTP **`/events`** expose history to humans.

Indexed / denormalized fields such as **`user_id_str`**, **`event_label`** support text search and sorting (`seed_history.py`, `event_schema`). **`learning_service.record_outcome`** updates confirmation fields and behavioral stats; **confirmed** outcomes can refresh **running baseline statistics** via **`baseline_service`**; **false positives** may trigger optional Cloudinary cleanup (see `app/config.py`).

### `behavioral_schema` {#coll-behavioral-schema}

Per-user aggregates: false-positive rates, occurrence patterns by event type, etc. **`triage_agent`** reads before Claude triage; **`learning_service.refresh_behavioral_schema`** recomputes from **`events`**.

### `room_zones` {#coll-room-zones}

Calibrated zones (pixels or fractions) per room. **`vision_service`** uses as **fallback** when Claude does not find an object in-frame.

### `user_thresholds` {#coll-user-thresholds}

Per-resident bands for interpreting raw sensors (including **light_level**). **`threshold_service`**; aligns “what counts as on/off” with household norms.

### `incident_reports` {#coll-incident-reports}

Structured records for MEDIUM+ escalations (**`incident_service`**): labels, **`risk_score`**, optional **embedding** for “similar incidents,” image URLs, resolution. Linked from **`events.incident_report_id`**. **`$vectorSearch`** on **`incident_vector_index`** for similarity; aggregations for timelines.

### `agent_heartbeats` {#coll-agent-heartbeats}

**`sensor_agent`** updates **`last_seen`** for **`sensor_agent`**; **`heartbeat_agent`** checks silence vs **`HEARTBEAT_TIMEOUT_SECONDS`**; **`dashboard_agent`** periodically refreshes the same row so demos show “online”; **`dashboard.py`** reads for status.

### `sensor_simulation_queue` {#coll-simulation-queue}

**`POST /sensor/simulate`** enqueues synthetic readings; **`sensor_agent`** drains them so **hardware is optional** for demos and CI-style runs.

### `snapshot_cloudinary_gate` {#coll-snapshot-gate}

**`pending_slots`** per user: **`triage_agent`** **grants** a slot when investigation is approved; **`vision_agent`** and **`POST /sensor/preview-snapshot`** **consume** atomically so Cloudinary uploads don’t stack across retries (`snapshot_cloudinary_gate.py`, `SNAPSHOT_CLOUDINARY_GATE_ENABLED`).

### `camera_snapshots` {#coll-camera-snapshots}

Metadata for preview / vision snapshot rows (URLs, **`cropped_thumb_url`**, `source`, `event_id`). **`camera_snapshot_service`**; **`GET /events/snapshots/...`** for the UI gallery.

### `alert_log` {#coll-alert-log}

**`alerts` router** — persisted alert / escalation log for inspection (separate from the core **`events`** stream).

### `arduino_contracts` {#coll-arduino-contracts}

**`integration` router** — optional registration payload for Arduino / contract demos.

### Demo / seed-only

**`raw_sensor_readings`** may appear when **`scripts/seed_history.py`** builds rich synthetic history—not required for the live agent path.

---

## How we used MongoDB well {#how-we-use-it}

1. **Single source of truth for agents and API** — Same collections whether Claude is invoked from **`triage_agent`** or a caregiver hits **`GET /search/events`**. No split-brain between “agent DB” and “web DB.”

2. **Fan-in support** — **`monitor_agent`** merges **history** and **vision** in memory, but both branches **read/write anchored on the same `event_id`** document. MongoDB’s document model matches “one event, many stages.”

3. **Vectors beside operational data** — **Atlas Vector Search** runs on the same cluster as **`events`** and **`sensor_readings`**, so similarity and incidents do not need a separate vector SaaS for the demo architecture.

4. **Search with a local-dev story** — **`$search`** when Atlas indexes exist; **regex fallback** in **`search_service`** when not—pitch works on Atlas; hackathon laptops still query.

5. **Concurrency-sensitive helpers** — **Upload slot** uses **find_one_and_update** so only one consumer wins per credit; **incident** creation uses a **session + transaction** (when supported) to link **`incident_reports`** and **`events`**.

6. **Aggregations for product narratives** — **`pattern_service`** and **`GET /incidents/risk-timeline/...`** turn raw events into “what patterns does this home show?” without shipping data to a warehouse.

---

## MongoDB features checklist (pitch table) {#pitch-checklist}

| Feature | Where |
|--------|--------|
| **Atlas Vector Search** | `sensor_readings` neighbors; `incident_reports` similar incidents |
| **Atlas Search ($search)** | `/search/events`, `/search/incidents` |
| **Aggregation framework** | Patterns, risk timeline, vector pipelines, behavioral refresh inputs |
| **Transactions (when available)** | Incident insert + `events.incident_report_id` |
| **Flexible documents + indexes** | Evolving event and incident shapes |
| **Motor (async)** | `app/database.py`, all routers and agents |

Scripts: **`scripts/create_search_index.py`** (Atlas); **`scripts/seed_demo.py`**, **`scripts/seed_history.py`**, **`scripts/seed_events.py`** for demos.

---

## Data flow summary {#data-flow}

```
Sensor / simulation queue
  → sensor_agent (baselines, embeddings → sensor_readings, vector check)
  → events insert + triage updates
      → parallel history + vision
  → monitor_agent → events (images, thumb, reasoning)
  → escalation / notification → events + optional incident_reports

learning_agent (daily) → behavioral_schema, users.threshold_multiplier

dashboard / HTTP → events, behavioral_schema, agent_heartbeats

preview / vision → snapshot_cloudinary_gate, camera_snapshots
```

---

## Why MongoDB specifically {#why-mongodb}

**Schema flexibility** for a fast-moving multi-agent system: new fields (thumbs, gates, labels) ship without migrations.

**Motor + async** match FastAPI and uAgents.

**Atlas Search + Vector Search** (when enabled) keep **text** and **embedding** retrieval in one operational store.

**Time to demo**: Atlas free tier, or local Mongo with reduced search features—**the app still runs**.

---

## Operator pointers {#operators}

- **`MONGODB_URI`**, **`MONGODB_DB_NAME`** — root `.env`; same values for **uvicorn** and **`run_agents.py`**.
- **`DEFAULT_USER_ID`** — 24-char hex **ObjectId** for the primary demo user; learning and some agents key off it.
- Vector/search indexes: see **`scripts/create_search_index.py`** and **`FLOW_AND_TESTING.md`**.
