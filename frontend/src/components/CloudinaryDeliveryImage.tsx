import { useMemo, type CSSProperties } from 'react'
import {
  compactChipLabel,
  decodeCloudinaryDeliveryUrl,
  pipelineBadgeLabel,
  pipelineBadgeShort,
  type DecodedCloudinaryDelivery,
} from '../lib/cloudinaryDecode'

const CHIP_STYLES: Record<DecodedCloudinaryDelivery['chips'][number]['kind'], { bg: string; border: string; color: string }> =
  {
    crop: { bg: 'rgba(6, 182, 212, 0.2)', border: 'rgba(34, 211, 238, 0.35)', color: '#ecfeff' },
    effect: { bg: 'rgba(168, 85, 247, 0.18)', border: 'rgba(196, 181, 253, 0.35)', color: '#f5f3ff' },
    delivery: { bg: 'rgba(34, 197, 94, 0.18)', border: 'rgba(74, 222, 128, 0.35)', color: '#f0fdf4' },
    limit: { bg: 'rgba(251, 191, 36, 0.2)', border: 'rgba(252, 211, 77, 0.35)', color: '#fffbeb' },
    named: { bg: 'rgba(244, 63, 94, 0.18)', border: 'rgba(253, 164, 175, 0.35)', color: '#fff1f2' },
    flags: { bg: 'rgba(148, 163, 184, 0.2)', border: 'rgba(203, 213, 225, 0.3)', color: '#f8fafc' },
    other: { bg: 'rgba(148, 163, 184, 0.14)', border: 'rgba(148, 163, 184, 0.28)', color: '#e2e8f0' },
  }

const PIPELINE_BADGE: Record<DecodedCloudinaryDelivery['pipeline'], { bg: string; color: string }> = {
  thumb: { bg: 'rgba(180, 83, 9, 0.92)', color: '#fffbeb' },
  full_crop: { bg: 'rgba(3, 105, 161, 0.92)', color: '#f0f9ff' },
  raw: { bg: 'rgba(51, 65, 85, 0.92)', color: '#f1f5f9' },
  transformed: { bg: 'rgba(91, 33, 182, 0.92)', color: '#faf5ff' },
  unknown: { bg: 'rgba(71, 85, 105, 0.92)', color: '#f8fafc' },
}

function overlayTitle(meta: DecodedCloudinaryDelivery): string {
  const chain = meta.chips.map((c) => c.label).join(' · ')
  return `${meta.publicId}\n${chain}`
}

type Props = {
  src: string
  alt: string
  href?: string
  /** Max chips in the one-line strip (+N if more); keep low for small tiles */
  maxChips?: number
  imgStyle?: CSSProperties
  minHeight?: number
}

export function CloudinaryDeliveryImage({ src, alt, href, maxChips = 6, imgStyle, minHeight }: Props) {
  const meta = useMemo(() => decodeCloudinaryDeliveryUrl(src), [src])
  const chips = meta?.chips ?? []
  const shown = chips.slice(0, maxChips)
  const more = chips.length - shown.length
  const tip = meta ? overlayTitle(meta) : alt

  const inner = (
    <div style={{ position: 'relative', lineHeight: 0, borderRadius: 'inherit', overflow: 'hidden' }} title={href ? undefined : tip}>
      <img
        src={src}
        alt={alt}
        style={{
          width: '100%',
          display: 'block',
          objectFit: 'cover',
          ...imgStyle,
          ...(minHeight ? { minHeight } : {}),
        }}
      />
      {meta ? (
        <>
          <div
            title={pipelineBadgeLabel(meta.pipeline)}
            style={{
              pointerEvents: 'none',
              position: 'absolute',
              top: 4,
              right: 4,
              fontSize: '0.5rem',
              fontWeight: 700,
              letterSpacing: '0.06em',
              padding: '2px 5px',
              borderRadius: 4,
              background: PIPELINE_BADGE[meta.pipeline].bg,
              color: PIPELINE_BADGE[meta.pipeline].color,
              boxShadow: '0 1px 4px rgba(0,0,0,0.35)',
              lineHeight: 1.2,
            }}
          >
            {pipelineBadgeShort(meta.pipeline)}
          </div>
          <div
            style={{
              pointerEvents: 'none',
              position: 'absolute',
              left: 0,
              right: 0,
              bottom: 0,
              padding: '4px 5px 5px',
              background: 'linear-gradient(to top, rgba(15, 23, 42, 0.88) 0%, rgba(15, 23, 42, 0.45) 55%, transparent 100%)',
              display: 'flex',
              flexDirection: 'row',
              flexWrap: 'nowrap',
              gap: 3,
              alignItems: 'center',
              overflow: 'hidden',
              minHeight: 0,
            }}
            title={chips.map((c) => `${compactChipLabel(c)}: ${c.label}`).join('\n')}
          >
            {shown.map((c) => {
              const s = CHIP_STYLES[c.kind]
              const short = compactChipLabel(c)
              return (
                <span
                  key={c.id}
                  title={c.label}
                  style={{
                    flex: '0 0 auto',
                    fontSize: '0.5rem',
                    fontWeight: 600,
                    letterSpacing: '0.02em',
                    padding: '1px 4px',
                    borderRadius: 4,
                    border: `1px solid ${s.border}`,
                    background: s.bg,
                    color: s.color,
                    textShadow: '0 1px 1px rgba(0,0,0,0.4)',
                    lineHeight: 1.25,
                    maxWidth: 52,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {short}
                </span>
              )
            })}
            {more > 0 ? (
              <span
                title={chips.slice(maxChips).map((c) => c.label).join(' · ')}
                style={{
                  flex: '0 0 auto',
                  fontSize: '0.5rem',
                  fontWeight: 700,
                  padding: '1px 4px',
                  borderRadius: 4,
                  border: '1px solid rgba(248, 250, 252, 0.25)',
                  background: 'rgba(15, 23, 42, 0.55)',
                  color: '#cbd5e1',
                }}
              >
                +{more}
              </span>
            ) : null}
          </div>
        </>
      ) : null}
    </div>
  )

  if (href) {
    return (
      <a href={href} target="_blank" rel="noreferrer" style={{ display: 'block', lineHeight: 0 }} title={tip}>
        {inner}
      </a>
    )
  }

  return inner
}
