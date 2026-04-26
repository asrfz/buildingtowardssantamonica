import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { CloudinaryPlayground } from '../components/CloudinaryPlayground'
import { CloudinaryAmplifyPanel } from '../components/CloudinaryAmplifyPanel'
import { DemoHazardFeed } from '../components/DemoHazardFeed'
import { ZoomableAnomalyView } from '../components/ZoomableAnomalyView'
import { apiBase, apiJson } from '../lib/api'
import { decodeCloudinaryDeliveryUrl, compactChipLabel, type DecodedCloudinaryDelivery } from '../lib/cloudinaryDecode'
import { FORCE_LOUD_NOISE, PRESETS, simulateBody } from '../lib/payloads'
import { parseVisionCropZone } from '../lib/visionCropZone'

const USER_STORAGE = 'homepulse_dev_user_id'

type EventRow = {
  event_id: string
  event_type: string
  event_label?: string
  severity: string
  recommended_action?: string
  deviation_score?: number
  raw_image_url?: string | null
  cropped_image_url?: string | null
  cropped_thumb_url?: string | null
  vision_crop_zone?: unknown
  detected_at?: string
}

function initialUserId(): string {
  const saved = localStorage.getItem(USER_STORAGE)?.trim()
  if (saved) return saved
  return import.meta.env.VITE_DEFAULT_USER_ID?.trim() || ''
}

function shortAction(text: string): string[] {
  const t = text.replace(/\s+/g, ' ').trim()
  if (!t) return []
  const parts = t.split(/(?<=[.!?])\s+/).filter(Boolean)
  const out = parts.slice(0, 3).map((p) => (p.length > 72 ? `${p.slice(0, 70)}…` : p))
  return out.length ? out : [t.length > 100 ? `${t.slice(0, 98)}…` : t]
}

function timeAgo(iso?: string): string {
  if (!iso) return ''
  const d = new Date(iso).getTime()
  if (Number.isNaN(d)) return ''
  const sec = Math.floor((Date.now() - d) / 1000)
  if (sec < 45) return 'Just now'
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`
  return `${Math.floor(sec / 86400)}d ago`
}

function formatFeedClock(iso?: string): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  const pad = (n: number) => n.toString().padStart(2, '0')
  const ms = d.getMilliseconds().toString().padStart(3, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.${ms}`
}

function confFromDeviation(score?: number): string | null {
  if (score == null || Number.isNaN(score)) return null
  const pct = Math.min(99.9, Math.max(55, 72 + score * 2.2))
  return `${pct.toFixed(1)}%`
}

function notifyBody(text?: string): string {
  if (!text?.trim()) return 'No extra detail for this alert.'
  const first = text.split(/(?<=[.!?])\s+/).filter(Boolean)[0] ?? text
  return first.length > 180 ? `${first.slice(0, 178)}…` : first
}

function recentTone(eventType: string): 'red' | 'orange' | 'blue' | 'purple' | 'yellow' | 'gray' {
  const t = eventType.toUpperCase()
  if (t.includes('FALL')) return 'red'
  if (t.includes('TEMP') || t.includes('HEAT') || t.includes('STOVE') || t.includes('FIRE')) return 'orange'
  if (t.includes('MOTION')) return 'blue'
  if (t.includes('SOUND') || t.includes('NOISE')) return 'purple'
  if (t.includes('LIGHT')) return 'yellow'
  if (t.includes('MOVEMENT')) return 'gray'
  return 'gray'
}

function hazardPillLabel(e: EventRow): string {
  const raw = (e.event_label || e.event_type || 'Alert').replace(/_/g, ' ')
  return raw.toUpperCase()
}

/** Merge monitor_agent WebSocket alert so Cloudinary URLs + crop show before the next GET /events. */
function mergeAlertIntoEvents(prev: EventRow[], data: Record<string, unknown>): EventRow[] {
  const event_id = String(data.event_id ?? '')
  if (!event_id) return prev
  const cropped =
    (typeof data.image_url === 'string' && data.image_url.trim()) ||
    (typeof data.cropped_image_url === 'string' && data.cropped_image_url.trim()) ||
    null
  const thumb =
    (typeof data.image_thumb_url === 'string' && data.image_thumb_url.trim()) ||
    (typeof data.cropped_thumb_url === 'string' && data.cropped_thumb_url.trim()) ||
    null
  const raw =
    (typeof data.raw_image_url === 'string' && data.raw_image_url.trim()) || null
  const row: EventRow = {
    event_id,
    event_type: String(data.event_type ?? 'ALERT'),
    event_label: typeof data.label === 'string' ? data.label : undefined,
    severity: String(data.severity ?? 'MEDIUM'),
    recommended_action:
      typeof data.recommended_action === 'string' ? data.recommended_action : undefined,
    deviation_score: typeof data.deviation_score === 'number' ? data.deviation_score : undefined,
    raw_image_url: raw,
    cropped_image_url: cropped,
    cropped_thumb_url: thumb,
    vision_crop_zone: data.vision_crop_zone,
    detected_at: new Date().toISOString(),
  }
  const rest = prev.filter((e) => e.event_id !== event_id)
  return [row, ...rest].slice(0, 80)
}

