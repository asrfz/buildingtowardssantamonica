import { useState } from 'react'
import { Dashboard } from './components/Dashboard'
import { ZoneCalibrator } from './components/ZoneCalibrator'

const USER_ID = import.meta.env.VITE_USER_ID ?? ''

type Tab = 'dashboard' | 'calibrate'

export function App() {
  const [tab, setTab] = useState<Tab>('dashboard')

  if (!USER_ID) {
    return (
      <div style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#f9fafb',
        fontFamily: 'Inter, sans-serif',
      }}>
        <div style={{
          background: '#fff',
          border: '1px solid #e5e7eb',
          borderRadius: 12,
          padding: 32,
          maxWidth: 480,
          textAlign: 'center',
        }}>
          <div style={{ fontSize: 36, marginBottom: 12 }}>🏠</div>
          <h2 style={{ margin: '0 0 8px', fontSize: 20, fontWeight: 700 }}>HomePulse AI</h2>
          <p style={{ margin: '0 0 16px', color: '#6b7280', fontSize: 14 }}>
            Set <code style={{ background: '#f3f4f6', padding: '2px 6px', borderRadius: 4 }}>VITE_USER_ID</code> in{' '}
            <code style={{ background: '#f3f4f6', padding: '2px 6px', borderRadius: 4 }}>frontend/.env.local</code>{' '}
            to the MongoDB ObjectId printed by <code>scripts/seed_demo.py</code>.
          </p>
          <p style={{ margin: 0, color: '#9ca3af', fontSize: 12 }}>
            Example: VITE_USER_ID=6637f2a4e1b2c3d4e5f60000
          </p>
        </div>
      </div>
    )
  }

  return (
    <div style={{ minHeight: '100vh', background: '#f9fafb', fontFamily: 'Inter, sans-serif' }}>
      {/* Top nav */}
      <header style={{
        background: '#fff',
        borderBottom: '1px solid #e5e7eb',
        position: 'sticky',
        top: 0,
        zIndex: 10,
      }}>
        <div style={{
          maxWidth: 960,
          margin: '0 auto',
          padding: '0 24px',
          height: 56,
          display: 'flex',
          alignItems: 'center',
          gap: 24,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flex: 1 }}>
            <span style={{ fontSize: 22 }}>🏠</span>
            <span style={{ fontWeight: 800, fontSize: 17, letterSpacing: '-0.01em' }}>HomePulse AI</span>
            <span style={{
              marginLeft: 4,
              fontSize: 11,
              background: '#eff6ff',
              color: '#2563eb',
              border: '1px solid #bfdbfe',
              borderRadius: 6,
              padding: '1px 7px',
              fontWeight: 600,
            }}>
              BETA
            </span>
          </div>

          <nav style={{ display: 'flex', gap: 4 }}>
            {([
              { id: 'dashboard', label: 'Dashboard' },
              { id: 'calibrate', label: 'Zone Setup' },
            ] as { id: Tab; label: string }[]).map(({ id, label }) => (
              <button
                key={id}
                onClick={() => setTab(id)}
                style={{
                  background: tab === id ? '#f3f4f6' : 'transparent',
                  border: 'none',
                  borderRadius: 6,
                  padding: '6px 14px',
                  fontSize: 13,
                  fontWeight: tab === id ? 700 : 500,
                  color: tab === id ? '#111827' : '#6b7280',
                  cursor: 'pointer',
                  transition: 'background 0.15s',
                }}
              >
                {label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      {/* Page body */}
      <main style={{ maxWidth: 960, margin: '0 auto', padding: '32px 24px' }}>
        {tab === 'dashboard' && <Dashboard userId={USER_ID} />}
        {tab === 'calibrate' && <ZoneCalibrator userId={USER_ID} />}
      </main>
    </div>
  )
}
