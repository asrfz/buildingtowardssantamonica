import type { HomePulseEvent, ZoneMap } from '../types'
import { AlertCard } from './AlertCard'
import { SeverityBadge } from './SeverityBadge'

interface EventFeedProps {
  events: HomePulseEvent[]
  zones: ZoneMap
  onUpdate: () => void
}

export function EventFeed({ events, zones, onUpdate }: EventFeedProps) {
  if (events.length === 0) {
    return (
      <div style={{
        textAlign: 'center',
        padding: '60px 0',
        color: '#9ca3af',
        fontSize: 15,
      }}>
        <div style={{ fontSize: 40, marginBottom: 12 }}>🏠</div>
        <div>All clear — no events detected yet.</div>
        <div style={{ fontSize: 13, marginTop: 6 }}>
          Use the simulator buttons or connect your Arduino to trigger an event.
        </div>
      </div>
    )
  }

  const unresolved = events.filter(e => e.confirmed === null || e.confirmed === undefined)
  const resolved   = events.filter(e => e.confirmed !== null && e.confirmed !== undefined)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      {unresolved.length > 0 && (
        <section>
          <h3 style={{ margin: '0 0 12px', fontSize: 14, fontWeight: 700, color: '#374151', letterSpacing: '0.05em' }}>
            PENDING — {unresolved.length} event{unresolved.length !== 1 ? 's' : ''}
          </h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {unresolved.map(ev => (
              <AlertCard key={ev.event_id} event={ev} zones={zones} onUpdate={onUpdate} />
            ))}
          </div>
        </section>
      )}

      {resolved.length > 0 && (
        <section>
          <h3 style={{ margin: '0 0 12px', fontSize: 14, fontWeight: 700, color: '#9ca3af', letterSpacing: '0.05em' }}>
            HISTORY — {resolved.length} resolved
          </h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {resolved.map(ev => (
              <ResolvedRow key={ev.event_id} event={ev} />
            ))}
          </div>
        </section>
      )}
    </div>
  )
}

function ResolvedRow({ event }: { event: HomePulseEvent }) {
  const time = new Date(event.detected_at).toLocaleString([], {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
  const readableType = event.event_type.replace(/_/g, ' ')

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      padding: '8px 12px',
      background: '#f9fafb',
      borderRadius: 8,
      fontSize: 13,
    }}>
      <SeverityBadge severity={event.severity} />
      <span style={{ flex: 1, color: '#374151' }}>{readableType}</span>
      <span style={{ color: '#9ca3af' }}>{time}</span>
      <span style={{ fontSize: 12, fontWeight: 600, color: event.confirmed ? '#16a34a' : '#6b7280' }}>
        {event.confirmed ? 'Real' : 'False alarm'}
      </span>
    </div>
  )
}
