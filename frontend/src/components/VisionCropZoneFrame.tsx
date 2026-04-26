import { useCallback, useId, useMemo, useState, type CSSProperties } from 'react'
import type { VisionCropZone } from '../lib/visionCropZone'

type Props = {
  src: string
  zone: VisionCropZone
  alt?: string
  maxHeight?: number
  style?: CSSProperties
  /** Default cyan (dev). Red matches hazard-analysis mockup. */
  accent?: 'cyan' | 'red'
  /** Centered label inside the crop rectangle (e.g. “Enhanced Camera Feed”). */
  centerCaption?: string
  /** Pill under the box, e.g. “POWER CORD — TRIP HAZARD”. */
  hazardLabel?: string
}

/**
 * Full-frame image with dim outside the crop rectangle + border (same rect as Cloudinary c_crop).
 */
export function VisionCropZoneFrame({
  src,
  zone,
  alt = 'Full frame',
  maxHeight = 220,
  style,
  accent = 'cyan',
  centerCaption,
  hazardLabel,
}: Props) {
  const maskId = useId().replace(/:/g, '')
  const [natural, setNatural] = useState({ w: 0, h: 0 })

  const onLoad = useCallback((e: React.SyntheticEvent<HTMLImageElement>) => {
    const el = e.currentTarget
    setNatural({ w: el.naturalWidth, h: el.naturalHeight })
  }, [])

  const rim = accent === 'red' ? 'rgba(239, 68, 68, 0.98)' : 'rgba(34, 211, 238, 0.95)'
  const rimGlow =
    accent === 'red'
      ? '0 0 0 1px rgba(0,0,0,0.45), 0 0 18px rgba(239, 68, 68, 0.45)'
      : '0 0 0 1px rgba(0,0,0,0.35), 0 0 16px rgba(34, 211, 238, 0.4)'
  const dimFill = accent === 'red' ? 'rgba(0, 0, 0, 0.58)' : 'rgba(15, 23, 42, 0.52)'

  const boxPct = useMemo(() => {
    if (zone.fractional) {
      return {
        left: zone.x * 100,
        top: zone.y * 100,
        width: zone.w * 100,
        height: zone.h * 100,
      }
    }
    if (natural.w <= 0 || natural.h <= 0) return null
    return {
      left: (zone.x / natural.w) * 100,
      top: (zone.y / natural.h) * 100,
      width: (zone.w / natural.w) * 100,
      height: (zone.h / natural.h) * 100,
    }
  }, [zone, natural.w, natural.h])

  return (
    <div
      style={{
        position: 'relative',
        width: '100%',
        maxWidth: '100%',
        borderRadius: 6,
        overflow: 'hidden',
        background: '#0a0f1a',
        paddingBottom: hazardLabel ? 44 : 0,
        ...style,
      }}
    >
      <img
        src={src}
        alt={alt}
        onLoad={onLoad}
        style={{
          width: '100%',
          maxWidth: '100%',
          height: 'auto',
          maxHeight,
          display: 'block',
        }}
      />
      {boxPct ? (
        <>
          <svg
            viewBox="0 0 100 100"
            preserveAspectRatio="none"
            style={{
              pointerEvents: 'none',
              position: 'absolute',
              left: 0,
              top: 0,
              width: '100%',
              height: '100%',
            }}
            aria-hidden
          >
            <defs>
              <mask id={maskId}>
                <rect width="100" height="100" fill="white" />
                <rect
                  x={boxPct.left}
                  y={boxPct.top}
                  width={boxPct.width}
                  height={boxPct.height}
                  fill="black"
                  rx={0.4}
                />
              </mask>
            </defs>
            <rect width="100" height="100" fill={dimFill} mask={`url(#${maskId})`} />
          </svg>
          {accent === 'red' ? (
            <>
              <div
                style={{
                  pointerEvents: 'none',
                  position: 'absolute',
                  left: `${boxPct.left}%`,
                  top: `${boxPct.top}%`,
                  width: 14,
                  height: 14,
                  borderLeft: `3px solid ${rim}`,
                  borderTop: `3px solid ${rim}`,
                }}
              />
              <div
                style={{
                  pointerEvents: 'none',
                  position: 'absolute',
                  left: `${boxPct.left + boxPct.width}%`,
                  top: `${boxPct.top}%`,
                  width: 14,
                  height: 14,
                  transform: 'translateX(-100%)',
                  borderRight: `3px solid ${rim}`,
                  borderTop: `3px solid ${rim}`,
                }}
              />
              <div
                style={{
                  pointerEvents: 'none',
                  position: 'absolute',
                  left: `${boxPct.left}%`,
                  top: `${boxPct.top + boxPct.height}%`,
                  width: 14,
                  height: 14,
                  transform: 'translateY(-100%)',
                  borderLeft: `3px solid ${rim}`,
                  borderBottom: `3px solid ${rim}`,
                }}
              />
              <div
                style={{
                  pointerEvents: 'none',
                  position: 'absolute',
                  left: `${boxPct.left + boxPct.width}%`,
                  top: `${boxPct.top + boxPct.height}%`,
                  width: 14,
                  height: 14,
                  transform: 'translate(-100%, -100%)',
                  borderRight: `3px solid ${rim}`,
                  borderBottom: `3px solid ${rim}`,
                }}
              />
            </>
          ) : null}
          <div
            style={{
              pointerEvents: 'none',
              position: 'absolute',
              left: `${boxPct.left}%`,
              top: `${boxPct.top}%`,
              width: `${boxPct.width}%`,
              height: `${boxPct.height}%`,
              boxSizing: 'border-box',
              border: `2px solid ${rim}`,
              borderRadius: 4,
              boxShadow: rimGlow,
            }}
          />
          {centerCaption ? (
            <div
              style={{
                pointerEvents: 'none',
                position: 'absolute',
                left: `${boxPct.left}%`,
                top: `${boxPct.top}%`,
                width: `${boxPct.width}%`,
                height: `${boxPct.height}%`,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <span
                style={{
                  fontSize: '0.78rem',
                  fontWeight: 600,
                  letterSpacing: '0.12em',
                  textTransform: 'uppercase' as const,
                  color: 'rgba(248, 250, 252, 0.88)',
                  textShadow: '0 1px 8px rgba(0,0,0,0.85)',
                }}
              >
                {centerCaption}
              </span>
            </div>
          ) : null}
          {hazardLabel ? (
            <div
              style={{
                pointerEvents: 'none',
                position: 'absolute',
                left: `${boxPct.left}%`,
                top: `${boxPct.top + boxPct.height}%`,
                width: `${boxPct.width}%`,
                marginTop: 8,
                display: 'flex',
                justifyContent: 'center',
              }}
            >
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 6,
                  padding: '8px 14px',
                  borderRadius: 999,
                  fontSize: '0.72rem',
                  fontWeight: 800,
                  letterSpacing: '0.06em',
                  textTransform: 'uppercase' as const,
                  color: '#fff',
                  background: 'linear-gradient(180deg, #dc2626 0%, #991b1b 100%)',
                  border: '1px solid rgba(254, 202, 202, 0.5)',
                  boxShadow: '0 4px 14px rgba(0,0,0,0.45)',
                  maxWidth: '96%',
                  textAlign: 'center',
                }}
              >
                ⚠ {hazardLabel}
              </span>
            </div>
          ) : null}
          {zone.zone_name ? (
            <div
              style={{
                pointerEvents: 'none',
                position: 'absolute',
                left: `${boxPct.left}%`,
                top: `${boxPct.top}%`,
                transform: 'translateY(calc(-100% - 4px))',
                padding: '2px 6px',
                fontSize: '0.62rem',
                fontWeight: 700,
                letterSpacing: '0.04em',
                textTransform: 'uppercase' as const,
                color: '#ecfeff',
                background: 'rgba(8, 51, 68, 0.92)',
                borderRadius: 4,
                maxWidth: 'min(90%, 200px)',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              {zone.zone_name}
            </div>
          ) : null}
        </>
      ) : !zone.fractional ? (
        <div
          style={{
            position: 'absolute',
            bottom: 6,
            left: 6,
            right: 6,
            fontSize: '0.65rem',
            color: '#94a3b8',
            textAlign: 'center',
          }}
        >
          Loading crop overlay…
        </div>
      ) : null}
    </div>
  )
}
