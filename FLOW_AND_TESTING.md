# HomePulse — End-to-End Flow and Testing Guide

This document describes how data moves through the backend, agents, and optional frontend, and how to verify each layer.

---

## Startup process (run the full program)

Follow these steps **in order** the first time you run HomePulse locally. After that, you usually only need steps 6–8.

### 1. Prerequisites

- **Python 3.11+** (3.13 works; project uses async tests and modern typing)
- **MongoDB** running and **reachable from your machine** (your PC, a teammate’s PC on the LAN, Docker, or **MongoDB Atlas**). Same `MONGODB_URI` for both FastAPI and `run_agents.py`.
- **Git** (to clone the repo if you have not already)
- Optional: **Node.js 20+** and npm — only if you use the `frontend/` dev console
- Optional: **Arduino** on a COM port, **webcam**, **microphone** — only for hardware and voice-input paths; `POST /sensor/simulate` can drive the agent pipeline without serial

### 2. Project setup

```bash
pip install -r requirements.txt
```

### 3. Environment file

Create or edit **`.env`** in the **repository root** (same folder as `app/`, `run_agents.py`). Minimum to get the API and agents talking to Mongo:

- `MONGODB_URI` — e.g. `mongodb://localhost:27017` or Atlas connection string  
- `MONGODB_DB_NAME` — e.g. `homepulse`  
- `DEFAULT_USER_ID` — a valid **user** document `_id` as a **24-char hex string** (ObjectId)  
- `FETCHAI_AGENT_SEED` — any stable secret string; changing it changes all agent addresses  

Add API keys as you need features:

- `ANTHROPIC_API_KEY` — triage, monitor, vision, emails, dashboard replies  
- `AGENTVERSE_KEY` — ASI:One mailbox for `dashboard_agent`  
- `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET` — vision uploads  
- `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD` — alert / digest email  
- `ELEVENLABS_API_KEY` (and optional `ELEVENLABS_VOICE_ID`) — TTS and wake-word STT  

See **`app/config.py`** for the full list and defaults.

### 4. Agent addresses (required before `run_agents.py`)

Agents message each other by **Fetch.ai address**. Those strings must match your `FETCHAI_AGENT_SEED`.

```bash
python scripts/register_agents.py
```

Copy the printed `*_AGENT_ADDRESS` lines into **`agents/agent_messages.py`**, replacing the old values.

**Do not leave `DASHBOARD_AGENT_ADDRESS` empty** if you use **`voice_input_agent`**: spoken queries are sent to the dashboard agent at that address.

### 5. Frontend env (optional)

If you use the React app:

```bash
cd frontend
copy .env.local.example .env.local   # Windows; use cp on Unix
npm install
```

Fill Cloudinary / API base URL in `.env.local` as needed.

### 6. Start MongoDB

Ensure the database in **`MONGODB_URI`** is up and **your app can open a TCP connection** to it. If Mongo runs on someone else’s laptop, use that machine’s LAN IP (or a tunnel) in the URI, and make sure MongoDB is configured to accept remote connections (not only `127.0.0.1`) and that firewalls allow the port (often `27017`). **Atlas** avoids that wiring by using a cloud hostname instead.

### 7. Start the API (terminal 1)

From the **repo root**:

```bash
uvicorn app.main:app --reload --port 8000
```

- Interactive docs: **http://localhost:8000/docs**  
- Voice overlay page: **http://localhost:8000/voice** (WebSocket **`ws://localhost:8000/voice/ws`**)

### 8. Start the agent bureau (terminal 2)

From the **repo root**:

```bash
python run_agents.py
```

This runs **all** agents in one process (sensor, triage, vision, monitor, notification, dashboard, voice, etc.). The bureau listens on port **8002** by default for uAgents REST traffic; **8000** remains the FastAPI port.

**Order:** API first, then bureau, is the usual habit so `voice_input_agent` can `POST` to `http://localhost:8000/voice/push` as soon as it starts.

### 9. Start the frontend (optional, terminal 3)

From the **repo root**:

```powershell
.\scripts\start_frontend.ps1
```

(macOS / Linux: `chmod +x scripts/start_frontend.sh && ./scripts/start_frontend.sh`)

Or: `cd frontend && npm install && npm run dev`

