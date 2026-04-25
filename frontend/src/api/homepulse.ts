import type { HomePulseEvent, ZoneMap, CaptureResult } from '../types'

const BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`${res.status} ${path}: ${text}`)
  }
  return res.json() as Promise<T>
}

// ── Events ───────────────────────────────────────────────────────────────────

export async function fetchEvents(userId: string, limit = 50): Promise<HomePulseEvent[]> {
  const data = await request<{ events: HomePulseEvent[] }>(`/events/${userId}?limit=${limit}`)
  return data.events
}

export async function fetchEventDetail(eventId: string): Promise<HomePulseEvent> {
  return request<HomePulseEvent>(`/events/detail/${eventId}`)
}

export async function confirmEvent(eventId: string, confirmed: boolean): Promise<void> {
  await request(`/events/${eventId}/confirm`, {
    method: 'PATCH',
    body: JSON.stringify({ confirmed }),
  })
}

// ── Zones ────────────────────────────────────────────────────────────────────

export async function fetchZones(userId: string): Promise<ZoneMap> {
  const data = await request<{ user_id: string; zones: ZoneMap }>(`/zones/${userId}`)
  return data.zones
}

export async function saveZones(userId: string, zones: ZoneMap): Promise<void> {
  await request(`/zones/${userId}`, {
    method: 'POST',
    body: JSON.stringify({ zones }),
  })
}

// ── Sensor ───────────────────────────────────────────────────────────────────

export async function captureReferenceFrame(): Promise<CaptureResult> {
  return request<CaptureResult>('/sensor/capture', { method: 'POST' })
}

export async function simulateTrigger(scenario: 'stove' | 'faucet' | 'fridge'): Promise<void> {
  const payloads = {
    stove:  { sound_level: 210, temperature_c: 48.0, magnetic_state: 0, accel_x: 0.01, accel_y: 0.02, accel_z: 9.80, pressure: 1013.0, timestamp: new Date().toISOString() },
    faucet: { sound_level: 420, temperature_c: 22.5, magnetic_state: 0, accel_x: 0.01, accel_y: 0.01, accel_z: 9.81, pressure: 1013.0, timestamp: new Date().toISOString() },
    fridge: { sound_level: 205, temperature_c: 23.0, magnetic_state: 1, accel_x: 0.01, accel_y: 0.01, accel_z: 9.81, pressure: 1013.0, timestamp: new Date().toISOString() },
  }
  await request('/sensor/simulate', { method: 'POST', body: JSON.stringify(payloads[scenario]) })
}

// ── Alerts ───────────────────────────────────────────────────────────────────

export async function cancelAlert(alertId: string): Promise<void> {
  await request(`/alerts/${alertId}/cancel`, { method: 'PATCH' })
}
