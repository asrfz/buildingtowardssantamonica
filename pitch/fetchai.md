# HomePulse × Fetch.ai — Track Pitch

## What we built

HomePulse is a real-time home safety system. When a sensor anomaly is detected—stove left on, water running, unexpected motion—a **pipeline of autonomous agents** investigates, reasons over multimodal evidence, escalates, and notifies caregivers. **Fetch.ai uAgents** is the message bus: agents talk to each other with **typed payloads** and **stable cryptographic addresses**, not with ad hoc REST between microservices.

There are **13 agents** registered in one **`Bureau`** in `run_agents.py`. Core safety traffic (sensor → … → notification) uses **uAgents `ctx.send` only**. The **FastAPI** app is a separate process: it exposes HTTP/WebSocket for humans and hardware, and a few agents call it with **`httpx`** where a browser or dashboard needs to be pushed to (for example **`POST /voice/push`** after `monitor_agent` finishes reasoning).

---

## Fetch.ai uAgents architecture (how the framework works)

Understanding this makes it obvious *why* the codebase is structured the way it is.

### Agent identity and addressing

Each agent is constructed with a **`name`**, a **`seed`** string, and optional **`port`** / **`mailbox`** / **`agentverse`** settings. The seed is combined with a per-agent suffix (for example `settings.FETCHAI_AGENT_SEED + "_monitor"`). From that, uAgents derives a **cryptographic agent address** (the `agent1q…` strings you see in logs).

**`agents/agent_messages.py`** holds the canonical list of **`*_AGENT_ADDRESS`** constants. Those values must match the seeds: run **`python scripts/register_agents.py`**, paste the printed lines into `agent_messages.py`, and commit. There is no hardcoded IP list—routing is **by address**.

### Bureau: one process, many agents

**`run_agents.py`** builds a **`Bureau`**, adds every agent, and calls **`bureau.run()`**. In this mode:

- All agents share the **same Python event loop** and uAgents **dispatcher**. Messages between them are delivered **in-process** when both ends are in the bureau.
- The bureau binds an **HTTP port** (default **8002**, with a small scan if the port is busy—see `UAGENTS_BUREAU_PORT`).
- For local development we often set **`UAGENTS_SKIP_ALMANAC_REGISTRATION=true`**. That installs **`AlmanacRegistrationSkipped`** (`agents/noop_registration.py`): a **no-op batch registration** so startup does not block on Agentverse/Almanac HTTP. **Local agent-to-agent delivery still works**; you are simply skipping global registry registration from this machine.

This is ideal for hackathons and demos: one command **`python run_agents.py`** brings up the full multi-agent graph.

### Handlers: messages, time, lifecycle

Agents register behavior with decorators:

| Primitive | Role in HomePulse |
|-----------|-------------------|
| **`@agent.on_message(SomeModel)`** | Typed inbox: when another agent `ctx.send`s a `SomeModel`, the handler runs. |
| **`@agent.on_interval(period=…)`** | Recurring work: **`voice_agent`** correction ticks, **`learning_agent`** / **`report_agent`** schedules, **`heartbeat_agent`** sensor liveness, **`dashboard_agent`** heartbeat refresh. |
| **`@agent.on_event("startup")`** | One-shot init: **`connect_db()`**, log address. |

There is no custom scheduler thread for the correction loop—the **framework** drives `on_interval`.

### Messages: contracts, not generic JSON

All cross-agent payloads subclass **`uagents.Model`** (Pydantic v1–compatible), defined in **`agents/agent_messages.py`**. That gives:

- **Versionable contracts** (`VisionResult` carries `cropped_thumb_url`, `spatial_crop_trusted`, etc.).
- **Clear documentation** of who sends what (comments on each class).
- **No “REST spaghetti”** between agents: the graph is **explicit sends** to **`HISTORY_AGENT_ADDRESS`**, **`MONITOR_AGENT_ADDRESS`**, and so on.

Nested Pydantic models are avoided in messages; use **`dict`** / **`list`** for flexible blobs (see comments in `agent_messages.py`).

### When Agentverse / mailbox matters

**`dashboard_agent`** can run in two modes (`app/config.py`: **`HOMEPULSE_DASHBOARD_MAILBOX`**):

- **`false` (default):** Bundled in **`run_agents.py`**. It shares the **same bureau HTTP** as the other agents. **`voice_input_agent`** sends **`VoiceQuery`** to **`DASHBOARD_AGENT_ADDRESS`** and gets **`VoiceQueryResponse`** locally—no tunnel.
- **`true`:** Run **`python agents/dashboard_agent.py`** alone. **`mailbox=True`** and **`agentverse={api_key, url}`** connect the dashboard agent to **Agentverse** so **ASI:One** (or similar) can chat with HomePulse while the rest of the bureau stays on your laptop.