/** Prefer non-empty URL / valid crop from either source (WS often arrives before Mongo lists images). */
function enrichEventFromPrev(api: EventRow, prev?: EventRow): EventRow {
  if (!prev) return api
  const pickUrl = (a: string | null | undefined, b: string | null | undefined) => {
    const x = (a || '').trim()
    const y = (b || '').trim()
    return x || y || null
  }
  const zoneApi = parseVisionCropZone(api.vision_crop_zone)
  const zonePrev = parseVisionCropZone(prev.vision_crop_zone)
  return {
    ...api,
    deviation_score: api.deviation_score ?? prev.deviation_score,
    raw_image_url: pickUrl(api.raw_image_url, prev.raw_image_url),
    cropped_image_url: pickUrl(api.cropped_image_url, prev.cropped_image_url),
    cropped_thumb_url: pickUrl(api.cropped_thumb_url, prev.cropped_thumb_url),
    vision_crop_zone: zoneApi ? api.vision_crop_zone : zonePrev ? prev.vision_crop_zone : api.vision_crop_zone,
  }
}

/** Combine GET /events with prior state so in-flight alerts and image URLs are not wiped. */
function mergeFetchedEventsWithPrev(prev: EventRow[], fetched: EventRow[]): EventRow[] {
  const prevById = new Map(prev.map((e) => [e.event_id, e]))
  const fetchedIds = new Set(fetched.map((e) => e.event_id))
  const mergedFromApi = fetched.map((r) => enrichEventFromPrev(r, prevById.get(r.event_id)))
  const pendingOnly = prev.filter((e) => e.event_id && !fetchedIds.has(e.event_id))
  return [...pendingOnly, ...mergedFromApi].slice(0, 80)
}

type LiveTelemetry = {
  arduino_serial_enabled: boolean
  arduino_serial_port: string
  serial_gave_up: boolean
  from_agent: { payload: Record<string, unknown>; updated_at: string } | null
  from_api_inject: { payload: Record<string, unknown>; monotonic_ts: number } | null
  shadow_source_note?: string
}

type SnapshotRow = {
  snapshot_id: string
  url: string
  cropped_url: string
  cropped_thumb_url?: string
  source: string
  event_id: string | null
  event_type: string
  created_at: string
  vision_crop_zone?: unknown
}

const DEMO_RECENT = [
  { key: 'd1', label: 'Fall Risk', tone: 'red' as const, ago: '2m ago' },
  { key: 'd2', label: 'Temp Spike', tone: 'orange' as const, ago: '1h ago' },
  { key: 'd3', label: 'Motion', tone: 'blue' as const, ago: '3h ago' },
  { key: 'd4', label: 'Sound', tone: 'purple' as const, ago: '5h ago' },
  { key: 'd5', label: 'Low Light', tone: 'yellow' as const, ago: '8h ago' },
  { key: 'd6', label: 'Movement', tone: 'gray' as const, ago: '12h ago' },
]

const DEFAULT_VOICE_STEPS = [
  'Use an alternate path — walk around the affected area.',
  'Call for help if needed — your caregiver can assist.',
  'Secure the area when safe — move items against the wall.',
]

