import { useState } from 'react'
import type { HomePulseEvent, ZoneMap } from '../types'
import { SeverityBadge } from './SeverityBadge'
import { ZonedImage } from '../cloudinary/ZonedImage'
import { EVENT_ZONE_MAP } from '../cloudinary/transformations'
import { confirmEvent } from '../api/homepulse'

interface AlertCardProps {
  event: HomePulseEvent
  zones: ZoneMap
  onUpdate?: () => void
}

export function AlertCard({ event, zones, onUpdate }: AlertCardProps) {
  const [confirming, setConfirming] = useState(false)

  const zoneName = EVENT_ZONE_MAP[event.event_type] ?? 'stove'
  const zone     = zones[zoneName as keyof ZoneMap]
  const hasImage = !!event.raw_image_url && !!zone

  const readableType = event.event_type.replace(/_/g, ' ')
  const time = new Date(event.detected_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  const date = new Date(event.detected_at).toLocaleDateString([], { month: 'short', day: 'numeric' })

  async function handle(confirmed: boolean) {
    setConfirming(true)
    try {
      await confirmEvent(event.event_id, confirmed)
      onUpdate?.()
    } finally {
      setConfirming(false)
    }
  }

  const isResolved = event.confirmed !== null && event.confirmed !== undefined

  return (
    <div style={{
      background: '#fff',
      borderRadius: 12,
      border: '1px solid #e5e7eb',
      overflow: 'hidden',
      boxShadow: '0 1px 4px rgba(0,0,0,0.06)',
    }}>
      {/* Header */}
      <div style={{
        padding: '14px 16px',
        borderBottom: '1px solid #f3f4f6',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 12,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <SeverityBadge severity={event.severity} />
          <span style={{ fontWeight: 700, fontSize: 15 }}>{readableType}</span>
        </div>
        <span style={{ fontSize: 12, color: '#9ca3af', flexShrink: 0 }}>
          {date} · {time}
        </span>
      </div>

      {/* Body */}
      <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 14 }}>
        {/* Zoomed Cloudinary image */}
        {hasImage ? (
          <ZonedImage
            eventId={event.event_id}
            zone={zone!}
            zoneName={zoneName}
            eventType={event.event_type}
            showContext
          />
        ) : (
          <div style={{
            height: 120,
            background: '#f3f4f6',
            borderRadius: 8,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#9ca3af',
            fontSize: 13,
          }}>
            {event.raw_image_url ? 'Zone not calibrated' : 'No image captured'}
          </div>
        )}

        {/* Triage reason */}
        {event.triage_reason && (
          <div style={{ fontSize: 13, color: '#4b5563', lineHeight: 1.5 }}>
            <span style={{ fontWeight: 600 }}>Claude: </span>
            {event.triage_reason}
          </div>
        )}

        {/* Recommended action */}
        {event.recommended_action && (
          <div style={{
            background: '#eff6ff',
            border: '1px solid #bfdbfe',
            borderRadius: 6,
            padding: '8px 12px',
            fontSize: 13,
            color: '#1d4ed8',
          }}>
            💡 {event.recommended_action}
          </div>
        )}

        {/* Sensor readings */}
        {event.sensor_payload && (
          <details style={{ fontSize: 12, color: '#6b7280' }}>
            <summary style={{ cursor: 'pointer', userSelect: 'none' }}>Sensor readings</summary>
            <div style={{ marginTop: 6, display: 'flex', gap: 10, flexWrap: 'wrap' }}>
              {Object.entries(event.sensor_payload).map(([k, v]) => (
                <span key={k} style={{
                  background: '#f3f4f6',
                  borderRadius: 4,
                  padding: '2px 6px',
                  fontFamily: 'monospace',
                }}>
                  {k}: {typeof v === 'number' ? v.toFixed(2) : v}
                </span>
              ))}
            </div>
          </details>
        )}

        {/* Confirm / dismiss buttons */}
        {!isResolved && event.status !== 'dismissed' && (
          <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
            <button
              onClick={() => handle(true)}
              disabled={confirming}
              style={{
                flex: 1,
                padding: '8px 0',
                background: '#dc2626',
                color: '#fff',
                border: 'none',
                borderRadius: 6,
                fontWeight: 600,
                fontSize: 13,
                cursor: 'pointer',
              }}
            >
              ✓ Confirm Real
            </button>
            <button
              onClick={() => handle(false)}
              disabled={confirming}
              style={{
                flex: 1,
                padding: '8px 0',
                background: '#f3f4f6',
                color: '#374151',
                border: '1px solid #e5e7eb',
                borderRadius: 6,
                fontWeight: 600,
                fontSize: 13,
                cursor: 'pointer',
              }}
            >
              ✕ False Alarm
            </button>
          </div>
        )}

        {/* Resolved state */}
        {isResolved && (
          <div style={{ fontSize: 12, color: event.confirmed ? '#16a34a' : '#9ca3af', fontWeight: 600 }}>
            {event.confirmed ? '✅ Confirmed real' : '✕ Marked false alarm'}
          </div>
        )}
      </div>
    </div>
  )
}