Open the URL Vite prints (typically **http://localhost:5173**).

### 10. Quick verification

- **Health / API:** open **http://localhost:8000/docs** and try a simple `GET` if you have one wired, or proceed to simulate.  
- **Simulated sensor (full pipeline):** `POST /sensor/simulate` — readings go to Mongo **`sensor_simulation_queue`** so the bureau sees them across processes. Optional **`force_triage`** skips baseline scoring (frontend **“Loud noise (full pipeline)”** uses this). Wait up to one sensor interval (~5s).  
- **Voice overlay:** open **http://localhost:8000/voice**, run the bureau with addresses configured, speak a wake phrase (see **Voice paths** below).  

### 11. ASI:One / Agentverse (production-style chat)

Register the **dashboard** agent on Agentverse and point its HTTP integration at your public **`POST .../dashboard/chat`** URL (deployed host or tunnel). `AGENTVERSE_KEY` in `.env` must match the mailbox agent configuration.

---

## Architecture at a glance

| Component | Role | Typical command |
|-----------|------|-----------------|
| **FastAPI** (`app/main.py`) | REST + WebSocket + Agentverse webhook | `uvicorn app.main:app --reload --port 8000` |
| **Agent bureau** (`run_agents.py`) | Fetch.ai agents + sensor loop | `python run_agents.py` (REST on port **8002** by default) |
| **Frontend** (`frontend/`) | Dev console, Cloudinary playground | `npm run dev` (Vite, often **5173**) |

MongoDB must be reachable using `MONGODB_URI` / `MONGODB_DB_NAME` in `.env`.

---

## Environment variables (summary)

Configure in the project root `.env` (see `app/config.py`):

| Variable | Used for |
|----------|-----------|
| `MONGODB_URI`, `MONGODB_DB_NAME` | All persistence |
| `DEFAULT_USER_ID` | Sensor scoring, events, agents (ObjectId string) |
| `ANTHROPIC_API_KEY` | Triage, monitor reasoning, vision prompts, emails, dashboard chat |
| `FETCHAI_AGENT_SEED` | Deterministic uAgent addresses |
| `AGENTVERSE_KEY` | `dashboard_agent` mailbox (ASI:One) |
| `CLOUDINARY_*` | Image upload/crop in vision path and `/sensor/capture` |
| `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD` | Alert / digest email |
| `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` | TTS (`voice_agent`) and STT (`wake_word_service` / Scribe) |
| `ARDUINO_SERIAL_PORT`, `WEBCAM_INDEX` | Hardware; simulate can bypass serial for logic tests |

Frontend: copy `frontend/.env.local.example` → `frontend/.env.local` for Vite/Cloudinary dev keys if using the React playground.

---

## Agent address book

1. Set `FETCHAI_AGENT_SEED` in `.env`.
2. Run:

   ```bash
   python scripts/register_agents.py
   ```

3. Paste the printed lines into `agents/agent_messages.py`.

**Critical for voice input:**

- **`DASHBOARD_AGENT_ADDRESS`** — `voice_input_agent` sends `VoiceQuery` here. If it stays empty, spoken queries will not reach `dashboard_agent`.
- **`VOICE_INPUT_AGENT_ADDRESS`** — `dashboard_agent` sends `VoiceQueryResponse` here (falls back to sender if misconfigured).

Other addresses route the sensor → triage → … → notification pipeline. After changing the seed, re-run the script and update **all** pasted addresses.

---

## Full agent and sensor pipeline (event path)

1. **Ingress** — Arduino JSON every ~5s via `serial_reader`, **or** `POST /sensor/simulate` → documents in MongoDB collection **`sensor_simulation_queue`** (FIFO), which **`sensor_agent`** drains on its interval. (A legacy in-memory `inject_reading` still runs in the API process but does not reach a separate `run_agents.py` process.)
2. **`sensor_agent`** — Pulls readings, runs `anomaly_detector.score_reading()`.
3. **If anomaly** — `IrregularityEvent` → **`triage_agent`** → `claude_service.triage_event()`.
4. **If dismissed** — Logged; chain stops.
5. **If investigate** — **`history_agent`** and **`vision_agent`** in parallel → **`monitor_agent`**.
6. **`vision_agent`** — Webcam/OpenCV, Claude vision for zones when applicable, Cloudinary upload + crop (`q_auto`/`f_auto`) + optional **Generative Fill** full-frame context URL → `VisionResult` (`context_expanded_url`); optional **`VoiceAlert`** → **`voice_agent`** (TTS + spatial ticks via Claude + ElevenLabs).
7. **`monitor_agent`** — When history + vision are ready, `claude_service.reason_about_event()` (multimodal when image URL is available), writes **events** in MongoDB, sends **`MonitorDecision`** → **`escalation_agent`**.
8. **`escalation_agent`** — Severity ladder → **`EscalationOrder`** → **`notification_agent`**.
9. **`notification_agent`** — Claude draft email → `gmail_service.send_alert()`, cancel window / learning hooks.
10. **`learning_agent`** — Periodic behavioral schema refresh (24h schedule in agent).
11. **`report_agent`** — Weekly digest (7d schedule).
12. **`heartbeat_agent`** — Sensor liveness vs `HEARTBEAT_TIMEOUT_SECONDS`.

For a narrative version with the same steps, see `AGENT_CONTEXT.md` → **Full Data Flow**.

---

## Voice paths (two different agents)

### A. `voice_input_agent` — wake word → question → dashboard → browser

Intended for **spoken questions** (e.g. accessibility).

1. **Wake words** (matched on the **transcript** after STT, lowercase) in `app/services/wake_word_service.py`:

   - `hey homepulse`, `hey home pulse`, `hey pulse`, `hey program`, `homepulse`

2. **Flow:** Mic → VAD → ElevenLabs Scribe → strip wake phrase → queue → `voice_input_agent` → `VoiceQuery` to **`DASHBOARD_AGENT_ADDRESS`** → `dashboard_agent` runs same Mongo/Claude logic as chat → `VoiceQueryResponse` → **`voice_input_agent`** → `POST http://localhost:8000/voice/push` → WebSocket clients.

3. **Follow-up window:** After a greeting or assistant reply, further utterances are accepted **without** the wake phrase for ~22s (`arm_voice_followup_window` / TTS playback hook in `wake_word_service`). Say **bye / goodbye HomePulse / stop listening / end session / good night / dismiss assistant / later home pulse** (and similar — see `agents/voice_input_agent.py`) to call **`disarm_voice_followup_window()`** and return to wake-only mode. Goodbye TTS uses `invoke_playback_hooks=False` so the session does not immediately re-open.

4. **Requires:** FastAPI on **8000**, bureau running, **`DASHBOARD_AGENT_ADDRESS`** set, **`ELEVENLABS_API_KEY`** for transcription, `sounddevice` + working mic.

### B. `voice_agent` — TTS + spatial guidance after vision

Triggered when **`vision_agent`** emits a **`VoiceAlert`** (fractional zone / “pct” path). Uses OpenCV ticks, `spatial_service`, and ElevenLabs TTS. Not the wake-word listener.

---

## FastAPI routes (quick reference)

| Prefix | Purpose |
|--------|---------|
| `/sensor/reading` | HTTP anomaly check (needs `DEFAULT_USER_ID`) |
| `/sensor/simulate` | Queue one reading in **`sensor_simulation_queue`** for **`sensor_agent`** (~5s). Body: flat **`SensorPayload`**, or `{ "payload": {...}, "force_triage": { "event_type", "severity", ... } }` to skip scoring (demo without baselines). Response status **`queued`**. |
| `/sensor/capture` | Webcam frame → Cloudinary calibration image |
| `/events`, `/users`, `/zones`, `/alerts` | CRUD / ops |
| `/dashboard/chat` | Agentverse ASI:One webhook (JSON envelope parsing) |
| `/voice`, `/voice/ws`, `/voice/push` | Deaf-user overlay HTML, WebSocket, internal push from `voice_input_agent` |
| `/search`, `/incidents` | Search and incident APIs (Atlas Search when available; regex fallback if not) |

---

## Testing steps

### 1. Automated tests (no hardware, minimal external APIs)

From the repo root:

```bash
pip install -r requirements.txt
pytest
```

Tests live under `tests/` (`test_anomaly_detector.py`, `test_triage_logic.py`, `test_escalation_logic.py`). `pytest.ini` sets `pythonpath = .` and `testpaths = tests`.

### 2. MongoDB and API smoke

1. Start MongoDB (local or Atlas) and set `MONGODB_URI`, `MONGODB_DB_NAME`, `DEFAULT_USER_ID` (valid user ObjectId string).
2. Start API:

   ```bash
   uvicorn app.main:app --reload --port 8000
   ```

3. Optional: `GET http://localhost:8000/docs` — exercise health/list routes if exposed.

### 3. Full agent bureau + simulated sensor

1. Complete **Agent address book** above.
2. Terminal A: `uvicorn app.main:app --reload --port 8000`
3. Terminal B: `python run_agents.py`
4. **Simulate** a reading (adjust values to exceed your baselines / thresholds):

   ```bash
   curl -X POST http://localhost:8000/sensor/simulate ^
     -H "Content-Type: application/json" ^
     -d "{\"sound_level\":800,\"temperature_c\":60,\"magnetic_state\":0,\"accel_x\":0,\"accel_y\":0,\"accel_z\":1,\"pressure\":1000,\"drop_detected\":0,\"light_change_detected\":0,\"motion_triggered\":1,\"gyro_triggered\":0,\"sound_triggered\":1,\"magnetic_triggered\":0,\"light_level\":512}"
   ```

   (On Unix shells, use single-line JSON and `\` instead of `^`.)

5. **Expect:** `sensor_agent` drains the queue on its **own timer** (not instant). Watch bureau logs for triage → vision → monitor → escalation → notification. Full chain needs **Claude**, and notification path needs **Gmail** if you expect real email.

### 4. HTTP reading endpoint (direct anomaly scoring)

`POST /sensor/reading` with the same JSON shape as `SensorPayload` runs **anomaly detection inside FastAPI** (does not enqueue agents). Useful to confirm `DEFAULT_USER_ID` and baselines without the bureau.

### 5. Dashboard / ASI:One

1. Register the dashboard agent on Agentverse; point the chat integration at your public `POST .../dashboard/chat` URL (ngrok or deployed host).
2. Ensure `AGENTVERSE_KEY` matches the mailbox agent in `dashboard_agent.py`.

Local-only alternative: call `POST http://localhost:8000/dashboard/chat` with a body that mimics Agentverse (see logs in `app/routers/dashboard.py` for raw payload debugging).

### 6. Voice overlay (deaf-user UI)

1. API on 8000, bureau running, **`DASHBOARD_AGENT_ADDRESS`** and **`VOICE_INPUT_AGENT_ADDRESS`** set.
2. Open `http://localhost:8000/voice` in a browser (WebSocket connects to `/voice/ws`).
3. Speak a wake phrase + question; confirm cards for `transcript` and `answer`, or `error` if misconfigured.

### 7. Frontend dev console

```bash
cd frontend
npm install
npm run dev
```

Use the in-app fields for API base URL, user id, and preset actions (events, search, chat, etc.). Optional: Vite proxy to `/api` — see `frontend/vite.config.ts`.

### 8. Atlas Search indexes (optional)

If using MongoDB Atlas with Search:

```bash
python scripts/create_search_index.py
```

On **M0** clusters, FTS index limits may apply; the script and `search_service` are written to degrade gracefully with **regex fallback** when `$search` is unavailable.

### 9. Seed / demo data (optional)

Scripts under `scripts/` (e.g. `seed_history.py`, `seed_events.py`) can populate MongoDB for demos — run only when you intend to reset or augment data.

---

## Common pitfalls

| Symptom | Likely cause |
|---------|----------------|
| Voice queries never get an answer | `DASHBOARD_AGENT_ADDRESS` empty or wrong seed |
| Simulate “does nothing” immediately | `sensor_agent` polls every ~5s; wait or check bureau logs |
| `/sensor/reading` returns error about user | `DEFAULT_USER_ID` missing or invalid |
| No email | Gmail env vars or escalation severity / test path |
| No TTS | Missing `ELEVENLABS_API_KEY` (TTS/STT may log and skip) |
| Search feels weak on Atlas | Index not created or `OperationFailure` → regex fallback |

---

## Related docs

- `AGENT_CONTEXT.md` — implementation rules and detailed agent behavior  
- `pitch/mongodb.md` — collections and search notes  
- `scripts/register_agents.py` — refresh all `*_AGENT_ADDRESS` constants  
