"""
voice_ws -- FastAPI WebSocket router for the HomePulse deaf-user visual overlay.

Endpoints:
    GET  /voice          -- Serves the visual overlay HTML page
    WS   /voice/ws       -- WebSocket; browser connects here for live updates
    POST /voice/push     -- Internal endpoint; voice_input_agent calls this to
                           broadcast a message to all connected browser clients

Message format pushed over WebSocket (JSON):
    {"type": "listening"}                          -- mic is live, waiting
    {"type": "wake_ack",   "text": "..."}          -- wake phrase recognized (immediate)
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
    data: dict = {}


@router.post("/push")
async def push_to_clients(payload: PushPayload) -> dict:
    """
    Broadcast a message to all browser WebSocket clients.
    Not exposed to the internet — localhost:8000 only.
    """
    msg: dict = {"type": payload.type, "text": payload.text}
    if payload.data:
        msg["data"] = payload.data
    await _broadcast(msg)
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

    .card.wake_ack {
      background: #0c1929;
      border: 1px solid #1d4ed8;
      font-size: 0.95rem;
      color: #93c5fd;
    }

    .card.wake_ack::before {
      content: "Wake";
      display: block;
      font-size: 0.7rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: #60a5fa;
      margin-bottom: 6px;
    }

    .card.error {
      background: #1a0f0f;
      border: 1px solid #3a2020;
      font-size: 0.9rem;
      color: #e07070;
    }

    .card.alert {
      border-left: 4px solid #f97316;
      padding: 14px 18px;
      position: relative;
    }

    .card.alert.low      { border-color: #f59e0b; background: #1a1400; }
    .card.alert.medium   { border-color: #f97316; background: #1a0d00; }
    .card.alert.high     { border-color: #ef4444; background: #1a0000; }
    .card.alert.critical { border-color: #dc2626; background: #100000; animation: urgentPulse 1s infinite; }

    @keyframes urgentPulse {
      0%, 100% { box-shadow: 0 0 0 0 rgba(220,38,38,0); }
      50%       { box-shadow: 0 0 12px 2px rgba(220,38,38,0.4); }
    }

    .alert-header {
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 8px;
    }

    .sev-badge {
      font-size: 0.65rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      padding: 2px 8px;
      border-radius: 4px;
    }

    .sev-badge.low      { background: #78350f; color: #fef3c7; }
    .sev-badge.medium   { background: #7c2d12; color: #fed7aa; }
    .sev-badge.high     { background: #7f1d1d; color: #fee2e2; }
    .sev-badge.critical { background: #450a0a; color: #fca5a5; }

    .alert-label {
      font-size: 1rem;
      font-weight: 600;
      color: #f0f0f0;
      flex: 1;
    }

    .alert-action {
      font-size: 0.875rem;
      color: #bbb;
      margin: 0;
    }

    .alert-img {
      margin-top: 10px;
      max-width: 100%;
      max-height: 180px;
      border-radius: 8px;
      object-fit: cover;
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
      feed.prepend(card);
      if (feed.children.length > 20) feed.removeChild(feed.lastChild);
    }

    function addAlertCard(label, sev, action, imageUrl) {
      const card = document.createElement('div');
      card.className = `card alert ${sev}`;

      const header = document.createElement('div');
      header.className = 'alert-header';

      const badge = document.createElement('span');
      badge.className = `sev-badge ${sev}`;
      badge.textContent = sev.toUpperCase();

      const title = document.createElement('span');
      title.className = 'alert-label';
      title.textContent = label;

      header.appendChild(badge);
      header.appendChild(title);
      card.appendChild(header);

      if (action) {
        const p = document.createElement('p');
        p.className = 'alert-action';
        p.textContent = action;
        card.appendChild(p);
      }

      if (imageUrl) {
        const img = document.createElement('img');
        img.className = 'alert-img';
        img.src = imageUrl;
        img.alt = label;
        card.appendChild(img);
      }

      feed.prepend(card);
      if (feed.children.length > 20) feed.removeChild(feed.lastChild);
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
        } else if (msg.type === 'wake_ack') {
          setStatus('Wake phrase recognized...', true);
          addCard('wake_ack', msg.text || 'Wake phrase recognized.');
        } else if (msg.type === 'transcript') {
          setStatus('Processing...', false);
          addCard('transcript', msg.text);
        } else if (msg.type === 'answer') {
          setStatus('Listening for wake word...', true);
          addCard('answer', msg.text);
        } else if (msg.type === 'error') {
          setStatus('Error -- try again', false);
          addCard('error', msg.text);
        } else if (msg.type === 'alert') {
          const d = msg.data || {};
          const sev = (d.severity || 'MEDIUM').toLowerCase();
          addAlertCard(d.label || msg.text, sev, d.recommended_action || '', (d.image_thumb_url || d.image_url || ''));
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