export default function HomePulseDashboard() {
  const [userId, setUserId] = useState(initialUserId)
  const [events, setEvents] = useState<EventRow[]>([])
  const [loading, setLoading] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [zoom, setZoom] = useState(1)
  const [wsOk, setWsOk] = useState(false)
  const [searchQ, setSearchQ] = useState('')
  const [searchSeverity, setSearchSeverity] = useState('')
  const [searchDays, setSearchDays] = useState('')
  const [searchKind, setSearchKind] = useState<'events' | 'incidents'>('events')
  const [searchBusy, setSearchBusy] = useState(false)
  const [searchHits, setSearchHits] = useState<Record<string, unknown>[]>([])
  const [patternsNote, setPatternsNote] = useState('')
  const [patternsBusy, setPatternsBusy] = useState(false)
  const [showPhotoLab, setShowPhotoLab] = useState(false)
  const [showTools, setShowTools] = useState(false)
  const [nowTick, setNowTick] = useState(() => Date.now())
  const viteCloud = import.meta.env.VITE_CLOUDINARY_CLOUD_NAME?.trim() || ''
  const [telemetry, setTelemetry] = useState<LiveTelemetry | null>(null)
  const [snapshots, setSnapshots] = useState<SnapshotRow[]>([])
  const [bureauTick, setBureauTick] = useState(() => Date.now())
  const [bureauErr, setBureauErr] = useState('')
  const [simulateBusy, setSimulateBusy] = useState(false)
  const [sensorPulse, setSensorPulse] = useState(false)

  useEffect(() => {
    const id = window.setInterval(() => setNowTick(Date.now()), 200)
    return () => clearInterval(id)
  }, [])

  const loadEvents = useCallback(async () => {
    const uid = userId.trim()
    if (!uid) {
      setEvents([])
      return
    }
    setLoading(true)
    try {
      const r = await fetch(`${apiBase()}/events/${encodeURIComponent(uid)}`)
      if (!r.ok) {
        setEvents([])
        return
      }
      const j = (await r.json()) as { events?: Record<string, unknown>[] }
      const rows: EventRow[] = (j.events ?? []).map((e) => ({
        event_id: String(e.event_id ?? ''),
        event_type: String(e.event_type ?? ''),
        event_label: typeof e.event_label === 'string' ? e.event_label : undefined,
        severity: String(e.severity ?? ''),
        recommended_action: typeof e.recommended_action === 'string' ? e.recommended_action : undefined,
        deviation_score: typeof e.deviation_score === 'number' ? e.deviation_score : undefined,
        raw_image_url: (e.raw_image_url as string) || null,
        cropped_image_url: (e.cropped_image_url as string) || null,
        cropped_thumb_url: (e.cropped_thumb_url as string) || null,
        vision_crop_zone: e.vision_crop_zone,
        detected_at: e.detected_at != null ? String(e.detected_at) : undefined,
      }))
      setEvents((prev) => {
        const merged = mergeFetchedEventsWithPrev(prev, rows)
        setSelectedId((cur) => {
          if (cur && merged.some((x) => x.event_id === cur)) return cur
          const withImg = merged.find((x) => x.raw_image_url && parseVisionCropZone(x.vision_crop_zone))
          const withAnyImg = merged.find((x) => x.raw_image_url || x.cropped_image_url)
          return withImg?.event_id ?? withAnyImg?.event_id ?? merged[0]?.event_id ?? null
        })
        return merged
      })
    } finally {
      setLoading(false)
    }
  }, [userId])

  const loadSnapshots = useCallback(async () => {
    const uid = userId.trim()
    if (!uid) {
      setSnapshots([])
      return
    }
    try {
      const r = await fetch(`${apiBase()}/events/snapshots/${encodeURIComponent(uid)}?limit=8`)
      if (!r.ok) {
        setSnapshots([])
        return
      }
      const j = (await r.json()) as { snapshots?: SnapshotRow[] }
      setSnapshots(j.snapshots ?? [])
    } catch {
      setSnapshots([])
    }
  }, [userId])

  const loadTelemetry = useCallback(async () => {
    const uid = userId.trim()
    if (!uid) {
      setTelemetry(null)
      return
    }
    try {
      const r = await fetch(`${apiBase()}/sensor/live-telemetry/${encodeURIComponent(uid)}`)
      if (!r.ok) {
        setTelemetry(null)
        return
      }
      const j = (await r.json()) as LiveTelemetry
      setTelemetry(j)
    } catch {
      setTelemetry(null)
    }
  }, [userId])

  useEffect(() => {
    localStorage.setItem(USER_STORAGE, userId)
  }, [userId])

  useEffect(() => {
    const saved = localStorage.getItem(USER_STORAGE)?.trim()
    const vite = import.meta.env.VITE_DEFAULT_USER_ID?.trim()
    if (saved || vite) return
    let cancelled = false
    void (async () => {
      try {
        const r = await fetch(`${apiBase()}/integration/dev-context`)
        if (!r.ok || cancelled) return
        const j = (await r.json()) as { default_user_id?: string }
        const id = j.default_user_id?.trim()
        if (id && !cancelled) setUserId(id)
      } catch {
        /* */
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    const boot = window.setTimeout(() => void loadEvents(), 0)
    return () => window.clearTimeout(boot)
  }, [loadEvents])

  const bump = useCallback(() => {
    void loadEvents()
    void loadSnapshots()
    void loadTelemetry()
  }, [loadEvents, loadSnapshots, loadTelemetry])

  const bumpRef = useRef(bump)
  useEffect(() => {
    bumpRef.current = bump
  }, [bump])

  useEffect(() => {
    const base = apiBase().replace(/^http/, 'ws')
    const url = `${base}/voice/ws`
    let stopped = false
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null
    let socket: WebSocket | null = null

    const connect = () => {
      if (stopped) return
      socket = new WebSocket(url)
      socket.onopen = () => {
        if (!stopped) setWsOk(true)
      }
      socket.onmessage = (ev) => {
        let alertRefresh = false
        try {
          const msg = JSON.parse(ev.data) as { type?: string; data?: Record<string, unknown> }
          if (msg.type === 'alert' && msg.data && typeof msg.data.event_id === 'string') {
            setEvents((prev) => mergeAlertIntoEvents(prev, msg.data!))
            setSelectedId(String(msg.data.event_id))
            setZoom(1)
            setBureauTick(Date.now())
            alertRefresh = true
          }
        } catch {
          /* ignore */
        }
        if (alertRefresh) bumpRef.current()
      }
      socket.onclose = () => {
        socket = null
        if (!stopped) setWsOk(false)
        if (!stopped) reconnectTimer = window.setTimeout(connect, 2000)
      }
      socket.onerror = () => socket?.close()
    }

    connect()
    return () => {
      stopped = true
      if (reconnectTimer) window.clearTimeout(reconnectTimer)
      socket?.close()
    }
  }, [])

  useEffect(() => {
    const uid = userId.trim()
    if (!uid) return
    const serialLive = Boolean(telemetry?.arduino_serial_enabled && !telemetry?.serial_gave_up)
    const ms = serialLive ? 5_000 : 25_000
    const id = window.setInterval(() => void loadEvents(), ms)
    return () => clearInterval(id)
  }, [userId, loadEvents, telemetry?.arduino_serial_enabled, telemetry?.serial_gave_up])

  useEffect(() => {
    const boot = window.setTimeout(() => void loadTelemetry(), 0)
    const id = window.setInterval(() => void loadTelemetry(), 1500)
    return () => {
      window.clearTimeout(boot)
      clearInterval(id)
    }
  }, [loadTelemetry])

  useEffect(() => {
    const boot = window.setTimeout(() => void loadSnapshots(), 0)
    return () => window.clearTimeout(boot)
  }, [loadSnapshots])

  useEffect(() => {
    const id = window.setInterval(() => setBureauTick(Date.now()), 2500)
    return () => clearInterval(id)
  }, [])

  const queueTestPipeline = useCallback(async () => {
    setSimulateBusy(true)
    try {
      await fetch(`${apiBase()}/sensor/simulate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: simulateBody(PRESETS.loudNoise(), FORCE_LOUD_NOISE),
      })
      window.setTimeout(() => bump(), 800)
    } finally {
      setSimulateBusy(false)
    }
  }, [bump])

  const selected = useMemo(
    () => events.find((e) => e.event_id === selectedId) ?? null,
    [events, selectedId],
  )

  const zone = useMemo(() => parseVisionCropZone(selected?.vision_crop_zone), [selected?.vision_crop_zone])
  const rawUrl = (selected?.raw_image_url || '').trim()
  const croppedUrl = (selected?.cropped_image_url || '').trim()
  const decodeCrop: DecodedCloudinaryDelivery | null = useMemo(
    () => (croppedUrl ? decodeCloudinaryDeliveryUrl(croppedUrl) : null),
    [croppedUrl],
  )
  const decodeRawMeta = useMemo(() => (rawUrl ? decodeCloudinaryDeliveryUrl(rawUrl) : null), [rawUrl])
  const publicIdForCld = decodeRawMeta?.publicId || decodeCrop?.publicId || ''
  const cloudForCld = viteCloud || decodeRawMeta?.cloudName || decodeCrop?.cloudName || ''

  const runSearch = useCallback(async () => {
    const q = searchQ.trim()
    const uid = userId.trim()
    if (!q || !uid) return
    setSearchBusy(true)
    setSearchHits([])
    try {
      const enc = encodeURIComponent(q)
      const uidQ = encodeURIComponent(uid)
      if (searchKind === 'events') {
        const qs = new URLSearchParams({ q, user_id: uid, limit: '15' })
        const sev = searchSeverity.trim().toUpperCase()
        if (sev) qs.set('severity', sev)
        const daysN = parseInt(searchDays.trim(), 10)
        if (!Number.isNaN(daysN) && daysN > 0) qs.set('days', String(daysN))
        const { ok, data } = await apiJson<{ results?: Record<string, unknown>[] }>(
          `/search/events?${qs.toString()}`,
        )
        if (ok && data?.results) setSearchHits(data.results)
      } else {
        const { ok, data } = await apiJson<{ results?: Record<string, unknown>[] }>(
          `/search/incidents?q=${enc}&user_id=${uidQ}&limit=12`,
        )
        if (ok && data?.results) setSearchHits(data.results)
      }
    } finally {
      setSearchBusy(false)
    }
  }, [searchQ, userId, searchKind, searchSeverity, searchDays])

  const runPatterns = useCallback(async () => {
    const uid = userId.trim()
    if (!uid) return
    setPatternsBusy(true)
    setPatternsNote('')
    try {
      const { ok, data } = await apiJson<Record<string, unknown>>(`/search/patterns/${encodeURIComponent(uid)}`)
      if (ok && data) {
        const freq = data.event_frequency as { event_type?: string; count?: number }[] | undefined
        const bits = (freq ?? []).slice(0, 4).map(
          (t) => `${(t.event_type ?? '?').replace(/_/g, ' ')} (${t.count ?? 0})`,
        )
        setPatternsNote(bits.length ? bits.join(' · ') : 'No pattern data yet.')
      } else setPatternsNote('Could not load summary.')
    } finally {
      setPatternsBusy(false)
    }
  }, [userId])

  const conf = confFromDeviation(selected?.deviation_score)
  const riskLabel = selected?.severity ? selected.severity.toUpperCase() : '—'
  const hasLiveCrop = Boolean(rawUrl && zone)
  /** Main hero matches sidebar: no fake “hazard” when nothing is selected. */
  const idleMain = !selected
  const displayConf = conf
  const displayRisk = riskLabel

  const notifyTitle = selected
    ? `${(selected.event_label || selected.event_type.replace(/_/g, ' ')).replace(/^\w/, (c) => c.toUpperCase())} detected nearby`
    : 'All clear for now'

  const notifyDescription = selected
    ? notifyBody(selected.recommended_action)
    : loading
      ? 'Loading your latest status…'
      : "We're monitoring your home. When something needs attention, a clear note will appear here — like the trip hazard example in our safety layout."

  const voiceImmediate = selected?.recommended_action
    ? `Immediate action: ${shortAction(selected.recommended_action)[0] ?? 'Stay safe and move carefully.'}`
    : 'Immediate action: No hazard is active — relax and move at your usual pace.'

  const voiceSteps = (() => {
    if (!selected?.recommended_action) return DEFAULT_VOICE_STEPS
    const lines = shortAction(selected.recommended_action)
    return lines.length > 1 ? lines.slice(1, 4) : DEFAULT_VOICE_STEPS
  })()

  const demoHazardText = selected ? hazardPillLabel(selected) : ''
  const feedClock = selected?.detected_at
    ? formatFeedClock(selected.detected_at)
    : formatFeedClock(new Date(nowTick).toISOString())

  const livePayload = useMemo(() => {
    const a = telemetry?.from_agent?.payload
    const b = telemetry?.from_api_inject?.payload
    return (a && typeof a === 'object' ? a : null) ?? (b && typeof b === 'object' ? b : null)
  }, [telemetry])

  const prevTrigRef = useRef<{ motion: number; sound: number } | null>(null)
  useEffect(() => {
    if (!livePayload) return
    const motion = Number(livePayload.motion_triggered ?? 0)
    const sound = Number(livePayload.sound_triggered ?? 0)
    const prev = prevTrigRef.current
    prevTrigRef.current = { motion, sound }
    if (prev == null) return
    if (motion > prev.motion || sound > prev.sound) {
      bumpRef.current()
      setSensorPulse(true)
      const t = window.setTimeout(() => setSensorPulse(false), 900)
      return () => window.clearTimeout(t)
    }
  }, [livePayload])

  return (
    <div className="hp-shell">
      <aside className="hp-sidebar">
        <div className="hp-brand">HomePulse</div>
        <label className="hp-label">Your home ID</label>
        <input
          className="hp-input"
          value={userId}
          onChange={(e) => setUserId(e.target.value.trim())}
          placeholder="Paste ID from your caregiver"
          autoComplete="off"
        />
        <p className="hp-hint">{wsOk ? '● Live link' : 'Connecting…'}</p>

        <div className="hp-notify-card">
          <div className="hp-notify-head">
            <span className="hp-notify-icon" aria-hidden>
              i
            </span>
            <div className="hp-notify-title">{notifyTitle}</div>
          </div>
          <p className="hp-notify-body">{notifyDescription}</p>
          <div className="hp-notify-meta">
            <span className="hp-notify-pill">Living room area</span>
            <span className="hp-notify-time">{selected?.detected_at ? timeAgo(selected.detected_at) : 'Just now'}</span>
          </div>
        </div>

        <div className="hp-voice-panel">
          <div className="hp-voice-title">
            <span className="hp-voice-dot" aria-hidden />
            Voice Agent - What To Do
          </div>
          <div className="hp-voice-immediate">{voiceImmediate}</div>
          <p className="hp-voice-quick-label">Quick steps to stay safe:</p>
          <ol className="hp-voice-steps-num">
            {voiceSteps.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ol>
        </div>

        <div className="hp-live-panel">
          <div className="hp-live-title">Arduino / sensors</div>
          {telemetry ? (
            <>
              <p className="hp-live-meta">
                Serial {telemetry.arduino_serial_enabled ? 'enabled' : 'disabled'}
                {telemetry.arduino_serial_port ? ` · ${telemetry.arduino_serial_port}` : ''}
                {telemetry.serial_gave_up ? ' · COM port busy (close other apps or restart agents)' : ''}
              </p>
              {livePayload ? (
                <ul className="hp-live-metrics">
                  <li>
                    <strong>Sound</strong> {String(livePayload.sound_level ?? '—')}
                  </li>
                  <li>
                    <strong>Light</strong>{' '}
                    {livePayload.light_level != null ? String(livePayload.light_level) : '—'}
                  </li>
                  <li>
                    <strong>Triggers</strong> motion {String(livePayload.motion_triggered ?? 0)} · sound{' '}
                    {String(livePayload.sound_triggered ?? 0)} · light Δ {String(livePayload.light_change_detected ?? 0)}
                  </li>
                  <li>
                    <strong>Motion mag</strong> {String(livePayload.accel_z ?? livePayload.accel ?? '—')}
                  </li>
                </ul>
              ) : (
                <p className="hp-live-wait">No reading yet — plug in the board and run sensor_agent, or queue a test below.</p>
              )}
              {telemetry.from_agent?.updated_at ? (
                <p className="hp-live-ts">sensor_agent · {timeAgo(telemetry.from_agent.updated_at)}</p>
              ) : null}
              {telemetry.shadow_source_note ? (
                <p className="hp-live-hint">{telemetry.shadow_source_note}</p>
              ) : null}
            </>
          ) : (
            <p className="hp-live-wait">Connect to the API to see live values.</p>
          )}
        </div>

        <div className="hp-bureau-card">
          <div className="hp-bureau-head">Bureau camera</div>
          {bureauErr ? <p className="hp-bureau-err">{bureauErr}</p> : null}
          <img
            src={`${apiBase()}/sensor/preview-jpeg?t=${bureauTick}`}
            alt=""
            className="hp-bureau-img"
            onLoad={() => setBureauErr('')}
            onError={() =>
              setBureauErr('No webcam preview — start uvicorn on :8000 with a camera, or ignore for Arduino-only.')
            }
          />
          <button type="button" className="hp-btn hp-btn-outline hp-btn-compact" onClick={() => setBureauTick(Date.now())}>
            Refresh frame
          </button>
        </div>

        <button
          type="button"
          className="hp-btn hp-btn-side hp-btn-outline"
          disabled={simulateBusy}
          onClick={() => void queueTestPipeline()}
        >
          {simulateBusy ? 'Queuing…' : 'Queue demo anomaly (full pipeline)'}
        </button>

        <button type="button" className="hp-btn hp-btn-side" onClick={() => setShowPhotoLab((v) => !v)}>
          {showPhotoLab ? 'Hide Cloudinary lab' : 'Cloudinary photo lab'}
        </button>
        <a className="hp-btn hp-btn-side hp-btn-outline hp-link-btn" href="#dev">
          Developer testing
        </a>
        <button type="button" className="hp-btn hp-btn-side hp-btn-outline" onClick={() => setShowTools((v) => !v)}>
          {showTools ? 'Hide note' : 'About'}
        </button>
      </aside>

      <main className="hp-main">
        <header className="hp-analysis-head">
          <div>
            <h1 className="hp-title">AI-Enhanced Hazard Analysis</h1>
            <p className="hp-sub">Live or sample frame — Cloudinary crop, sharpen, and delivery.</p>
          </div>
          <span className="hp-cloudinary-mark">CLOUDINARY ENHANCED</span>
        </header>

        {livePayload ? (
          <div
            className={`hp-main-live ${sensorPulse ? 'hp-main-live--pulse' : ''}`}
            role="status"
            aria-live="polite"
          >
            <div className="hp-main-live-row">
              <strong>Live sensors</strong>
              <span className="hp-main-live-hint">Arduino / serial and simulate feed the same monitor pipeline — new triggers refresh alerts below.</span>
            </div>
            <div className="hp-main-live-metrics">
              <span>Sound {String(livePayload.sound_level ?? '—')}</span>
              <span>Light {livePayload.light_level != null ? String(livePayload.light_level) : '—'}</span>
              <span>
                Triggers motion {String(livePayload.motion_triggered ?? 0)} · sound {String(livePayload.sound_triggered ?? 0)}
              </span>
              <span>Δ light {String(livePayload.light_change_detected ?? 0)}</span>
            </div>
          </div>
        ) : null}

        <div
          className={`hp-feed-stage ${sensorPulse ? 'hp-feed-stage--pulse' : ''} ${idleMain ? 'hp-feed-stage--idle' : ''}`}
        >
          {idleMain ? (
            <div className="hp-status-float hp-status-float--clear" aria-live="polite">
              <div className="hp-status-line">
                <span className="hp-status-dot hp-status-dot--calm" />
                <strong>MONITORING</strong>
              </div>
              <div className="hp-status-metric">No active alert — same status as the panel on the left.</div>
            </div>
          ) : (
            <div className="hp-status-float hp-status-float--mock" aria-live="polite">
              <div className="hp-status-line">
                <span className="hp-status-dot" />
                <strong>HAZARD DETECTED</strong>
              </div>
              {displayConf ? <div className="hp-status-metric">CONF: {displayConf}</div> : null}
              <div className="hp-status-metric">RISK: {displayRisk}</div>
            </div>
          )}

          {idleMain ? (
            <div className="hp-idle-feed">
              <div className="hp-notify-card hp-idle-feed-hero">
                <div className="hp-notify-head">
                  <span className="hp-notify-icon" aria-hidden>
                    i
                  </span>
                  <div className="hp-notify-title">{notifyTitle}</div>
                </div>
                <p className="hp-notify-body">{notifyDescription}</p>
                <div className="hp-notify-meta">
                  <span className="hp-notify-pill">Living room area</span>
                  <span className="hp-notify-time">{loading ? 'Loading…' : 'Standby'}</span>
                </div>
              </div>
              <p className="hp-idle-feed-sub">
                When the pipeline saves a frame, the enhanced feed and crop appear here automatically — no mock hazard
                overlay unless you open a real alert below.
              </p>
            </div>
          ) : hasLiveCrop ? (
            <div className="hp-zoom-bar">
              <span className="hp-zoom-label">Zoom (focus on box)</span>
              <button type="button" className="hp-btn hp-btn-dark" onClick={() => setZoom((z) => Math.max(1, Math.round((z - 0.25) * 100) / 100))}>
                −
              </button>
              <button type="button" className="hp-btn hp-btn-dark" onClick={() => setZoom(1)}>
                Reset
              </button>
              <button type="button" className="hp-btn hp-btn-dark" onClick={() => setZoom((z) => Math.min(2.25, Math.round((z + 0.25) * 100) / 100))}>
                +
              </button>
            </div>
          ) : null}

          {hasLiveCrop && zone ? (
            <ZoomableAnomalyView
              rawUrl={rawUrl}
              zone={zone}
              zoom={zoom}
              shortLabel={selected?.event_label || selected?.event_type || 'Alert'}
              hazardLabel={selected ? hazardPillLabel(selected) : demoHazardText}
            />
          ) : selected && rawUrl ? (
            <>
              <p className="hp-feed-caption">Photo from this alert — crop box appears when vision saves coordinates.</p>
              <img src={rawUrl} alt="" className="hp-fallback-img" />
            </>
          ) : selected ? (
            <DemoHazardFeed hazardLabel={demoHazardText || 'ALERT'} />
          ) : null}

          <div className="hp-feed-clock">{feedClock}</div>
        </div>

        {decodeCrop && decodeCrop.chips.length > 0 ? (
          <div className="hp-strip" aria-label="Cloudinary adjustments on cropped image">
            <span className="hp-strip-title">Delivery chain</span>
            {decodeCrop.chips.slice(0, 8).map((c) => (
              <span key={c.id} className="hp-chip" title={c.label}>
                {compactChipLabel(c)}
              </span>
            ))}
          </div>
        ) : null}

        {selected && (selected.cropped_thumb_url || selected.cropped_image_url) ? (
          <section className="hp-cld-delivery">
            <h2 className="hp-h2">This alert — Cloudinary crop (delivery URL)</h2>
            <p className="hp-muted-main hp-tight">Thumb is width-limited; open full crop in a new tab.</p>
            <a
              className="hp-cld-delivery-link"
              href={selected.cropped_image_url || selected.cropped_thumb_url || '#'}
              target="_blank"
              rel="noreferrer"
            >
              <img
                src={(selected.cropped_thumb_url || selected.cropped_image_url) as string}
                alt=""
                className="hp-cld-thumb"
              />
            </a>
          </section>
        ) : null}

        {viteCloud && publicIdForCld && cloudForCld === viteCloud ? (
          <CloudinaryAmplifyPanel cloudName={viteCloud} publicId={publicIdForCld} />
        ) : viteCloud && selected?.event_id ? (
          <section className="hp-cld-block">
            <h2 className="hp-h2">Cloudinary</h2>
            <p className="hp-muted-main hp-tight">
              This alert has no raw Cloudinary <code className="hp-code">public_id</code> yet — open an event with a stored raw image URL, or run the full pipeline once.
            </p>
          </section>
        ) : null}

        {snapshots.length > 0 ? (
          <section className="hp-snapshots">
            <div className="hp-recent-head">
              <h2 className="hp-h2">Saved camera frames</h2>
              <span className="hp-recent-range">MongoDB + Cloudinary</span>
            </div>
            <div className="hp-snap-scroll">
              {snapshots.map((s) => (
                <button
                  key={s.snapshot_id}
                  type="button"
                  className="hp-snap-tile"
                  onClick={() => {
                    if (s.event_id) {
                      setSelectedId(s.event_id)
                      setZoom(1)
                    }
                  }}
                >
                  <img src={s.cropped_thumb_url || s.cropped_url || s.url} alt="" className="hp-snap-thumb" />
                  <span className="hp-snap-cap">{(s.event_type || s.source).replace(/_/g, ' ')}</span>
                </button>
              ))}
            </div>
          </section>
        ) : null}

        <section className="hp-recent">
          <div className="hp-recent-head">
            <h2 className="hp-h2">Recent Alerts</h2>
            <span className="hp-recent-range">last 24h</span>
          </div>
          <div className="hp-recent-row">
            {events.length > 0
              ? events.slice(0, 12).map((e) => (
                  <button
                    key={e.event_id}
                    type="button"
                    className={`hp-pill hp-pill--${recentTone(e.event_type)} ${e.event_id === selectedId ? 'active' : ''}`}
                    onClick={() => {
                      setSelectedId(e.event_id)
                      setZoom(1)
                    }}
                  >
                    <span className="hp-pill-icon" aria-hidden />
                    <span className="hp-pill-label">{(e.event_label || e.event_type).replace(/_/g, ' ')}</span>
                    <span className="hp-pill-meta">{timeAgo(e.detected_at)}</span>
                  </button>
                ))
              : DEMO_RECENT.map((d) => (
                  <div key={d.key} className={`hp-pill hp-pill--${d.tone} hp-pill--demo`}>
                    <span className="hp-pill-icon" aria-hidden />
                    <span className="hp-pill-label">{d.label}</span>
                    <span className="hp-pill-meta">{d.ago}</span>
                  </div>
                ))}
          </div>
        </section>

        <section className="hp-search">
          <h2 className="hp-h2">Search your history (MongoDB Atlas Search)</h2>
          <p className="hp-muted-main hp-tight">
            Full-text on events and incidents; filters apply to event search. Same APIs as the pitch backend.
          </p>
          <div className="hp-search-row">
            <input
              className="hp-input hp-input-grow"
              value={searchQ}
              onChange={(e) => setSearchQ(e.target.value)}
              placeholder="e.g. stove, sound, water"
              onKeyDown={(e) => e.key === 'Enter' && void runSearch()}
            />
            <button type="button" className="hp-btn hp-btn-primary" disabled={searchBusy} onClick={() => void runSearch()}>
              {searchBusy ? '…' : 'Find'}
            </button>
          </div>
          {searchKind === 'events' ? (
            <div className="hp-search-filters">
              <label className="hp-filter">
                <span>Severity</span>
                <select
                  className="hp-select"
                  value={searchSeverity}
                  onChange={(e) => setSearchSeverity(e.target.value)}
                >
                  <option value="">Any</option>
                  <option value="LOW">LOW</option>
                  <option value="MEDIUM">MEDIUM</option>
                  <option value="HIGH">HIGH</option>
                  <option value="CRITICAL">CRITICAL</option>
                </select>
              </label>
              <label className="hp-filter">
                <span>Last N days</span>
                <input
                  className="hp-input hp-input-narrow"
                  type="number"
                  min={1}
                  max={365}
                  placeholder="e.g. 30"
                  value={searchDays}
                  onChange={(e) => setSearchDays(e.target.value)}
                />
              </label>
            </div>
          ) : null}
          <div className="hp-toggle">
            <button
              type="button"
              className={searchKind === 'events' ? 'active' : ''}
              onClick={() => setSearchKind('events')}
            >
              Events
            </button>
            <button
              type="button"
              className={searchKind === 'incidents' ? 'active' : ''}
              onClick={() => setSearchKind('incidents')}
            >
              Reports
            </button>
          </div>
          {searchHits.length > 0 ? (
            <ul className="hp-hit-list">
              {searchHits.map((h, i) => {
                const id = String(h.event_id ?? h.incident_id ?? i)
                const label = String(h.event_label ?? h.event_type ?? h.title ?? 'Entry')
                const when = h.detected_at ?? h.created_at
                return (
                  <li key={id} className="hp-hit">
                    <strong>{label.replace(/_/g, ' ')}</strong>
                    {when ? <span className="hp-muted-main"> — {String(when)}</span> : null}
                  </li>
                )
              })}
            </ul>
          ) : null}
          <div className="hp-patterns">
            <button type="button" className="hp-btn hp-btn-dark" disabled={patternsBusy} onClick={() => void runPatterns()}>
              {patternsBusy ? '…' : 'Pattern summary'}
            </button>
            {patternsNote ? <p className="hp-patterns-note">{patternsNote}</p> : null}
          </div>
        </section>

        {showPhotoLab ? (
          <section className="hp-lab">
            <CloudinaryPlayground />
          </section>
        ) : null}

        {showTools ? (
          <section className="hp-tools hp-about">
            <p className="hp-muted-main hp-tight">
              Search and pattern summary use the same MongoDB-backed APIs as the pitch docs. Hazard frame uses your saved crop
              zone; zoom moves the whole scene so the marked area is easier to see.
            </p>
            <p className="hp-muted-main hp-tight">
              <a className="hp-inline-link" href="#dev">
                Developer testing
              </a>{' '}
              for camera simulate and raw logs.
            </p>
          </section>
        ) : null}
      </main>
    </div>
  )
}
