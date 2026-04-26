"""
voice_ws -- FastAPI WebSocket router for the HomePulse deaf-user visual overlay.

Endpoints:
    GET  /voice          -- Serves the visual overlay HTML page
    WS   /voice/ws       -- WebSocket; browser connects here for live updates
    POST /voice/push     -- Internal endpoint; voice_input_agent calls this to
                           broadcast a message to all connected browser clients

Message format pushed over WebSocket (JSON):
    {"type": "listening"}                          -- mic is live, waiting
    {"type": "transcript", "text": "..."}          -- user's spoken question
    {"type": "answer",     "text": "..."}          -- Claude's response
    {"type": "error",      "text": "..."}          -- something went wrong

The HTML page (/voice) is self-contained -- no JS framework, no build step.
It connects to the WebSocket and renders cards for each message type.
"""

import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Active WebSocket clients ──────────────────────────────────────────────────
# Module-level set; voice_input_agent (via HTTP POST /voice/push) writes here.

_clients: set[WebSocket] = set()


async def _broadcast(payload: dict) -> None:
    dead: set[WebSocket] = set()
    for ws in list(_clients):
        try:
            await ws.send_text(json.dumps(payload))
        except Exception:
            dead.add(ws)
    _clients.difference_update(dead)


# ── WebSocket endpoint ────────────────────────────────────────────────────────

@router.websocket("/ws")
async def voice_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    _clients.add(websocket)
    logger.info(f"[VoiceWS] Client connected ({len(_clients)} total)")
    try:
        # Send initial state so the page shows "listening" immediately
        await websocket.send_text(json.dumps({"type": "listening"}))
        # Keep the connection alive until the client disconnects
        while True:
            await websocket.receive_text()   # discard client messages
    except WebSocketDisconnect:
        pass
    finally:
        _clients.discard(websocket)
        logger.info(f"[VoiceWS] Client disconnected ({len(_clients)} remaining)")


# ── Internal push endpoint (called by voice_input_agent) ─────────────────────

class PushPayload(BaseModel):
    type: str
    text: str = ""


@router.post("/push")
async def push_to_clients(payload: PushPayload) -> dict:
    """
    voice_input_agent POSTs here to broadcast a message to all browser clients.
    Not exposed to the internet -- runs on localhost:8000 only.
    """
    await _broadcast({"type": payload.type, "text": payload.text})
    return {"clients_notified": len(_clients)}


# ── Visual overlay HTML page ──────────────────────────────────────────────────

_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>HomePulse Voice</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      background: #0f0f11;
      color: #f0f0f0;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      padding: 40px 24px;
      gap: 24px;
    }

    header {
      text-align: center;
    }

    header h1 {
      font-size: 1.5rem;
      font-weight: 600;
      color: #ffffff;
      letter-spacing: -0.02em;
    }

    header p {
      font-size: 0.875rem;
      color: #777;
      margin-top: 4px;
    }

    /* Listening indicator */
    #status {
      display: flex;
      align-items: center;
      gap: 10px;
      background: #1a1a1f;
      border: 1px solid #2a2a35;
      border-radius: 32px;
      padding: 10px 20px;
      font-size: 0.875rem;
      color: #aaa;
    }

    #dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: #22c55e;
      flex-shrink: 0;
    }

    #dot.pulse {
      animation: pulse 1.5s infinite;
    }

    @keyframes pulse {
      0%   { box-shadow: 0 0 0 0 rgba(34,197,94,0.6); }
      70%  { box-shadow: 0 0 0 8px rgba(34,197,94,0); }
      100% { box-shadow: 0 0 0 0 rgba(34,197,94,0); }
    }

    /* Wake words hint */
    #hint {
      font-size: 0.8rem;
      color: #555;
      text-align: center;
      max-width: 480px;
      line-height: 1.6;
    }

    #hint strong {
      color: #888;
    }

    /* Conversation cards */
    #feed {
      width: 100%;
      max-width: 640px;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }

    .card {
      border-radius: 12px;
      padding: 16px 20px;
      line-height: 1.6;
      animation: fadeIn 0.3s ease;
    }

    @keyframes fadeIn {
      from { opacity: 0; transform: translateY(6px); }
      to   { opacity: 1; transform: translateY(0); }
    }

    .card.transcript {
      background: #1e2030;
      border: 1px solid #2a2d45;
      font-size: 1rem;
      color: #c8d0f0;
    }

    .card.transcript::before {
      content: "You said";
      display: block;
      font-size: 0.7rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: #5a6aaa;
      margin-bottom: 6px;
    }

    .card.answer {
      background: #0f1a14;
      border: 1px solid #1a3325;
      font-size: 1.05rem;
      color: #d4f0e0;
    }

    .card.answer::before {
      content: "HomePulse";
      display: block;
      font-size: 0.7rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: #2d7a4a;
      margin-bottom: 6px;
    }

    .card.error {
      background: #1a0f0f;
      border: 1px solid #3a2020;
      font-size: 0.9rem;
      color: #e07070;
    }
  </style>
</head>
<body>
  <header>
    <h1>HomePulse Voice</h1>
    <p>Real-time voice interface for deaf users</p>
  </header>

  <div id="status">
    <span id="dot" class="pulse"></span>
    <span id="status-text">Connecting...</span>
  </div>

  <p id="hint">
    Say <strong>"Hey HomePulse"</strong> or <strong>"Hey Program"</strong>
    followed by your question.<br>
    Example: <em>"Hey HomePulse, what happened at home today?"</em>
  </p>

  <div id="feed"></div>

  <script>
    const dot        = document.getElementById('dot');
    const statusText = document.getElementById('status-text');
    const feed       = document.getElementById('feed');

    function addCard(type, text) {
      const card = document.createElement('div');
      card.className = `card ${type}`;
      card.textContent = text;
      feed.prepend(card);          // newest on top
      if (feed.children.length > 20) {
        feed.removeChild(feed.lastChild);
      }
    }

    function setStatus(text, pulsing) {
      statusText.textContent = text;
      dot.classList.toggle('pulse', pulsing);
      dot.style.background = pulsing ? '#22c55e' : '#f59e0b';
    }

    const wsUrl = `ws://${location.host}/voice/ws`;
    let ws;

    function connect() {
      ws = new WebSocket(wsUrl);

      ws.onopen = () => setStatus('Listening for wake word...', true);

      ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.type === 'listening') {
          setStatus('Listening for wake word...', true);
        } else if (msg.type === 'transcript') {
          setStatus('Processing...', false);
          addCard('transcript', msg.text);
        } else if (msg.type === 'answer') {
          setStatus('Listening for wake word...', true);
          addCard('answer', msg.text);
        } else if (msg.type === 'error') {
          setStatus('Error -- try again', false);
          addCard('error', msg.text);
        }
      };

      ws.onclose = () => {
        setStatus('Reconnecting...', false);
        setTimeout(connect, 2000);
      };

      ws.onerror = () => ws.close();
    }

    connect();
  </script>
</body>
</html>"""


@router.get("", response_class=HTMLResponse)
async def voice_overlay_page() -> HTMLResponse:
    """Visual overlay page for deaf users. Open in a browser while running the system."""
    return HTMLResponse(content=_HTML)
