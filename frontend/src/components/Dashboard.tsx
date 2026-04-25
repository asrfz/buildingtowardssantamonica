import { useState } from 'react'
import { useEvents } from '../hooks/useEvents'
import { useZones } from '../hooks/useZones'
import { EventFeed } from './EventFeed'
import { simulateTrigger } from '../api/homepulse'

interface DashboardProps {
  userId: string
}

export function Dashboard({ userId }: DashboardProps) {
  const { events, loading, error, refresh } = useEvents(userId)
  const { zones } = useZones(userId)
  const [simulating, setSimulating] = useState<string | null>(null)
  const [simStatus, setSimStatus] = useState<string | null>(null)

  const pending  = events.filter(e => e.confirmed === null || e.confirmed === undefined)
  const resolved = events.filter(e => e.confirmed !== null && e.confirmed !== undefined)

  async function handleSimulate(scenario: 'stove' | 'faucet' | 'fridge') {
    setSimulating(scenario)
    setSimStatus(null)
    try {
      await simulateTrigger(scenario)
      setSimStatus(`${scenario} trigger sent — agents processing…`)
      setTimeout(refresh, 2500)
    } catch (e: any) {
      setSimStatus(`Error: ${e.message}`)
    } finally {
      setSimulating(null)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      {/* Stats row */}
      <div style={{ display: 'flex', gap: 16 }}>
        <StatCard label="Pending" value={pending.length} accent="#dc2626" />
        <StatCard label="Resolved" value={resolved.length} accent="#16a34a" />
        <StatCard label="Total" value={events.length} accent="#2563eb" />
        <div style={{
          flex: 1,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'flex-end',
          gap: 8,
        }}>
          <div style={{
            width: 8, height: 8, borderRadius: '50%',
            background: error ? '#dc2626' : '#16a34a',
            boxShadow: error ? 'none' : '0 0 0 3px #dcfce7',
            animation: error ? 'none' : 'pulse 2s infinite',
          }} />
          <span style={{ fontSize: 12, color: '#6b7280' }}>
            {error ? `Error: ${error}` : 'Polling every 5s'}
          </span>
        </div>
      </div>

      {/* Simulator */}
      <div style={{
        background: '#fff',
        borderRadius: 12,
        border: '1px solid #e5e7eb',
        padding: '16px 20px',
      }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: '#374151', marginBottom: 12, letterSpacing: '0.05em' }}>
          SIMULATE TRIGGER
        </div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
          <SimButton
            label="🔥 Stove Left On"
            color="#ef4444"
            loading={simulating === 'stove'}
            onClick={() => handleSimulate('stove')}
          />
          <SimButton
            label="💧 Faucet Running"
            color="#3b82f6"
            loading={simulating === 'faucet'}
            onClick={() => handleSimulate('faucet')}
          />
          <SimButton
            label="🧊 Fridge Open"
            color="#22c55e"
            loading={simulating === 'fridge'}
            onClick={() => handleSimulate('fridge')}
          />
          {simStatus && (
            <span style={{ fontSize: 12, color: '#6b7280', marginLeft: 4 }}>
              {simStatus}
            </span>
          )}
        </div>
      </div>

      {/* Event feed */}
      {loading ? (
        <div style={{ textAlign: 'center', padding: 40, color: '#9ca3af', fontSize: 14 }}>
          Loading events…
        </div>
      ) : (
        <EventFeed events={events} zones={zones} onUpdate={refresh} />
      )}
    </div>
  )
}

function StatCard({ label, value, accent }: { label: string; value: number; accent: string }) {
  return (
    <div style={{
      background: '#fff',
      borderRadius: 12,
      border: '1px solid #e5e7eb',
      padding: '14px 20px',
      minWidth: 100,
    }}>
      <div style={{ fontSize: 28, fontWeight: 800, color: accent, lineHeight: 1 }}>{value}</div>
      <div style={{ fontSize: 12, color: '#9ca3af', marginTop: 4, fontWeight: 500 }}>{label}</div>
    </div>
  )
}

function SimButton({
  label, color, loading, onClick,
}: {
  label: string; color: string; loading: boolean; onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      disabled={loading}
      style={{
        background: color,
        color: '#fff',
        border: 'none',
        borderRadius: 8,
        padding: '10px 18px',
        fontSize: 13,
        fontWeight: 600,
        cursor: loading ? 'not-allowed' : 'pointer',
        opacity: loading ? 0.6 : 1,
        transition: 'opacity 0.15s',
      }}
    >
      {loading ? 'Sending…' : label}
    </button>
  )
}