That split is a strong Fetch.ai story: **same agent code**, **different deployment topology**, switched by config.

---

## How we used the architecture well

### 1. Fan-out and fan-in without a “workflow engine”

**`triage_agent`** implements classic **fan-out**: after Claude approves investigation, it sends the same **`TriageResult`** to **`history_agent`** and **`vision_agent`** in parallel (two `ctx.send` calls). Each branch does **slow I/O** (Mongo history vs webcam + Cloudinary + vision) **independently**.

**`monitor_agent`** implements **fan-in**:

- Two **`on_message`** handlers (`UserHistoryContext`, `VisionResult`) each stash their payload in **`_pending[event_id]`**.
- **`_try_reason`** runs when **both** slots exist, then calls Claude once with **full** context.

There is **no central orchestrator** and no `asyncio.gather` across agents—the **graph** is the orchestration. The comment in `monitor_agent` is intentional: the uAgents loop is **single-threaded**, so the in-memory **`_pending`** dict is safe without locks.

### 2. Separation of concerns = separate agents

Each stage has **one job** and one address: detect (**sensor**), gate (**triage**), gather history (**history**), gather pixels (**vision**), synthesize (**monitor**), policy (**escalation**), compose and send email (**notification**). That mirrors how you would **scale or extract** agents later (for example run **vision** on a GPU box) without rewriting the whole app—**addresses** stay stable if seeds stay stable.

### 3. Time-based autonomy

**`learning_agent`**, **`report_agent`**, and **`heartbeat_agent`** are not “called by the API.” They use **`on_interval`** to run **behavioral refresh**, **weekly digest**, and **sensor silence** checks. That matches Fetch.ai’s model: **agents that act on their own clock**, not only on inbound HTTP.

### 4. Honest hybrid with FastAPI

Humans need **HTTP** and **WebSockets**. uAgents does not replace that—it **complements** it. Example: after **`monitor_agent`** updates Mongo, it **`POST`s `/voice/push`** so connected browsers get an alert card. The **source of truth** for the event is still Mongo; the push is **UI glue**. Vision paths can also use **`HOMEPULSE_API_BASE`** for browser-sourced frames where relevant.

### 5. Resilient bureau startup

**`run_agents.py`** wraps **`bureau.add(dashboard_agent)`** in **try/except**: if Agentverse/ledger calls fail at startup, the **core safety pipeline** (sensor through notification) can still run without the dashboard agent. That is a practical use of **modular** agent addition.

---

## The agent network (roles)

### Detection

**`sensor_agent`** — Polls Arduino (or drains **`sensor_simulation_queue`** from **`POST /sensor/simulate`**), runs anomaly scoring and optional vector/embedding checks, sends **`IrregularityEvent`** to **`triage_agent`**.

### Triage

**`triage_agent`** — Loads user context from Mongo (including false-positive priors), asks Claude **investigate yes/no**. On yes, fans out **`TriageResult`** to **`history_agent`** and **`vision_agent`**. (Streak-based early email to emergency contacts is also handled here per `SENSOR_STREAK_EMAIL_THRESHOLD`—see `run_agents.py` header and `triage_agent`.)

### Investigation (parallel)

**`history_agent`** — **`UserHistoryContext`** → **`monitor_agent`**.

**`vision_agent`** — Webcam (or API-fed frame), Claude zone detection, **Cloudinary** upload (`raw_url`, `cropped_url`, `cropped_thumb_url`), **`VisionResult`** → **`monitor_agent`**; optional **`VoiceAlert`** → **`voice_agent`** when spatial guidance is trusted.

### Synthesis

**`monitor_agent`** — Waits for **both** history and vision, calls Claude multimodal reasoning, writes Mongo (including thumb URL), TTS optional line, **`POST /voice/push`**, sends **`MonitorDecision`** → **`escalation_agent`**.

### Response

**`escalation_agent`** — Severity ladder, cancel window, **`EscalationOrder`** → **`notification_agent`**.

**`notification_agent`** — Claude-authored HTML email, Gmail SMTP, Mongo status updates.

### Voice

**`voice_agent`** — **`VoiceAlert`** then **`on_interval`** correction loop (OpenCV → base64 → Claude locate → spatial guidance → ElevenLabs).

