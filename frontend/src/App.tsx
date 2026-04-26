import { useCallback, useEffect, useState } from 'react'
import { CloudinaryPlayground } from './components/CloudinaryPlayground'
import { apiBase, apiJson } from './lib/api'
import { PRESETS, basePayload } from './lib/payloads'

const USER_STORAGE = 'homepulse_dev_user_id'

type Tab = 'console' | 'media'

export default function App() {
  const [tab, setTab] = useState<Tab>('console')
  const [userId, setUserId] = useState(() => localStorage.getItem(USER_STORAGE) || '')
  const [searchQ, setSearchQ] = useState('stove')
  const [chatQ, setChatQ] = useState('What happened at home this week?')
  const [log, setLog] = useState<string[]>([])
  const [lastJson, setLastJson] = useState<string>('')
  const [busy, setBusy] = useState(false)
  const [wsLines, setWsLines] = useState<string[]>([])

  useEffect(() => {
    localStorage.setItem(USER_STORAGE, userId)
  }, [userId])

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

  const connectVoiceWs = () => {
    const base = apiBase().replace(/^http/, 'ws')
    const url = `${base}/voice/ws`
    pushLog(`WebSocket → ${url}`)
    try {
      const ws = new WebSocket(url)
      ws.onmessage = (ev) => {
        setWsLines((prev) => [...prev.slice(-40), ev.data])
      }
      ws.onerror = () => pushLog('Voice WS error')
      ws.onclose = () => pushLog('Voice WS closed')
    } catch (e) {
      pushLog(String(e))
    }
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
            <h2>Voice WebSocket</h2>
            <p className="hint">Streams overlay messages when something pushes to <code>/voice/ws</code>.</p>
            <button type="button" onClick={connectVoiceWs}>
              Connect /voice/ws
            </button>
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
