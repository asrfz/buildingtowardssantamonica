/**
 * Decode Cloudinary delivery URLs into human-readable transformation "tags"
 * for dev-console overlays (no extra API calls — all from the URL path).
 */

export type CloudinaryChip = {
  id: string
  label: string
  /** UI hint: crop | effect | delivery | limit | named | flags | other */
  kind: 'crop' | 'effect' | 'delivery' | 'limit' | 'named' | 'flags' | 'other'
}

export type DecodedCloudinaryDelivery = {
  cloudName: string
  /** joined path after version, e.g. homepulse/raw/abc */
  publicId: string
  publicIdShort: string
  rawSegments: string[]
  chips: CloudinaryChip[]
  /** Heuristic from transformation chain */
  pipeline: 'thumb' | 'full_crop' | 'raw' | 'transformed' | 'unknown'
}

const IMG_RESOURCE = /\/image\/upload\//

function stripQueryHash(url: string): string {
  try {
    const u = new URL(url)
    return `${u.origin}${u.pathname}`
  } catch {
    return url.split('?')[0]?.split('#')[0] ?? url
  }
}

function isSignedSegment(seg: string): boolean {
  return seg.startsWith('s--') && seg.endsWith('--') && seg.length > 6
}

function isTransformSegment(seg: string): boolean {
  if (!seg || seg === 'homepulse') return false
  if (/^v\d+$/i.test(seg)) return false
  if (isSignedSegment(seg)) return false
  if (/\.(jpe?g|png|webp|gif|svg)$/i.test(seg)) return false
  const head = seg.split(',')[0] ?? ''
  const prefixes = [
    'c_',
    'e_',
    'q_',
    'f_',
    'dpr_',
    'fl_',
    't_',
    'a_',
    'b_',
    'bo_',
    'co_',
    'dn_',
    'du_',
    'eo_',
    'so_',
    'ar_',
    'w_',
    'h_',
    'x_',
    'y_',
  ]
  if (prefixes.some((p) => head.startsWith(p))) return true
  // Chained params in one path segment
  if (seg.includes(',') && /^[a-z]{1,4}_/i.test(head)) return true
  return false
}

function parseAfterUpload(segments: string[]): { transforms: string[]; publicParts: string[] } {
  let i = 0
  if (segments[i] && isSignedSegment(segments[i])) i++

  if (segments[i] && /^v\d+$/i.test(segments[i])) {
    return { transforms: [], publicParts: segments.slice(i + 1) }
  }

  const transforms: string[] = []
  while (i < segments.length) {
    const s = segments[i]
    if (s === 'homepulse') {
      break
    }
    if (isTransformSegment(s)) {
      transforms.push(s)
      i++
      continue
    }
    break
  }
  return { transforms, publicParts: segments.slice(i) }
}

function extractWidthFromLimit(segment: string): string | null {
  const m = segment.match(/(?:^|,)w_(\d+)/i)
  return m ? m[1] ?? null : null
}

function segmentHasFractionalBox(segment: string): boolean {
  return /[,/]([xywh])_(0?\.\d+|1\.0+)\b/.test(segment)
}

function chipsFromSegment(seg: string, ctx: { sawRelative: boolean }): CloudinaryChip[] {
  const out: CloudinaryChip[] = []
  const head = seg.split(',')[0]?.trim() ?? ''
  // Delivery tokens are often chained as `f_auto,q_auto` in one path segment.
  if (seg.includes(',') && !head.startsWith('c_')) {
    return seg
      .split(',')
      .map((p) => p.trim())
      .filter(Boolean)
      .flatMap((piece) => chipsFromSegment(piece, ctx))
  }

  if (head.startsWith('c_crop')) {
    const frac = segmentHasFractionalBox(seg)
    out.push({
      id: `crop-${seg}`,
      label: ctx.sawRelative || frac ? 'Zone crop · 0–1 box' : 'Zone crop · pixels',
      kind: 'crop',
    })
    return out
  }

  if (head.startsWith('c_limit')) {
    const w = extractWidthFromLimit(seg)
    out.push({
      id: `limit-${seg}`,
      label: w ? `c_limit · w_${w}` : 'c_limit',
      kind: 'limit',
    })
    return out
  }

  if (head === 'fl_relative' || seg === 'fl_relative') {
    ctx.sawRelative = true
    out.push({ id: 'fl_relative', label: 'fl_relative', kind: 'flags' })
    return out
  }

  if (head.startsWith('e_sharpen')) {
    const m = seg.match(/e_sharpen:(\d+)/i)
    out.push({
      id: seg,
      label: m ? `Sharpen · ${m[1]}` : 'Sharpen',
      kind: 'effect',
    })
    return out
  }

  if (head.startsWith('e_improve')) {
    out.push({ id: 'improve', label: 'e_improve', kind: 'effect' })
    return out
  }

  if (head === 'q_auto' || seg === 'q_auto') {
    out.push({ id: 'q_auto', label: 'q_auto', kind: 'delivery' })
    return out
  }

  if (head === 'f_auto' || seg === 'f_auto') {
    out.push({ id: 'f_auto', label: 'f_auto', kind: 'delivery' })
    return out
  }

  if (head.startsWith('dpr_auto') || seg.startsWith('dpr_auto')) {
    out.push({ id: 'dpr_auto', label: 'dpr_auto', kind: 'delivery' })
    return out
  }

  if (head.startsWith('t_')) {
    const name = head.slice(2) || 'named'
    out.push({
      id: seg,
      label: `Named · ${name}`,
      kind: 'named',
    })
    return out
  }

  out.push({
    id: seg,
    label: seg.length > 42 ? `${seg.slice(0, 40)}…` : seg,
    kind: 'other',
  })
  return out
}