**`voice_input_agent`** — Wake word + STT, **`VoiceQuery`** → **`dashboard_agent`**, **`VoiceQueryResponse`** → WebSocket overlay via FastAPI.

### Maintenance

**`heartbeat_agent`** — **`on_interval`**: reads **`agent_heartbeats`** in Mongo (updated by **`sensor_agent`**) and logs if **`sensor_agent`** is silent past **`HEARTBEAT_TIMEOUT_SECONDS`**.

**`learning_agent`** — Periodic behavioral schema / threshold refresh from history.

**`report_agent`** — Weekly digest email.

**`dashboard_agent`** — Natural-language Q&A over Mongo (ASI:One when mailbox mode, or local bureau when bundled).

---

## Message types

Typed **`Model`** classes in **`agents/agent_messages.py`**:

| Message | From → To | Purpose |
|---------|-----------|---------|
| `IrregularityEvent` | sensor → triage | Anomaly + payload + streak metadata |
| `TriageResult` | triage → history, triage → vision | Approved investigation; **fan-out** |
| `UserHistoryContext` | history → monitor | Recent events + behavioral schema |
| `VisionResult` | vision → monitor | Cloudinary **`raw_url`**, **`cropped_url`**, **`cropped_thumb_url`**, zone, **`spatial_crop_trusted`** |
| `MonitorDecision` | monitor → escalation | Confirmed type, severity, action, image URL, sensor payload |
| `EscalationOrder` | escalation → notification | Recipients, severity, cancel window |
| `VoiceAlert` | vision → voice | Fractional bbox + trust flag for spatial TTS |
| `VoiceQuery` | voice_input → dashboard | Wake-word STT transcript |
| `VoiceQueryResponse` | dashboard → voice_input | Answer for WebSocket overlay |

**Note:** `HeartbeatStatus` exists in `agent_messages.py` as a typed placeholder; **today’s `heartbeat_agent` only updates Mongo and logs**—it does not send that message on the wire.

---

## Pipeline at a glance

```
[Arduino / simulate queue] --> sensor_agent
                                    |
                             IrregularityEvent
                                    |
                               triage_agent ----[Claude: investigate?]
                                    |
                    ┌───────────────┴───────────────┐
               TriageResult                    TriageResult
                    |                                |
              history_agent                    vision_agent ----[Claude vision]
                    |                                |         ----[Cloudinary]
         UserHistoryContext                    VisionResult         |
                    └───────────────┬───────────────┘        VoiceAlert
                                    |                            |
                              monitor_agent                 voice_agent
                          [Claude: reason + image]          [TTS + interval loop]
                                    |
                          MonitorDecision
                                    |
                          escalation_agent
                                    |
                          EscalationOrder
                                    |
                         notification_agent
                          [Claude email + Gmail]

[mic] --> voice_input_agent --> VoiceQuery --> dashboard_agent ----[Claude + Mongo]
                      <-- VoiceQueryResponse <--                --> FastAPI WebSocket
```

---

## Why Fetch.ai specifically

**Addresses, not service discovery.** Agents send to **`MONITOR_AGENT_ADDRESS`**; the framework resolves delivery. Same codebase can run **all-in-one** or **split across hosts** as long as seeds and network registration match your deployment choice.

**`on_message` / `on_interval` as the app skeleton.** Fan-in in **`monitor_agent`** and the **voice correction loop** are expressed in **framework primitives**, not bespoke asyncio orchestration.

**Bureau for co-located development.** One process, one command, full graph—ideal for demos and CI-style local runs.

**Agentverse when you need it.** **`dashboard_agent`** mailbox mode connects caregivers via ASI:One without rewriting the agent—**configuration**, not a fork.

**Autonomous timers.** Learning, reporting, and heartbeat are **first-class agent behaviors**, aligned with how Fetch.ai describes long-running autonomous agents—not only request/response workers.

---

## Operator checklist

1. Set **`FETCHAI_AGENT_SEED`** in `.env` (stable per deployment).
2. Run **`python scripts/register_agents.py`** and paste addresses into **`agents/agent_messages.py`**.
3. Ensure **`DASHBOARD_AGENT_ADDRESS`** is non-empty if **`voice_input_agent`** should answer spoken questions.
4. Start **FastAPI** (`uvicorn`) and **`python run_agents.py`** as **two processes** (`FLOW_AND_TESTING.md`).
5. Toggle **`UAGENTS_SKIP_ALMANAC_REGISTRATION`** and **`HOMEPULSE_DASHBOARD_MAILBOX`** per local vs Agentverse dashboard needs.
