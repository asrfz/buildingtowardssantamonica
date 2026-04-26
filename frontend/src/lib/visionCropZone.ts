export type VisionCropZone = {
  x: number
  y: number
  w: number
  h: number
  fractional: boolean
  zone_name?: string
}

export function parseVisionCropZone(v: unknown): VisionCropZone | null {
  if (!v || typeof v !== 'object') return null
  const o = v as Record<string, unknown>
  const x = Number(o.x)
  const y = Number(o.y)
  const w = Number(o.w)
  const h = Number(o.h)
  if (![x, y, w, h].every(Number.isFinite) || w <= 0 || h <= 0) return null
  return {
    x,
    y,
    w,
    h,
    fractional: o.fractional === undefined ? true : Boolean(o.fractional),
    zone_name: typeof o.zone_name === 'string' ? o.zone_name : undefined,
  }
}
