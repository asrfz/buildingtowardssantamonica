import { useCallback, useEffect, useRef, useState } from 'react'
import { CloudinaryPlayground } from './components/CloudinaryPlayground'
import { apiBase, apiJson } from './lib/api'
import { PRESETS, basePayload, simulateBody, FORCE_LOUD_NOISE, type ForceTriage } from './lib/payloads'

const USER_STORAGE = 'homepulse_dev_user_id'

type Tab = 'console' | 'media'

type LiveAlert = {
  /** Mongo event_id when present — dedupes duplicate WebSocket deliveries */
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

function initialUserId(): string {
  const saved = localStorage.getItem(USER_STORAGE)?.trim()
  if (saved) return saved
  const vite = import.meta.env.VITE_DEFAULT_USER_ID?.trim()
  if (vite) return vite
  return ''
}

export default function App() {
  const [tab, setTab] = useState<Tab>('console')
  const [userId, setUserId] = useState(initialUserId)
  const [searchQ, setSearchQ] = useState('stove')
  const [chatQ, setChatQ] = useState('What happened at home this week?')
  const [log, setLog] = useState<string[]>([])
  const [lastJson, setLastJson] = useState<string>('')
  const [busy, setBusy] = useState(false)
  const [wsLines, setWsLines] = useState<string[]>([])
  const [alerts, setAlerts] = useState<LiveAlert[]>([])
  const [cameraError, setCameraError] = useState('')
  const [cameraReady, setCameraReady] = useState(false)
  const [mediaStream, setMediaStream] = useState<MediaStream | null>(null)
  const [cameraRetryToken, setCameraRetryToken] = useState(0)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const videoRef = useRef<HTMLVideoElement>(null)
  const cameraReadyRef = useRef(false)

  useEffect(() => {
    localStorage.setItem(USER_STORAGE, userId)
  }, [userId])

  // One-time: fill User ID from backend DEFAULT_USER_ID if localStorage + Vite env are empty.
  // The browser never sees repo root .env; APP_ENV=development exposes this id via the API.
  useEffect(() => {
    const saved = localStorage.getItem(USER_STORAGE)?.trim()
    const vite = import.meta.env.VITE_DEFAULT_USER_ID?.trim()
    if (saved || vite) return
    let cancelled = false
    ;(async () => {
      try {
        const r = await fetch(`${apiBase()}/integration/dev-context`)
        if (!r.ok || cancelled) return
        const j = (await r.json()) as { default_user_id?: string }
        const id = j.default_user_id?.trim()
        if (id && !cancelled) setUserId(id)
      } catch {
        /* API not up */
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  // Camera only while Testing tab is mounted (video element exists). Cleans up tracks on tab change / unmount.
  useEffect(() => {
    if (tab !== 'console') {
      setMediaStream((prev) => {
        prev?.getTracks().forEach((t) => t.stop())
        return null
      })
      cameraReadyRef.current = false
      setCameraReady(false)
      return
    }

    if (!navigator.mediaDevices?.getUserMedia) {
      setCameraError('Camera API not available (use HTTPS or localhost, not a plain IP over HTTP).')
      return
    }

    let cancelled = false
    let stream: MediaStream | null = null
    setCameraError('')

    ;(async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: 'user', width: { ideal: 1280 } },
          audio: false,
        })
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop())
          return
        }
        setMediaStream(stream)
      } catch (e: unknown) {
        if (cancelled) return
        const name = e instanceof DOMException ? e.name : ''
        if (name === 'NotAllowedError' || name === 'PermissionDeniedError') {
          setCameraError(
            'Camera blocked — click “Retry camera” below, allow the site in the browser lock icon, and disable “Block” for camera.',
          )
        } else if (name === 'NotFoundError' || name === 'DevicesNotFoundError') {
          setCameraError('No camera found on this device.')
        } else {
          const msg = e instanceof Error ? e.message : String(e)
          setCameraError(`Camera error: ${msg}`)
        }
        setMediaStream(null)
        cameraReadyRef.current = false
        setCameraReady(false)
      }
    })()

    return () => {
      cancelled = true
      stream?.getTracks().forEach((t) => t.stop())
      setMediaStream((prev) => {
        prev?.getTracks().forEach((t) => t.stop())
        return null
      })
      cameraReadyRef.current = false
      setCameraReady(false)
    }
  }, [tab, cameraRetryToken])

  // Attach stream to <video> when ref + stream exist (fixes race where getUserMedia resolved before ref was set).
  useEffect(() => {
    if (tab !== 'console') return
    const el = videoRef.current
    if (!el || !mediaStream) {
      cameraReadyRef.current = false
      setCameraReady(false)
      return
    }
    el.srcObject = mediaStream
    const onMeta = () => {
      cameraReadyRef.current = true
      setCameraReady(true)
      setCameraError('')
    }
    el.addEventListener('loadedmetadata', onMeta)
    return () => {
      el.removeEventListener('loadedmetadata', onMeta)
    }
  }, [mediaStream, tab])

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

  // Single WebSocket + dedupe alerts by event_id (multiple tabs / strict mode / reconnects used to duplicate cards).
  useEffect(() => {
    const base = apiBase().replace(/^http/, 'ws')
    const url = `${base}/voice/ws`
    let stopped = false

    const connect = () => {
      if (stopped) return
      if (wsRef.current?.readyState === WebSocket.OPEN) return

      const ws = new WebSocket(url)
      wsRef.current = ws

      ws.onmessage = (ev) => {
        setWsLines((prev) => [...prev.slice(-40), ev.data])
        try {
          const msg = JSON.parse(ev.data) as {
            type?: string
            data?: Record<string, string | undefined>
            text?: string
          }
          if (msg.type === 'capture' && msg.data?.event_id) {
            captureAndPostFrame(msg.data.event_id)
          } else if (msg.type === 'alert' && msg.data) {
            const eventId = typeof msg.data.event_id === 'string' ? msg.data.event_id : ''
            const label = String(msg.data.label || msg.data.event_type || 'Alert')
            const severity = String(msg.data.severity || 'MEDIUM').toUpperCase()
            const recommended = String(msg.data.recommended_action || msg.text || '')
            const imageUrl = msg.data.image_url || undefined
            const time = new Date().toLocaleTimeString()
            setAlerts((prev) => {
              const id = eventId || `anon-${label}-${recommended.slice(0, 40)}`
              const next: LiveAlert = { id, label, severity, recommended_action: recommended, image_url: imageUrl, time }
              const without = prev.filter((a) => a.id !== id)
              return [next, ...without].slice(0, 6)
            })
          }
        } catch {
          /* ignore */
        }
      }
      ws.onclose = () => {
        wsRef.current = null
        if (stopped) return
        reconnectTimerRef.current = setTimeout(connect, 2000)
      }
      ws.onerror = () => ws.close()
    }

    connect()
    return () => {
      stopped = true
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current)
        reconnectTimerRef.current = null
      }
      wsRef.current?.close()
      wsRef.current = null
    }
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
    const body = simulateBody(PRESETS[name]())
    run(`Simulate ${name}`, '/sensor/simulate', { method: 'POST', body })
  }

  const simulateWithForce = (label: string, payload: Record<string, unknown>, force: ForceTriage) => {
    run(label, '/sensor/simulate', { method: 'POST', body: simulateBody(payload, force) })
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

          <section className="card camera-card">
            <h2>
              Camera Feed
              {cameraReady && (
                <span style={{ fontSize: '0.75rem', fontWeight: 400, color: '#22c55e', marginLeft: 8 }}>● live</span>
              )}
            </h2>
            {cameraError ? <p className="warn">{cameraError}</p> : null}
            {!cameraError && (
              <p className="hint">
                {cameraReady
                  ? 'Active — frame sent to vision agent when an irregularity is detected.'
                  : 'Starting camera… If blocked, use Retry and allow camera for this site.'}
              </p>
            )}
            <div className="btn-row" style={{ marginBottom: 8 }}>
              <button
                type="button"
                onClick={() => {
                  setCameraError('')
                  setMediaStream((prev) => {
                    prev?.getTracks().forEach((t) => t.stop())
                    return null
                  })
                  cameraReadyRef.current = false
                  setCameraReady(false)
                  setCameraRetryToken((n) => n + 1)
                }}
              >
                Retry camera
              </button>
            </div>
            <div className="camera-stage">
              <video
                ref={videoRef}
                className="camera-feed-video"
                autoPlay
                playsInline
                muted
              />
            </div>
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
                placeholder="Auto-filled from API / VITE_DEFAULT_USER_ID — edit to test another user"
                value={userId}
                onChange={(e) => setUserId(e.target.value)}
                className="mono"
              />
            </label>
            <p className="hint" style={{ marginTop: -6 }}>
              Same value as <code>DEFAULT_USER_ID</code> in the API <code>.env</code>. The UI cannot read that file;
              in development it loads from <code>GET /integration/dev-context</code> (or set{' '}
              <code>VITE_DEFAULT_USER_ID</code> in <code>frontend/.env.local</code>).
            </p>
            <div className="btn-row">
              <a className="link-btn" href={`${apiBase()}/docs`} target="_blank" rel="noreferrer">
                OpenAPI docs
              </a>
              <a className="link-btn" href={`${apiBase()}/voice`} target="_blank" rel="noreferrer">
                Voice overlay (/voice)
              </a>
            </div>
          </section>

          <section className="card live-demos">
            <h2>Live demos — no Arduino</h2>
            <p className="hint">
              Readings are <strong>queued in MongoDB</strong> so <code>sensor_agent</code> in{' '}
              <code>run_agents.py</code> sees them (separate process from FastAPI). Keep API + bureau running.
              Wait up to one sensor interval (~5s), then watch logs / events / alerts.
            </p>
            <div className="btn-row wrap live-demo-actions">
              <button
                type="button"
                className="btn-primary"
                disabled={busy}
                onClick={() =>
                  simulateWithForce('Loud noise → full pipeline', PRESETS.loudNoise(), FORCE_LOUD_NOISE)
                }
              >
                Loud noise (full pipeline)
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => simulatePreset('loudNoise')}
                title="Requires sensor baselines in Mongo; use Loud noise (full pipeline) if scoring returns normal."
              >
                Loud noise (score only)
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() =>
                  simulateWithForce('Force stove anomaly', PRESETS.stove(), {
                    event_type: 'TEMPERATURE_ANOMALY',
                    severity: 'HIGH',
                    deviation_score: 8.0,
                    reason: 'Simulated stove / heat (demo bypass)',
                    sensor: 'temperature',
                  })
                }
              >
                Stove (bypass scoring)
              </button>
            </div>
          </section>

          <section className="card">
            <h2>Sensor → agent pipeline</h2>
            <p className="hint">
              <code>POST /sensor/simulate</code> queues a reading in Mongo + legacy in-memory queue. Needs{' '}
              <code>DEFAULT_USER_ID</code> in <code>.env</code> for the bureau.
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
