import { AdvancedImage } from '@cloudinary/react'
import type { ZoneBounds, ZoneName } from '../types'
import { eventPublicId } from '../types'
import { buildEventImage, buildRawFrame, ZONE_COLORS, ZONE_LABELS } from './transformations'

interface ZonedImageProps {
  eventId: string
  zone: ZoneBounds
  zoneName: ZoneName | string
  eventType: string
  /** If true, renders a thumbnail of the full unzoomed frame beside the crop */
  showContext?: boolean
}

export function ZonedImage({ eventId, zone, zoneName, eventType, showContext = true }: ZonedImageProps) {
  const publicId = eventPublicId(eventId)
  const croppedImg = buildEventImage(publicId, zone, eventType)
  const rawImg     = buildRawFrame(publicId)
  const zoneColor  = ZONE_COLORS[zoneName] ?? '#6b7280'
  const zoneLabel  = ZONE_LABELS[zoneName] ?? zoneName

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {/* Zone badge */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <div style={{ width: 10, height: 10, borderRadius: 2, background: zoneColor }} />
        <span style={{ fontSize: 12, fontWeight: 600, color: '#6b7280', letterSpacing: '0.05em' }}>
          {zoneLabel.toUpperCase()} — ZOOMED VIEW
        </span>
      </div>

      <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
        {/* Main cropped / zoomed image */}
        <div style={{
          border: `2px solid ${zoneColor}`,
          borderRadius: 8,
          overflow: 'hidden',
          boxShadow: `0 0 0 4px ${zoneColor}22`,
          flexShrink: 0,
        }}>
          <AdvancedImage
            cldImg={croppedImg}
            style={{ display: 'block', maxWidth: 320, maxHeight: 240, objectFit: 'cover' }}
            alt={`${eventType} zone view`}
          />
        </div>

        {/* Context thumbnail — full unzoomed frame */}
        {showContext && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <span style={{ fontSize: 11, color: '#9ca3af' }}>Full frame</span>
            <div style={{
              border: '1px solid #e5e7eb',
              borderRadius: 6,
              overflow: 'hidden',
              position: 'relative',
            }}>
              <AdvancedImage
                cldImg={rawImg}
                style={{ display: 'block', width: 160, objectFit: 'cover' }}
                alt="Full camera view"
              />
              {/* Overlay rectangle showing which zone is highlighted */}
              <ZoneOverlay zone={zone} frameWidth={640} frameHeight={480} displayWidth={160} zoneColor={zoneColor} />
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// Draws a coloured rectangle on the thumbnail showing where the zone is
interface ZoneOverlayProps {
  zone: ZoneBounds
  frameWidth: number   // actual webcam capture width
  frameHeight: number  // actual webcam capture height
  displayWidth: number // thumbnail display width
  zoneColor: string
}

function ZoneOverlay({ zone, frameWidth, frameHeight, displayWidth, zoneColor }: ZoneOverlayProps) {
  const scale = displayWidth / frameWidth
  const displayHeight = frameHeight * scale

  const left   = zone.x * scale
  const top    = zone.y * scale
  const width  = zone.w * scale
  const height = zone.h * scale

  return (
    <svg
      style={{ position: 'absolute', top: 0, left: 0, pointerEvents: 'none' }}
      width={displayWidth}
      height={displayHeight}
    >
      <rect
        x={left}
        y={top}
        width={width}
        height={height}
        fill={`${zoneColor}33`}
        stroke={zoneColor}
        strokeWidth={1.5}
        rx={2}
      />
    </svg>
  )
}
