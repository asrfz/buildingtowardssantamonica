export type Severity = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'

export type EventStatus =
  | 'detected'
  | 'triaged'
  | 'dismissed'
  | 'monitored'
  | 'notified'
  | 'confirmed'
  | 'false_positive'
  | 'logged_low'
  | 'notification_failed'

export interface ZoneBounds {
  x: number
  y: number
  w: number
  h: number
}

export type ZoneName = 'stove' | 'sink' | 'fridge'

export interface ZoneMap {
  stove?: ZoneBounds
  sink?: ZoneBounds
  fridge?: ZoneBounds
}

export interface HomePulseEvent {
  event_id: string
  user_id: string
  event_type: string
  severity: Severity
  deviation_score: number
  status: EventStatus
  notification_sent: boolean
  detected_at: string          // ISO string
  triage_reason?: string
  triage_confidence?: number
  recommended_action?: string
  suggested_service?: string
  raw_image_url?: string
  cropped_image_url?: string
  email_body?: string
  confirmed?: boolean | null
  sensor_payload?: Record<string, number>
}

export interface CaptureResult {
  public_id: string
  url: string
  width: number
  height: number
}

// Cloudinary public_id for a given event is always: homepulse/raw/<event_id>
export const eventPublicId = (eventId: string) => `homepulse/raw/${eventId}`
export const referencePublicId = () => 'homepulse/reference/calibration'
