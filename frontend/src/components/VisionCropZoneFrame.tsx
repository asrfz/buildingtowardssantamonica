import { useCallback, useId, useMemo, useState, type CSSProperties } from 'react'
import type { VisionCropZone } from '../lib/visionCropZone'

type Props = {
  src: string
  zone: VisionCropZone
  alt?: string
  maxHeight?: number
  style?: CSSProperties
}

/**
 * Full-frame image with dim outside the crop rectangle + cyan border (same rect as Cloudinary c_crop).
 */
export function VisionCropZoneFrame({ src, zone, alt = 'Full frame', maxHeight = 220, style }: Props) {
  const maskId = useId().replace(/:/g, '')
  const [natural, setNatural] = useState({ w: 0, h: 0 })

  const onLoad = useCallback((e: React.SyntheticEvent<HTMLImageElement>) => {
    const el = e.currentTarget
    setNatural({ w: el.naturalWidth, h: el.naturalHeight })
  }, [])

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
            <rect width="100" height="100" fill="rgba(15, 23, 42, 0.52)" mask={`url(#${maskId})`} />
          </svg>
          <div
            style={{
              pointerEvents: 'none',
              position: 'absolute',
              left: `${boxPct.left}%`,
              top: `${boxPct.top}%`,
              width: `${boxPct.width}%`,
              height: `${boxPct.height}%`,
              boxSizing: 'border-box',
              border: '2px solid rgba(34, 211, 238, 0.95)',
              borderRadius: 4,
              boxShadow: '0 0 0 1px rgba(0,0,0,0.35), 0 0 16px rgba(34, 211, 238, 0.4)',
            }}
          />
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
