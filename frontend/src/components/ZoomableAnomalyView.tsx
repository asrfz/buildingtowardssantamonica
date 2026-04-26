import { useMemo } from 'react'
import type { VisionCropZone } from '../lib/visionCropZone'
import { VisionCropZoneFrame } from './VisionCropZoneFrame'

type Props = {
  rawUrl: string
  zone: VisionCropZone
  zoom: number
  shortLabel: string
  /** Shown on red pill under crop (mockup style). */
  hazardLabel?: string
}

/**
 * Full-frame view with crop overlay; zoom scales toward crop center.
 */
export function ZoomableAnomalyView({ rawUrl, zone, zoom, shortLabel, hazardLabel }: Props) {
  const origin = useMemo(() => {
    if (zone.fractional) {
      const cx = (zone.x + zone.w / 2) * 100
      const cy = (zone.y + zone.h / 2) * 100
      return `${cx}% ${cy}%`
    }
    return '50% 50%'
  }, [zone])

  return (
    <div className="hp-feed-zoom-outer">
      <div
        className="hp-feed-zoom-inner"
        style={{
          transform: `scale(${zoom})`,
          transformOrigin: origin,
          transition: 'transform 0.2s ease',
        }}
      >
        <VisionCropZoneFrame
          src={rawUrl}
          zone={zone}
          alt={shortLabel}
          maxHeight={520}
          accent="red"
          centerCaption="Enhanced Camera Feed"
          hazardLabel={hazardLabel}
        />
      </div>
    </div>
  )
}
