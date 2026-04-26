import { useCallback, useEffect, useRef, useState } from 'react'
import { CloudinaryPlayground } from './components/CloudinaryPlayground'
import { apiBase, apiJson } from './lib/api'
import { PRESETS, basePayload } from './lib/payloads'

const USER_STORAGE = 'homepulse_dev_user_id'

type Tab = 'console' | 'media'

type LiveAlert = {
  id: string
  label: string
  severity: string
  recommended_action: string
  image_url?: string
  time: string
}

const SEV_COLORS: Record<string, { border: string; bg: string; badge: string; text: string }> = {
  LOW:      { border: '#f59e0b', bg: '#fffbeb', badge: '#fef3c7', text: '#92400e' },
  MEDIUM:   { border: '#f97316', bg: '#fff7ed', badge: '#fed7aa', text: '#7c2d12' },
  HIGH:     { border: '#ef4444', bg: '#fef2f2', badge: '#fee2e2', text: '#7f1d1d' },
  CRITICAL: { border: '#dc2626', bg: '#fef2f2', badge: '#fca5a5', text: '#450a0a' },
}

export default function App() {
  const [tab, setTab] = useState<Tab>('console')
  const [userId, setUserId] = useState(() => localStorage.getItem(USER_STORAGE) || '')
  const [searchQ, setSearchQ] = useState('stove')
  const [chatQ, setChatQ] = useState('What happened at home this week?')
  const [log, setLog] = useState<string[]>([])
  const [lastJson, setLastJson] = useState<string>('')
  const [busy, setBusy] = useState(false)
  const [wsLines, setWsLines] = useState<string[]>([])
  const [alerts, setAlerts] = useState<LiveAlert[]>([])
  const [cameraError, setCameraError] = useState('')
  const [cameraReady, setCameraReady] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const videoRef = useRef<HTMLVideoElement>(null)
  const cameraReadyRef = useRef(false)

  useEffect(() => {
    localStorage.setItem(USER_STORAGE, userId)
  }, [userId])

  // Request camera on mount
  useEffect(() => {
    navigator.mediaDevices.getUserMedia({ video: true, audio: false })
      .then((stream) => {
        if (videoRef.current) {
          videoRef.current.srcObject = stream
          cameraReadyRef.current = true
          setCameraReady(true)
        }
      })
      .catch(() => setCameraError('Camera permission denied — frame capture disabled'))
  }, [])

  // Capture a frame from the live video and POST it to /vision/frame
  const captureAndPostFrame = useCallback(async (eventId: string) => {
    const video = videoRef.current
    if (!cameraReadyRef.current || !video || video.videoWidth === 0) return
    const canvas = document.createElement('canvas')
    canvas.width = video.videoWidth
    canvas.height = video.videoHeight
    canvas.getContext('2d')?.drawImage(video, 0, 0)
    const dataUrl = canvas.toDataURL('image/jpeg', 0.85)
    const image_b64 = dataUrl.replace(/^data:image\/jpeg;base64,/, '')
    try {
      await fetch(`${apiBase()}/vision/frame`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ event_id: eventId, image_b64 }),
      })
    } catch (e) {
      console.error('[HomePulse] Frame POST failed:', e)
    }
  }, [])

  // Auto-connect WebSocket for live alert feed + capture trigger
  useEffect(() => {
    const base = apiBase().replace(/^http/, 'ws')
    const url = `${base}/voice/ws`

    const connect = () => {
      const ws = new WebSocket(url)
      wsRef.current = ws

      ws.onmessage = (ev) => {
        setWsLines((prev) => [...prev.slice(-40), ev.data])
        try {
          const msg = JSON.parse(ev.data)
          if (msg.type === 'capture' && msg.data?.event_id) {
            captureAndPostFrame(msg.data.event_id)
          } else if (msg.type === 'alert' && msg.data) {
            setAlerts((prev) => [
              {
                id: `${Date.now()}`,
                label: msg.data.label || msg.data.event_type || 'Alert',
                severity: (msg.data.severity || 'MEDIUM').toUpperCase(),
                recommended_action: msg.data.recommended_action || msg.text || '',
                image_url: msg.data.image_url || undefined,
                time: new Date().toLocaleTimeString(),
              },
              ...prev,
            ].slice(0, 5))
          }
        } catch {}
      }
      ws.onclose = () => setTimeout(connect, 2000)
      ws.onerror = () => ws.close()
    }

    connect()
    return () => { wsRef.current?.close() }
  }, [captureAndPostFrame])

  const pushLog = useCallback((line: string) => {
    setLog((prev) => [...prev.slice(-80), `[${new Date().toLocaleTimeString()}] ${line}`])
  }, [])

  const run = useCallback(
    async (label: string, path: string, init?: RequestInit) => {
      setBusy(true)
      pushLog(`${label} → ${init?.method || 'GET'} ${path}`)
      try {
        const { ok, status, data, text } = await apiJson<unknown>(path, init)
        const pretty = data !== null ? JSON.stringify(data, null, 2) : text
        setLastJson(pretty)
        pushLog(ok ? `${label} OK (${status})` : `${label} FAIL (${status})`)
        if (!ok) pushLog(text.slice(0, 500))
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e)
        setLastJson(msg)
        pushLog(`ERROR: ${msg}`)
      } finally {
        setBusy(false)
      }
    },
    [pushLog]
  )

  const simulatePreset = (name: keyof typeof PRESETS) => {
    const body = JSON.stringify(PRESETS[name]())
    run(`Simulate ${name}`, '/sensor/simulate', { method: 'POST', body })
  }

  const refreshEvents = () => {
    if (!userId.trim()) {
      pushLog('Set User ID first (MongoDB ObjectId string).')
      return
    }
    run('List events', `/events/${encodeURIComponent(userId.trim())}`)
  }

  const runSearch = () => {
    const q = searchQ.trim()
    if (!q) return
    const uid = userId.trim()
    const qs = new URLSearchParams({ q })
    if (uid) qs.set('user_id', uid)
    run('Search events', `/search/events?${qs}`)
  }

  const runPatterns = () => {
    if (!userId.trim()) {
      pushLog('Set User ID for patterns.')
      return
    }
    run('Patterns', `/search/patterns/${encodeURIComponent(userId.trim())}`)
  }

  const runIncidents = () => {
    if (!userId.trim()) return
    run('Incidents', `/incidents/${encodeURIComponent(userId.trim())}`)
  }

  const runRisk = () => {
    if (!userId.trim()) return
    run('Risk timeline', `/incidents/risk-timeline/${encodeURIComponent(userId.trim())}?days=30`)
  }

  const runChat = () => {
    const text = chatQ.trim()
    if (!text) return
    run('Dashboard chat', '/dashboard/chat', {
      method: 'POST',
      body: JSON.stringify({ text }),
    })
  }

  return (
    <div className="layout">
      <header className="top">
        <div>
          <h1>HomePulse — Dev console</h1>
          <p className="sub">
            Test FastAPI + agents: simulate sensors, list events, search, patterns, incidents, caregiver Q&amp;A.
            Run API: <code>uvicorn app.main:app --reload --port 8000</code> · Run agents:{' '}
            <code>python run_agents.py</code>
          </p>
        </div>
        <nav className="tabs">
          <button type="button" className={tab === 'console' ? 'active' : ''} onClick={() => setTab('console')}>
            Testing
          </button>
          <button type="button" className={tab === 'media' ? 'active' : ''} onClick={() => setTab('media')}>
            Cloudinary kit
          </button>
        </nav>
      </header>

      {tab === 'console' && (
        <>
          {alerts.length > 0 && (
            <section className="card" style={{ marginTop: 14 }}>
              <h2 style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
                <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#ef4444', display: 'inline-block', animation: 'pulse 1.5s infinite' }} />
                Live Alerts
              </h2>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {alerts.map((alert) => {
                  const c = SEV_COLORS[alert.severity] ?? SEV_COLORS.MEDIUM
                  return (
                    <div key={alert.id} style={{ borderLeft: `4px solid ${c.border}`, background: c.bg, borderRadius: 8, padding: '12px 14px', position: 'relative' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                        <span style={{ background: c.badge, color: c.text, fontSize: '0.65rem', fontWeight: 700, padding: '2px 8px', borderRadius: 4, letterSpacing: '0.08em' }}>
                          {alert.severity}
                        </span>
                        <strong style={{ flex: 1 }}>{alert.label}</strong>
                        <span style={{ fontSize: '0.75rem', color: '#94a3b8' }}>{alert.time}</span>
                        <button
                          type="button"
                          onClick={() => setAlerts((p) => p.filter((a) => a.id !== alert.id))}
                          style={{ background: 'transparent', color: '#94a3b8', padding: '0 4px', fontSize: '1rem', lineHeight: 1 }}
                        >
                          ×
                        </button>
                      </div>
                      <p style={{ margin: 0, fontSize: '0.875rem', color: '#475569' }}>{alert.recommended_action}</p>
                      {alert.image_url && (
                        <img src={alert.image_url} alt={alert.label} style={{ marginTop: 8, maxWidth: '100%', maxHeight: 160, borderRadius: 6, objectFit: 'cover' }} />
                      )}
                    </div>
                  )
                })}
              </div>
            </section>
          )}

          <section className="card">
            <h2>
              Camera Feed
              {cameraReady && (
                <span style={{ fontSize: '0.75rem', fontWeight: 400, color: '#22c55e', marginLeft: 8 }}>● live</span>
              )}
            </h2>
            {cameraError
              ? <p className="warn">{cameraError}</p>
              : <p className="hint">Active — frame sent to vision agent automatically when an irregularity is detected.</p>
            }
            <video
              ref={videoRef}
              autoPlay
              playsInline
              muted
              style={{ width: '100%', borderRadius: 8, background: '#0f172a', display: 'block', marginTop: 8 }}
            />
          </section>

          <section className="card">
            <h2>Connection</h2>
            <label className="row">
              <span>API base</span>
              <input type="text" readOnly value={apiBase()} className="mono" />
            </label>
            <p className="hint">
              Set <code>VITE_API_BASE</code> in <code>frontend/.env.local</code> if not using localhost:8000.
            </p>
            <label className="row">
              <span>User ID (MongoDB)</span>
              <input
                type="text"
                placeholder="DEFAULT_USER_ID from .env"
                value={userId}
                onChange={(e) => setUserId(e.target.value)}
                className="mono"
              />
            </label>
            <div className="btn-row">
              <a className="link-btn" href={`${apiBase()}/docs`} target="_blank" rel="noreferrer">
                OpenAPI docs
              </a>
              <a className="link-btn" href={`${apiBase()}/voice`} target="_blank" rel="noreferrer">
                Voice overlay (/voice)
              </a>
            </div>
          </section>

          <section className="card">
            <h2>Sensor → agent pipeline</h2>
            <p className="hint">
              <code>POST /sensor/simulate</code> injects a reading for <code>sensor_agent</code> (needs bureau
              running).
            </p>
            <div className="btn-row wrap">
              <button type="button" disabled={busy} onClick={() => simulatePreset('normal')}>
                Normal
              </button>
              <button type="button" disabled={busy} onClick={() => simulatePreset('stove')}>
                Stove
              </button>
              <button type="button" disabled={busy} onClick={() => simulatePreset('faucet')}>
                Faucet
              </button>
              <button type="button" disabled={busy} onClick={() => simulatePreset('fridge')}>
                Fridge
              </button>
              <button type="button" disabled={busy} onClick={() => simulatePreset('fire')}>
                Fire-like
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() =>
                  run('Score only (HTTP)', '/sensor/reading', {
                    method: 'POST',
                    body: JSON.stringify(basePayload({ temperature_c: 48, accel_x: 0, accel_y: 0, accel_z: 0.2 })),
                  })
                }
              >
                Score reading (no inject)
              </button>
            </div>
          </section>

          <section className="card">
            <h2>Events &amp; Mongo-backed APIs</h2>
            <div className="btn-row wrap">
              <button type="button" disabled={busy} onClick={refreshEvents}>
                GET /events
              </button>
              <button type="button" disabled={busy} onClick={runSearch}>
                GET /search/events
              </button>
              <button type="button" disabled={busy} onClick={runPatterns}>
                GET /search/patterns
              </button>
              <button type="button" disabled={busy} onClick={runIncidents}>
                GET /incidents
              </button>
              <button type="button" disabled={busy} onClick={runRisk}>
                Risk timeline
              </button>
            </div>
            <label className="row">
              <span>Search query</span>
              <input type="text" value={searchQ} onChange={(e) => setSearchQ(e.target.value)} className="mono" />
            </label>
          </section>

          <section className="card">
            <h2>Caregiver Q&amp;A (same logic as ASI:One hook)</h2>
            <textarea
              rows={3}
              value={chatQ}
              onChange={(e) => setChatQ(e.target.value)}
              className="mono wide"
            />
            <button type="button" disabled={busy} onClick={runChat}>
              POST /dashboard/chat
            </button>
          </section>

          <section className="card">
            <h2>Voice WebSocket <span style={{ fontSize: '0.75rem', fontWeight: 400, color: '#22c55e', marginLeft: 6 }}>● auto-connected</span></h2>
            <p className="hint">Live feed from <code>/voice/ws</code> — alert cards appear above when events are detected.</p>
            {wsLines.length > 0 && (
              <pre className="out small">{wsLines.join('\n')}</pre>
            )}
          </section>

          <section className="card">
            <h2>Activity log</h2>
            <pre className="out small">{log.join('\n') || '—'}</pre>
          </section>

          <section className="card">
            <h2>Last response</h2>
            <pre className="out">{lastJson || '—'}</pre>
          </section>
        </>
      )}

      {tab === 'media' && <CloudinaryPlayground />}
    </div>
  )
}
