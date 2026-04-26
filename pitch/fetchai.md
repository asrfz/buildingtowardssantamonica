# HomePulse × Fetch.ai — Track Pitch

## What We Built

HomePulse is a real-time home safety system for elderly and deaf users. When a sensor anomaly is detected — stove left on, water running, unexpected motion — a coordinated pipeline of autonomous AI agents investigates, reasons about, and responds to the event. Fetch.ai's uAgents framework is the nervous system that routes decisions between those agents.

There are **13 autonomous agents** running in a single Bureau. They communicate entirely through typed FetchAI messages. No REST calls between agents, no shared state, no central controller.

---

## The Agent Network

### Detection Layer

**`sensor_agent`** — Polls Arduino sensor data every 5 seconds via serial port. Runs z-score anomaly detection and vector embedding anomaly detection (MongoDB Atlas Vector Search) on each reading. When a reading crosses the anomaly threshold, it fires an `IrregularityEvent` to `triage_agent`.

### Triage Layer

**`triage_agent`** — Receives `IrregularityEvent`. Queries MongoDB for the user's false positive rate for this event type, then calls Claude to decide whether the anomaly warrants investigation. Claude gets: event type, deviation score, raw sensor payload, time of day, and historical false positive rate. If Claude says investigate, `triage_agent` fires `TriageResult` in parallel to two agents simultaneously.

### Investigation Layer (Parallel)

**`history_agent`** — Receives `TriageResult`. Pulls the last 10 events of the same type from MongoDB and the user's behavioral schema. Sends `UserHistoryContext` to `monitor_agent`.

**`vision_agent`** — Receives `TriageResult`. Captures a webcam frame, runs Claude dynamic object detection to find the relevant object's bounding box, uploads the frame to Cloudinary (zone crop with `q_auto`/`f_auto`, plus optional **Generative Fill** context URL on the same asset), and sends a `VisionResult` (`context_expanded_url` when enabled) to `monitor_agent` and optionally a `VoiceAlert` to `voice_agent`.

### Synthesis Layer

**`monitor_agent`** — Waits for both `UserHistoryContext` and `VisionResult` to arrive for the same `event_id`. Once both are in hand, it calls Claude with the full context: sensor data, deviation score, Cloudinary cropped image, event history, and behavioral schema. Claude produces a confirmed event type, severity, recommended action, and suggested emergency service. `monitor_agent` updates MongoDB and fires `MonitorDecision` to `escalation_agent`.

This fan-in pattern — history and vision running in parallel, both feeding a synthesizing agent — is a natural fit for uAgents message routing. There is no orchestration code; both agents just send to `MONITOR_AGENT_ADDRESS` and `monitor_agent` uses an in-memory dict keyed by `event_id` to know when it has both pieces.

### Response Layer

**`escalation_agent`** — Reads the user's emergency contacts from MongoDB. LOW severity is logged only; MEDIUM notifies the user; HIGH and CRITICAL also notify emergency contacts. Fires `EscalationOrder` to `notification_agent` with a configurable cancel window (0 for CRITICAL).

**`notification_agent`** — Calls Claude to write a warm HTML email. Sends via Gmail SMTP. Updates the event status in MongoDB.

### Voice Layer

**`voice_agent`** — Receives `VoiceAlert` from `vision_agent`. The VoiceAlert carries the object's fractional bounding box (same coordinate space as the Cloudinary crop). Speaks an immediate directional alert: "Your water bottle fell to your left." Then enters a **progressive correction loop** on a 3-second `on_interval`: captures webcam frames, sends them to Claude vision as base64, gets updated object and person positions, computes directional guidance via `spatial_service`, and speaks corrections via ElevenLabs until the user converges on the object or a 30-second timeout fires.

**`voice_input_agent`** — Runs ElevenLabs Scribe STT in a background thread with sounddevice audio capture. Detects wake words ("hey HomePulse", "hey program"). When a query is captured, it sends a `VoiceQuery` to `dashboard_agent` via FetchAI message passing. Receives `VoiceQueryResponse` back and pushes the answer to the FastAPI WebSocket overlay for the deaf user's screen.

### Maintenance Layer

