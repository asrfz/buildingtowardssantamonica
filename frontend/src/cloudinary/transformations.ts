import { CloudinaryImage } from '@cloudinary/url-gen/assets/CloudinaryImage'
import { crop } from '@cloudinary/url-gen/actions/resize'
import { sharpen, improve } from '@cloudinary/url-gen/actions/adjust'
import { format, quality } from '@cloudinary/url-gen/actions/delivery'
import { auto } from '@cloudinary/url-gen/qualifiers/format'
import { auto as autoQuality } from '@cloudinary/url-gen/qualifiers/quality'
import type { ZoneBounds } from '../types'
import { cld } from './config'

// ── Zone crop: zoom into exactly where the issue is ──────────────────────────

export function buildZoneCrop(publicId: string, zone: ZoneBounds): CloudinaryImage {
  return cld
    .image(publicId)
    .resize(
      crop()
        .width(zone.w)
        .height(zone.h)
        .x(zone.x)
        .y(zone.y)
    )
    .adjust(sharpen().strength(80))
    .adjust(improve())
    .delivery(format(auto()))
    .delivery(quality(autoQuality()))
}

// ── Full raw frame (no crop) — shown as thumbnail context ────────────────────

export function buildRawFrame(publicId: string): CloudinaryImage {
  return cld
    .image(publicId)
    .delivery(format(auto()))
    .delivery(quality(autoQuality()))
}

// ── Reference frame for zone calibration (full size, no transforms) ──────────

export function buildCalibrationFrame(publicId: string): CloudinaryImage {
  return cld
    .image(publicId)
    .delivery(format(auto()))
    .delivery(quality(autoQuality()))
}

// ── Event-type specific visual enhancements ──────────────────────────────────
// For certain event types we apply additional effects on top of the zone crop.

const EVENT_ENHANCEMENTS: Record<string, (img: CloudinaryImage) => CloudinaryImage> = {
  // Fire risk: boost vibrance + contrast to make heat visible
  FIRE_RISK: (img) => img.adjust(improve()),

  // Water events: no extra enhancement needed
  FAUCET_RUNNING: (img) => img,
  WATER_DRIPPING: (img) => img,

  // Default: just the standard crop+sharpen+improve
  DEFAULT: (img) => img,
}

export function buildEventImage(
  publicId: string,
  zone: ZoneBounds,
  eventType: string
): CloudinaryImage {
  const base = buildZoneCrop(publicId, zone)
  const enhance = EVENT_ENHANCEMENTS[eventType] ?? EVENT_ENHANCEMENTS.DEFAULT
  return enhance(base)
}

// ── Zone colours used in calibrator and overlay ──────────────────────────────

export const ZONE_COLORS: Record<string, string> = {
  stove:  '#ef4444',  // red
  sink:   '#3b82f6',  // blue
  fridge: '#22c55e',  // green
}

export const ZONE_LABELS: Record<string, string> = {
  stove:  'Stove / Oven',
  sink:   'Sink',
  fridge: 'Fridge',
}

// ── Event type → zone name mapping (mirrors vision_service.py) ───────────────

export const EVENT_ZONE_MAP: Record<string, string> = {
  STOVE_LEFT_ON:   'stove',
  IRON_LEFT_ON:    'stove',
  FIRE_RISK:       'stove',
  FAUCET_RUNNING:  'sink',
  WATER_DRIPPING:  'sink',
  FRIDGE_OPEN:     'fridge',
  APPLIANCE_FAULT: 'stove',
  FALL_DETECTED:   'stove',
}
