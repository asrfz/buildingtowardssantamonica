import { useCallback, useEffect, useRef, useState } from 'react'
import { CloudinaryPlayground } from './components/CloudinaryPlayground'
import { CloudinaryDeliveryImage } from './components/CloudinaryDeliveryImage'
import { VisionCropZoneFrame } from './components/VisionCropZoneFrame'
import { apiBase, apiJson } from './lib/api'
import { parseVisionCropZone, type VisionCropZone } from './lib/visionCropZone'
import { PRESETS, basePayload, simulateBody, FORCE_LOUD_NOISE, type ForceTriage } from './lib/payloads'

const USER_STORAGE = 'homepulse_dev_user_id'

type Tab = 'console' | 'media'

type LiveAlert = {
  /** Mongo event_id when present — dedupes duplicate WebSocket deliveries */
  id: string
  label: string
  severity: string
  recommended_action: string
  /** Full zone crop (Cloudinary delivery URL) */
  image_url?: string
  /** Width-limited crop for cards / email */
  image_thumb_url?: string
  raw_image_url?: string
  vision_crop_zone?: VisionCropZone | null
  time: string
}

function FullFrameCropDetails({
  rawUrl,
  zone,
  summaryColor,
}: {
  rawUrl: string
  zone: VisionCropZone
  summaryColor?: string
}) {
  return (
    <details style={{ marginTop: 8 }}>
      <summary
        style={{
          cursor: 'pointer',
          fontSize: '0.72rem',
          fontWeight: 600,
          color: summaryColor ?? '#475569',
          listStyle: 'none',
        }}
      >
        Full frame · crop region
      </summary>
      <div style={{ marginTop: 8 }}>
        <VisionCropZoneFrame src={rawUrl} zone={zone} maxHeight={200} />
      </div>
    </details>
  )
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

export default function DevConsole() {
  const [tab, setTab] = useState<Tab>('console')
  const [userId, setUserId] = useState(initialUserId)
  const [searchQ, setSearchQ] = useState('stove')
  const [chatQ, setChatQ] = useState('What happened at home this week?')
  const [log, setLog] = useState<string[]>([])
  const [lastJson, setLastJson] = useState<string>('')
  const [busy, setBusy] = useState(false)
  const [wsLines, setWsLines] = useState<string[]>([])
  const [alerts, setAlerts] = useState<LiveAlert[]>([])
  /** Events with Cloudinary URLs from the bureau (vision_agent → Mongo). */
  const [cloudinaryClips, setCloudinaryClips] = useState<
    {
      event_id: string
      event_type: string
      severity: string
      cropped_image_url: string | null
      cropped_thumb_url: string | null
      raw_image_url: string | null
      vision_crop_zone: VisionCropZone | null
      detected_at: string
    }[]
  >([])
  const [clipsLoading, setClipsLoading] = useState(false)
  const [clipsError, setClipsError] = useState('')
  const [snapshotGallery, setSnapshotGallery] = useState<
    {
      snapshot_id: string
      url: string
      cropped_url: string
      cropped_thumb_url?: string
      source: string
      event_id: string | null
      event_type: string
      created_at: string
      vision_crop_zone?: VisionCropZone | null
    }[]
  >([])
  const [snapshotsLoading, setSnapshotsLoading] = useState(false)
  const [snapshotsError, setSnapshotsError] = useState('')
  const [savingSnapshot, setSavingSnapshot] = useState(false)
  /** Cache-bust query for GET /sensor/preview-jpeg (no Cloudinary required for this card). */
  const [bureauPreviewTick, setBureauPreviewTick] = useState(() => Date.now())
  const [bureauPreviewUpdated, setBureauPreviewUpdated] = useState('')
  const [bureauPreviewLoading, setBureauPreviewLoading] = useState(true)
  const [bureauPreviewError, setBureauPreviewError] = useState('')
  const bureauPreviewSrc = `${apiBase()}/sensor/preview-jpeg?t=${bureauPreviewTick}`
  const bumpBureauPreview = useCallback(() => setBureauPreviewTick(Date.now()), [])
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

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

  const fetchCloudinaryClips = useCallback(async () => {
    const uid = userId.trim()
    if (!uid) {
      setCloudinaryClips([])
      setClipsLoading(false)
      return
    }
    setClipsLoading(true)
    setClipsError('')
    const ac = new AbortController()
    const to = window.setTimeout(() => ac.abort(), 15_000)
    try {
      const r = await fetch(`${apiBase()}/events/${encodeURIComponent(uid)}`, { signal: ac.signal })
      if (!r.ok) {
        setClipsError(`HTTP ${r.status}`)
        setCloudinaryClips([])
        return
      }
      const j = (await r.json()) as { events?: Record<string, unknown>[] }
      const list = j.events ?? []
      const withMedia = list
        .map((e) => {
          const id = String(e.event_id ?? '')
          const crop = (e.cropped_image_url as string | undefined) || null
          const cthumb = (e.cropped_thumb_url as string | undefined)?.trim() || null
          const raw = (e.raw_image_url as string | undefined) || null
          const vcz = parseVisionCropZone(e.vision_crop_zone)
          return {
            event_id: id,
            event_type: String(e.event_type ?? ''),
            severity: String(e.severity ?? ''),
            cropped_image_url: crop,
            cropped_thumb_url: cthumb,
            raw_image_url: raw,
            vision_crop_zone: vcz,
            detected_at: e.detected_at != null ? String(e.detected_at) : '',
          }
        })
        .filter(
          (e) =>
            (e.cropped_image_url || e.cropped_thumb_url || e.raw_image_url) && e.event_id,
        )
        .slice(0, 24)
      setCloudinaryClips(withMedia)
    } catch (e) {
      if (e instanceof Error && e.name === 'AbortError') {
        setClipsError('Request timed out — is uvicorn running on port 8000?')
      } else {
        setClipsError(e instanceof Error ? e.message : String(e))
      }
      setCloudinaryClips([])
    } finally {
      window.clearTimeout(to)
      setClipsLoading(false)
    }
  }, [userId])

  const fetchSnapshotGallery = useCallback(async () => {
    const uid = userId.trim()
    if (!uid) {
      setSnapshotGallery([])
      setSnapshotsLoading(false)
      return
    }
    setSnapshotsLoading(true)
    setSnapshotsError('')
    const ac = new AbortController()
    const to = window.setTimeout(() => ac.abort(), 15_000)
    try {
      const r = await fetch(`${apiBase()}/events/snapshots/${encodeURIComponent(uid)}`, {
        signal: ac.signal,
      })
      if (!r.ok) {
        setSnapshotsError(`HTTP ${r.status}`)
        setSnapshotGallery([])
        return
      }
      const j = (await r.json()) as {
        snapshots?: {
          snapshot_id: string
          url: string
          cropped_url: string
          cropped_thumb_url?: string
          source: string
          event_id: string | null
          event_type: string
          created_at: string
          vision_crop_zone?: unknown
        }[]
      }
      setSnapshotGallery(
        (j.snapshots ?? []).map((s) => ({
          ...s,
          vision_crop_zone: parseVisionCropZone(s.vision_crop_zone),
        })),
      )
    } catch (e) {
      if (e instanceof Error && e.name === 'AbortError') {
        setSnapshotsError('Request timed out — is uvicorn on port 8000?')
      } else {
        setSnapshotsError(e instanceof Error ? e.message : String(e))
      }
      setSnapshotGallery([])
    } finally {
      window.clearTimeout(to)
      setSnapshotsLoading(false)
    }
  }, [userId])

  useEffect(() => {
    if (tab !== 'console') return
    const boot = window.setTimeout(() => void fetchCloudinaryClips(), 0)
    const tick = setInterval(() => void fetchCloudinaryClips(), 45_000)
    return () => {
      window.clearTimeout(boot)
      clearInterval(tick)
    }
  }, [tab, fetchCloudinaryClips])

  useEffect(() => {
    if (tab !== 'console') return
    const boot = window.setTimeout(() => void fetchSnapshotGallery(), 0)
    const tick = setInterval(() => void fetchSnapshotGallery(), 30_000)
    return () => {
      window.clearTimeout(boot)
      clearInterval(tick)
    }
  }, [tab, fetchSnapshotGallery])

  useEffect(() => {
    if (tab !== 'console') return
    const boot = window.setTimeout(() => bumpBureauPreview(), 0)
    // ~2.5s: API reuses a sub-second frame cache so this stays light on the webcam lock.
    const tick = setInterval(bumpBureauPreview, 2500)
    return () => {
      window.clearTimeout(boot)
      clearInterval(tick)
    }
  }, [tab, bumpBureauPreview])

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
          if (msg.type === 'alert' && msg.data) {
            const data = msg.data as Record<string, unknown>
            const eventId = typeof data.event_id === 'string' ? data.event_id : ''
            const label = String(data.label || data.event_type || 'Alert')
            const severity = String(data.severity || 'MEDIUM').toUpperCase()
            const recommended = String(data.recommended_action || msg.text || '')
            const imageUrl = typeof data.image_url === 'string' ? data.image_url : undefined
            const imageThumb =
              typeof data.image_thumb_url === 'string' && data.image_thumb_url.trim()
                ? data.image_thumb_url.trim()
                : undefined
            const rawImg =
              typeof data.raw_image_url === 'string' && data.raw_image_url.trim()
                ? data.raw_image_url.trim()
                : undefined
            const vcz = parseVisionCropZone(data.vision_crop_zone)
            const time = new Date().toLocaleTimeString()
            setAlerts((prev) => {
              const id = eventId || `anon-${label}-${recommended.slice(0, 40)}`
              const next: LiveAlert = {
                id,
                label,
                severity,
                recommended_action: recommended,
                image_url: imageUrl,
                image_thumb_url: imageThumb,
                raw_image_url: rawImg,
                vision_crop_zone: vcz,
                time,
              }
              const without = prev.filter((a) => a.id !== id)
              return [next, ...without].slice(0, 6)
            })
            void fetchCloudinaryClips()
            void fetchSnapshotGallery()
            bumpBureauPreview()
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
  }, [fetchCloudinaryClips, fetchSnapshotGallery, bumpBureauPreview])

  const pushLog = useCallback((line: string) => {
    setLog((prev) => [...prev.slice(-80), `[${new Date().toLocaleTimeString()}] ${line}`])
  }, [])

  const saveSnapshotToMongo = useCallback(async () => {
    const uid = userId.trim()
    if (!uid) {
      pushLog('Set User ID to save snapshots to MongoDB.')
      return
    }
    setSavingSnapshot(true)
    try {
      const qs = new URLSearchParams({ user_id: uid })
      const r = await fetch(`${apiBase()}/sensor/preview-snapshot?${qs}`, { method: 'POST' })
      if (!r.ok) {
        const t = await r.text()
        let msg = t.slice(0, 400)
        try {
          const j = JSON.parse(t) as { detail?: unknown }
          if (typeof j.detail === 'string') msg = j.detail
        } catch {
          /* plain text */
        }
        pushLog(`Save snapshot FAIL (${r.status}): ${msg}`)
        return
      }
      const j = (await r.json()) as { url?: string; snapshot_id?: string }
      pushLog(`Snapshot saved — Mongo id ${j.snapshot_id?.slice(-8) ?? '?'} (Cloudinary)`)
      void fetchSnapshotGallery()
    } catch (e) {
      pushLog(e instanceof Error ? e.message : String(e))
    } finally {
      setSavingSnapshot(false)
    }
  }, [userId, fetchSnapshotGallery, pushLog])

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
          <p style={{ margin: '0 0 6px' }}>
            <a href="#" style={{ color: '#0f766e', fontWeight: 600, fontSize: '0.9rem' }}>
              ← Main safety screen
            </a>
          </p>
          <h1>HomePulse — Dev console</h1>
          <p className="sub">
            Test FastAPI + agents: bureau camera preview (OpenCV → Cloudinary), alert clips from <code>/events</code>, search,
            patterns, incidents, caregiver Q&amp;A. Run API: <code>uvicorn app.main:app --reload --port 8000</code> ·
            Run agents: <code>python run_agents.py</code>
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
                      {(alert.image_thumb_url || alert.image_url) && (
                        <div style={{ marginTop: 8, maxWidth: '100%', borderRadius: 6, overflow: 'hidden' }}>
                          <CloudinaryDeliveryImage
                            src={alert.image_thumb_url || alert.image_url || ''}
                            alt={alert.label}
                            href={alert.image_url || alert.image_thumb_url}
                            maxChips={5}
                            imgStyle={{ maxHeight: 160, objectFit: 'cover' }}
                          />
                        </div>
                      )}
                      {alert.raw_image_url && alert.vision_crop_zone ? (
                        <FullFrameCropDetails rawUrl={alert.raw_image_url} zone={alert.vision_crop_zone} />
                      ) : null}
                    </div>
                  )
                })}
              </div>
            </section>
          )}

          <section className="card camera-card">
            <h2>
              Bureau camera preview
              {bureauPreviewUpdated && !bureauPreviewError ? (
                <span style={{ fontSize: '0.75rem', fontWeight: 400, color: '#22c55e', marginLeft: 8 }}>
                  ● OpenCV @ API
                </span>
              ) : null}
            </h2>
            <p className="hint">
              Live JPEG from <code>GET /sensor/preview-jpeg</code> (same camera as{' '}
              <code>live-frame-b64</code>). No Cloudinary needed for this tile. Keep <code>uvicorn</code> on :8000; if
              the webcam is busy elsewhere, set <code>WEBCAM_INDEX</code> or stop other camera apps.
            </p>
            {bureauPreviewError ? <p className="warn">{bureauPreviewError}</p> : null}
            <div className="btn-row" style={{ marginBottom: 8 }}>
              <button type="button" disabled={bureauPreviewLoading} onClick={bumpBureauPreview}>
                {bureauPreviewLoading ? 'Refreshing…' : 'Refresh now'}
              </button>
              <button
                type="button"
                disabled={savingSnapshot || !userId.trim()}
                title="Uses one upload slot (same pool as vision): trigger an investigating anomaly first, or you get HTTP 429. Dev API: ?force=true bypass."
                onClick={() => void saveSnapshotToMongo()}
              >
                {savingSnapshot ? 'Saving…' : 'Save snapshot to gallery'}
              </button>
            </div>
            {bureauPreviewUpdated ? (
              <p className="hint" style={{ marginTop: -4 }}>
                Last frame loaded: {bureauPreviewUpdated}
              </p>
            ) : null}
            <div className="camera-stage">
              <img
                key={bureauPreviewTick}
                src={bureauPreviewSrc}
                alt="Bureau camera preview"
                className="camera-feed-video"
                style={{ width: '100%', height: 'auto', display: 'block', objectFit: 'contain' }}
                onLoadStart={() => {
                  setBureauPreviewLoading(true)
                  setBureauPreviewError('')
                }}
                onLoad={() => {
                  setBureauPreviewLoading(false)
                  setBureauPreviewError('')
                  setBureauPreviewUpdated(new Date().toLocaleTimeString())
                }}
                onError={() => {
                  setBureauPreviewLoading(false)
                  setBureauPreviewError(
                    'Could not load camera preview — is uvicorn on port 8000? Check WEBCAM_INDEX, and that no other app has locked the camera (e.g. only one OpenCV consumer on Windows).',
                  )
                }}
              />
            </div>
          </section>

          <section className="card camera-card">
            <h2>Vision clips (Cloudinary)</h2>
            <p className="hint">
              After triage + vision, events get <code>cropped_image_url</code> (full delivery),{' '}
              <code>cropped_thumb_url</code> (width-limited for lists/email), and <code>raw_image_url</code>. Grid tiles prefer
              the thumb. Each tile <strong>decodes the delivery URL</strong> and shows compact transformation chips. Expand{' '}
              <strong>Full frame · crop region</strong> on events after monitor runs (stores <code>vision_crop_zone</code> in
              Mongo) to see the raw Cloudinary frame with the crop rectangle. Loaded from <code>GET /events/&#123;userId&#125;</code>.
            </p>
            {clipsError ? <p className="warn">{clipsError}</p> : null}
            <div className="btn-row" style={{ marginBottom: 8 }}>
              <button type="button" disabled={clipsLoading || !userId.trim()} onClick={() => void fetchCloudinaryClips()}>
                {clipsLoading ? 'Loading…' : 'Refresh clips'}
              </button>
            </div>
            {!userId.trim() ? (
              <p className="hint">Set User ID below to load clips.</p>
            ) : cloudinaryClips.length === 0 && !clipsLoading ? (
              <p className="hint">No events with images yet. Trigger the pipeline (simulate or Arduino) with valid Cloudinary in API <code>.env</code>.</p>
            ) : (
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
                  gap: 12,
                  marginTop: 8,
                }}
              >
                {cloudinaryClips.map((c) => {
                  const src = c.cropped_thumb_url || c.cropped_image_url || c.raw_image_url || ''
                  const fullHref = c.cropped_image_url || c.raw_image_url || src
                  const sev = SEV_COLORS[c.severity] ?? SEV_COLORS.MEDIUM
                  return (
                    <figure
                      key={c.event_id}
                      style={{
                        margin: 0,
                        border: `1px solid ${sev.border}`,
                        borderRadius: 8,
                        overflow: 'hidden',
                        background: sev.bg,
                      }}
                    >
                      {src ? (
                        <CloudinaryDeliveryImage
                          src={src}
                          alt={c.event_type}
                          href={fullHref}
                          maxChips={5}
                          minHeight={140}
                          imgStyle={{ width: '100%', height: 140, objectFit: 'cover' }}
                        />
                      ) : null}
                      <figcaption style={{ padding: '8px 10px', fontSize: '0.75rem', color: sev.text }}>
                        <strong>{c.event_type}</strong> · {c.severity}
                        <br />
                        <span className="mono" style={{ opacity: 0.85 }}>
                          {c.event_id.slice(-8)}
                        </span>
                        {c.detected_at ? (
                          <>
                            <br />
                            {c.detected_at}
                          </>
                        ) : null}
                        {c.raw_image_url && c.vision_crop_zone ? (
                          <FullFrameCropDetails
                            rawUrl={c.raw_image_url}
                            zone={c.vision_crop_zone}
                            summaryColor={sev.text}
                          />
                        ) : null}
                      </figcaption>
                    </figure>
                  )
                })}
              </div>
            )}
          </section>

          <section className="card camera-card">
            <h2>Snapshot gallery (MongoDB + Cloudinary)</h2>
            <p className="hint">
              Stored in <code>camera_snapshots</code> and listed via <code>GET /events/snapshots/&#123;userId&#125;</code>.
              Vision rows may include <strong>Full frame · crop region</strong> when <code>vision_crop_zone</code> was saved.
              Manual preview saves have no crop overlay.
            </p>
            {snapshotsError ? <p className="warn">{snapshotsError}</p> : null}
            <div className="btn-row" style={{ marginBottom: 8 }}>
              <button
                type="button"
                disabled={snapshotsLoading || !userId.trim()}
                onClick={() => void fetchSnapshotGallery()}
              >
                {snapshotsLoading ? 'Loading…' : 'Refresh gallery'}
              </button>
            </div>
            {!userId.trim() ? (
              <p className="hint">Set User ID below to load snapshots.</p>
            ) : snapshotGallery.length === 0 && !snapshotsLoading ? (
              <p className="hint">
                No snapshots yet. Use <strong>Save snapshot to gallery</strong> on the bureau preview, or run triage + vision
                with Cloudinary configured.
              </p>
            ) : (
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
                  gap: 12,
                  marginTop: 8,
                }}
              >
                {snapshotGallery.map((s) => {
                  const thumb = (s.cropped_thumb_url || s.cropped_url || s.url || '').trim()
                  const badgeBg = s.source === 'vision' ? '#1e3a5f' : '#3d3518'
                  const badgeFg = '#e8eef6'
                  return (
                    <figure
                      key={s.snapshot_id}
                      style={{
                        margin: 0,
                        border: '1px solid var(--border, #333)',
                        borderRadius: 8,
                        overflow: 'hidden',
                        background: 'var(--card-inner, #1a1a1a)',
                      }}
                    >
                      {thumb ? (
                        <CloudinaryDeliveryImage
                          src={thumb}
                          alt={s.event_type || s.source}
                          href={s.cropped_url || s.url || thumb}
                          maxChips={5}
                          minHeight={140}
                          imgStyle={{ width: '100%', height: 140, objectFit: 'cover' }}
                        />
                      ) : null}
                      {!thumb ? (
                        <div style={{ height: 140, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.8rem', opacity: 0.7 }}>
                          No image URL
                        </div>
                      ) : null}
                      <figcaption
                        style={{
                          padding: '8px 10px',
                          fontSize: '0.75rem',
                          color: '#e2e8f0',
                          background: 'rgba(15, 23, 42, 0.92)',
                        }}
                      >
                        <span
                          style={{
                            display: 'inline-block',
                            padding: '2px 8px',
                            borderRadius: 4,
                            background: badgeBg,
                            color: badgeFg,
                            fontSize: '0.7rem',
                            marginBottom: 6,
                          }}
                        >
                          {s.source}
                        </span>
                        <br />
                        <strong style={{ color: '#f8fafc' }}>{s.event_type || '—'}</strong>
                        <br />
                        <span className="mono" style={{ opacity: 0.9, color: '#cbd5e1' }}>
                          {s.snapshot_id.slice(-8)}
                        </span>
                        {s.event_id ? (
                          <>
                            <br />
                            <span className="mono" style={{ opacity: 0.85, color: '#94a3b8' }}>
                              evt {s.event_id.slice(-8)}
                            </span>
                          </>
                        ) : null}
                        {s.created_at ? (
                          <>
                            <br />
                            <span style={{ color: '#94a3b8' }}>{s.created_at}</span>
                          </>
                        ) : null}
                        {s.url && s.vision_crop_zone ? (
                          <FullFrameCropDetails
                            rawUrl={s.url.trim()}
                            zone={s.vision_crop_zone}
                            summaryColor="#94a3b8"
                          />
                        ) : null}
                      </figcaption>
                    </figure>
                  )
                })}
              </div>
            )}
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
