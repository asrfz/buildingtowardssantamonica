import type { Severity } from '../types'

const COLORS: Record<Severity, { bg: string; text: string }> = {
  LOW:      { bg: '#fef9c3', text: '#854d0e' },
  MEDIUM:   { bg: '#fed7aa', text: '#9a3412' },
  HIGH:     { bg: '#fecaca', text: '#991b1b' },
  CRITICAL: { bg: '#dc2626', text: '#ffffff' },
}

export function SeverityBadge({ severity }: { severity: Severity }) {
  const { bg, text } = COLORS[severity] ?? COLORS.LOW
  return (
    <span style={{
      display: 'inline-block',
      padding: '2px 8px',
      borderRadius: 12,
      fontSize: 11,
      fontWeight: 700,
      letterSpacing: '0.06em',
      background: bg,
      color: text,
    }}>
      {severity}
    </span>
  )
}