function buildChips(transforms: string[]): CloudinaryChip[] {
  const ctx = { sawRelative: false }
  const chips: CloudinaryChip[] = []
  for (const t of transforms) {
    chips.push(...chipsFromSegment(t, ctx))
  }
  // Dedupe by id while keeping order
  const seen = new Set<string>()
  return chips.filter((c) => {
    if (seen.has(c.id)) return false
    seen.add(c.id)
    return true
  })
}

function inferPipeline(transforms: string[], chips: CloudinaryChip[]): DecodedCloudinaryDelivery['pipeline'] {
  if (transforms.length === 0) return 'raw'
  const hasLimit = chips.some((c) => c.kind === 'limit')
  const hasCrop = chips.some((c) => c.label.startsWith('Zone crop'))
  if (hasLimit && hasCrop) return 'thumb'
  if (hasCrop) return 'full_crop'
  if (transforms.length > 0) return 'transformed'
  return 'unknown'
}

/**
 * Returns null if the URL is not a recognizable Cloudinary image delivery URL.
 */
export function decodeCloudinaryDeliveryUrl(url: string): DecodedCloudinaryDelivery | null {
  if (!url || !url.includes('res.cloudinary.com')) return null
  const path = stripQueryHash(url)
  if (!IMG_RESOURCE.test(path)) return null

  let u: URL
  try {
    u = new URL(path.startsWith('http') ? path : `https://${path}`)
  } catch {
    return null
  }
  const parts = u.pathname.split('/').filter(Boolean)
  const uploadIdx = parts.findIndex((p, i) => p === 'upload' && parts[i - 1] === 'image')
  if (uploadIdx < 0) return null

  const cloudName = parts[0] ?? ''
  const after = parts.slice(uploadIdx + 1)
  const { transforms, publicParts } = parseAfterUpload(after)
  const publicId = publicParts.join('/')
  const publicIdShort =
    publicId.length > 44 ? `…${publicId.slice(-40)}` : publicId

  const chips = buildChips(transforms)
  const pipeline = inferPipeline(transforms, chips)

  return {
    cloudName,
    publicId,
    publicIdShort,
    rawSegments: transforms,
    chips,
    pipeline,
  }
}

export function pipelineBadgeLabel(pipeline: DecodedCloudinaryDelivery['pipeline']): string {
  switch (pipeline) {
    case 'thumb':
      return 'Thumb chain'
    case 'full_crop':
      return 'Full crop'
    case 'raw':
      return 'Original'
    case 'transformed':
      return 'Transformed'
    default:
      return 'Cloudinary'
  }
}

/** Tiny corner badge — full wording in tooltip via `pipelineBadgeLabel`. */
export function pipelineBadgeShort(pipeline: DecodedCloudinaryDelivery['pipeline']): string {
  switch (pipeline) {
    case 'thumb':
      return 'Thumb'
    case 'full_crop':
      return 'Full'
    case 'raw':
      return 'Raw'
    case 'transformed':
      return 'FX'
    default:
      return 'CLD'
  }
}

/** One-line overlay chips — hover each chip for the long `label`. */
export function compactChipLabel(chip: CloudinaryChip): string {
  switch (chip.kind) {
    case 'crop':
      return /0[–-]1|fraction/i.test(chip.label) ? 'cR' : 'cP'
    case 'flags':
      return 'rel'
    case 'effect':
      if (/sharpen/i.test(chip.label)) {
        const m = chip.label.match(/(\d+)/)
        return m ? `shrp${m[1]}` : 'shrp'
      }
      if (/improve/i.test(chip.label)) return 'imp'
      return chip.label.length > 6 ? `${chip.label.slice(0, 5)}…` : chip.label
    case 'delivery':
      if (chip.label === 'q_auto') return 'q'
      if (chip.label === 'f_auto') return 'fmt'
      if (/^dpr/i.test(chip.label)) return 'dpr'
      return chip.label
    case 'limit': {
      const m = chip.label.match(/w_(\d+)/i)
      return m ? `w${m[1]}` : 'lim'
    }
    case 'named':
      return chip.label.replace(/^Named ·\s*/i, 't:').slice(0, 10)
    default:
      return chip.label.length > 8 ? `${chip.label.slice(0, 7)}…` : chip.label
  }
}