**`heartbeat_agent`** — Monitors `sensor_agent` liveness by checking the last heartbeat timestamp in MongoDB. Fires alerts if silence exceeds the configured timeout.

**`learning_agent`** — Runs once per 24 hours. Reanalyzes all historical events, refreshes the behavioral schema with updated false positive rates and occurrence patterns, and adjusts each user's anomaly threshold multiplier.

**`report_agent`** — Runs weekly. Pulls all events from the past 7 days, calls Claude to write a digest, and emails it to the user and caregiver.

**`dashboard_agent`** — Connected to Agentverse via mailbox (`mailbox=True`). Handles natural language queries from ASI:One chat — caregivers can ask "what happened at home this week?" and get a Claude-powered response backed by live MongoDB event data. Also handles `VoiceQuery` messages from `voice_input_agent`.

---

## Message Types

All typed using uAgents `Model` (Pydantic v1):

| Message | From → To | Purpose |
|---|---|---|
| `IrregularityEvent` | sensor → triage | Raw anomaly detection result |
| `TriageResult` | triage → history + vision | Confirmed investigation, fan-out |
| `UserHistoryContext` | history → monitor | Prior events + behavioral schema |
| `VisionResult` | vision → monitor | Cloudinary URLs (`raw`, `cropped`, optional AI context) + zone name |
| `MonitorDecision` | monitor → escalation | Claude's full reasoning output |
| `EscalationOrder` | escalation → notification | Recipients, severity, cancel window |
| `HeartbeatStatus` | heartbeat → escalation | Agent liveness signal |
| `VoiceAlert` | vision → voice | Object bbox for spatial guidance |
| `VoiceQuery` | voice_input → dashboard | Deaf user spoken question |
| `VoiceQueryResponse` | dashboard → voice_input | Claude answer to route to overlay |

---

## Why Fetch.ai Specifically

**Decentralized agent addressing.** Every agent has a cryptographic address derived from its seed phrase. No service discovery, no registry, no hardcoded IPs. An agent sends to `TRIAGE_AGENT_ADDRESS` and the FetchAI network handles routing — whether that agent is running on the same machine, the same LAN, or a remote server.

**`on_message` + `on_interval` as first-class primitives.** The correction loop in `voice_agent` is an `on_interval(3.0)` — the framework drives it. The fan-in in `monitor_agent` is two `on_message` handlers writing to a shared dict and checking for completeness. No asyncio.gather, no polling, no scheduler setup. The framework is the scheduler.

**Bureau for co-located development.** During development and demo, all 13 agents run in a single process via `Bureau`. In production, any agent can be extracted and run independently with no code changes — just point its seed and addresses at the running network.

**Agentverse mailbox for ASI:One.** The `dashboard_agent` registers with Agentverse (`mailbox=True`) and is discoverable from ASI:One's chat interface. Caregivers can talk to HomePulse from ASI:One without any frontend — no ngrok, no port forwarding.

**Autonomous behavior.** `learning_agent` runs every 24 hours without being called. `heartbeat_agent` monitors the network independently. `report_agent` sends weekly digests autonomously. These agents aren't microservices waiting to be called — they are agents acting on schedules and events, which is exactly the Fetch.ai model.

---

## Pipeline at a Glance

```
[Arduino] --serial--> sensor_agent
                           |
                    IrregularityEvent
                           |
                      triage_agent ----[Claude: investigate?]
                           |
              ┌────────────┴────────────┐
         TriageResult              TriageResult
              |                        |
        history_agent            vision_agent ----[Claude vision]
              |                        |         ----[Cloudinary]
     UserHistoryContext           VisionResult         |
              └────────────┬────────────┘        VoiceAlert
                      monitor_agent                    |
                    [Claude: reason]             voice_agent
                           |                   [ElevenLabs TTS]
                    MonitorDecision            [correction loop]
                           |
                    escalation_agent
                           |
                    EscalationOrder
                           |
                   notification_agent
                    [Claude: email]
                    [Gmail SMTP]

[deaf user mic] --> voice_input_agent
                         |
                     VoiceQuery
                         |
                   dashboard_agent ----[Claude + MongoDB]
                         |
                  VoiceQueryResponse
                         |
                   voice_input_agent --> [WebSocket overlay]
```
