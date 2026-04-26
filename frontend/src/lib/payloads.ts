/** Optional: skip scoring and send this event straight to triage (works without baselines). */
export type ForceTriage = {
  event_type: string
  severity?: string
  deviation_score?: number
  reason?: string
  sensor?: string
}

/** Body for POST /sensor/simulate — flat reading or wrapped with force_triage. */
export function simulateBody(payload: Record<string, unknown>, forceTriage?: ForceTriage) {
  if (forceTriage) {
    return JSON.stringify({ payload, force_triage: forceTriage })
  }
  return JSON.stringify(payload)
}

/** Minimal valid SensorPayload for POST /sensor/simulate — matches FastAPI model. */
export function basePayload(overrides: Record<string, unknown> = {}) {
  return {
    sound_level: 210,
    temperature_c: 22.0,
    magnetic_state: 0,
    accel_x: 0.01,
    accel_y: 0.02,
    accel_z: 9.8,
    pressure: 1013.0,
    timestamp: new Date().toISOString(),
    drop_detected: 0,
    light_change_detected: 0,
    motion_triggered: 0,
    gyro_triggered: 0,
    sound_triggered: 0,
    magnetic_triggered: 0,
    light_level: 512,
    ...overrides,
  }
}

export const PRESETS = {
  normal: () => basePayload({}),
  stove: () =>
    basePayload({
      temperature_c: 48.0,
      accel_x: 0,
      accel_y: 0,
      accel_z: 0.2,
    }),
  faucet: () => basePayload({ sound_level: 420, temperature_c: 22.2 }),
  fridge: () => basePayload({ magnetic_state: 1, temperature_c: 22.5 }),
  fire: () =>
    basePayload({
      temperature_c: 65.0,
      sound_level: 800,
      accel_x: 2.5,
      accel_y: 1.8,
      accel_z: 12.0,
    }),
  /** Loud sound levels for UI — still needs baselines unless you use force_triage. */
  loudNoise: () =>
    basePayload({
      sound_level: 920,
      sound_triggered: 1,
      temperature_c: 22.0,
    }),
} as const

/** Deterministic SOUND_ANOMALY — bypasses baseline scoring (full agent pipeline). */
export const FORCE_LOUD_NOISE: ForceTriage = {
  event_type: 'SOUND_ANOMALY',
  severity: 'HIGH',
  deviation_score: 7.0,
  reason: 'Simulated loud noise (demo — bypass scoring)',
  sensor: 'sound',
}
