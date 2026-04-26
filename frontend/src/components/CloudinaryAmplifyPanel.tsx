/**
 * Cloudinary delivery “amplify” strip: generative restore, upscale, enhance + tags from Admin API.
 */
import { useEffect, useMemo, useState } from 'react'
import { AdvancedImage } from '@cloudinary/react'
import { Cloudinary } from '@cloudinary/url-gen'
import { improve, sharpen } from '@cloudinary/url-gen/actions/adjust'
import { format, quality } from '@cloudinary/url-gen/actions/delivery'
import { generativeRestore, upscale, enhance } from '@cloudinary/url-gen/actions/effect'
import { scale } from '@cloudinary/url-gen/actions/resize'
import { auto as qAuto } from '@cloudinary/url-gen/qualifiers/quality'
import { auto as fAuto } from '@cloudinary/url-gen/qualifiers/format'
import { apiBase } from '../lib/api'

type ResourceInfo = {
  tags: string[]
  context: Record<string, unknown>
  colors?: { color: string; score: number }[]
  width?: number
  height?: number
  faces?: unknown
}

type Variant = { key: string; label: string; hint: string; img: ReturnType<Cloudinary['image']> }

function baseChain(cld: Cloudinary, publicId: string, w: number) {
  return cld
    .image(publicId)
    .resize(scale().width(w))
    .adjust(improve())
    .adjust(sharpen(80))
    .delivery(quality(qAuto()))
    .delivery(format(fAuto()))
}

export function CloudinaryAmplifyPanel({ cloudName, publicId }: { cloudName: string; publicId: string }) {
  const [info, setInfo] = useState<ResourceInfo | null>(null)
  const [infoErr, setInfoErr] = useState('')

  useEffect(() => {
    let cancelled = false
    const enc = encodeURIComponent(publicId)
    void (async () => {
      try {
        const r = await fetch(`${apiBase()}/cloudinary/resource?public_id=${enc}`)
        if (!r.ok) {
          const t = await r.text()
          if (!cancelled) {
            setInfoErr(t.slice(0, 220))
            setInfo(null)
          }
          return
        }
        const j = (await r.json()) as ResourceInfo & { public_id?: string }
        if (!cancelled) {
          setInfoErr('')
          setInfo({
            tags: Array.isArray(j.tags) ? j.tags : [],
            context: j.context && typeof j.context === 'object' ? j.context : {},
            colors: j.colors,
            width: j.width,
            height: j.height,
            faces: j.faces,
          })
        }
      } catch (e) {
        if (!cancelled) {
          setInfoErr(e instanceof Error ? e.message : 'Request failed')
          setInfo(null)
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [publicId])

  const cld = useMemo(() => new Cloudinary({ cloud: { cloudName }, url: { secure: true } }), [cloudName])

  const w = 320
  const variants: Variant[] = useMemo(() => {
    const b = baseChain(cld, publicId, w)
    return [
      { key: 'baseline', label: 'Baseline', hint: 'improve · sharpen · q_auto · f_auto', img: b },
      {
        key: 'restore',
        label: 'Generative restore',
        hint: 'e_gen_restore — may be slower on first view',
        img: baseChain(cld, publicId, w).effect(generativeRestore()),
      },
      {
        key: 'upscale',
        label: 'Upscale',
        hint: 'e_upscale — Super Resolution',
        img: baseChain(cld, publicId, w).effect(upscale()),
      },
      {
        key: 'enhance',
        label: 'Enhance',
        hint: 'e_enhance + chain',
        img: baseChain(cld, publicId, w).effect(enhance()),
      },
      {
        key: 'max',
        label: 'Restore + upscale + enhance',
        hint: 'stacked AI delivery (pitch demo)',
        img: baseChain(cld, publicId, w).effect(generativeRestore()).effect(upscale()).effect(enhance()),
      },
    ]
  }, [cld, publicId])

  return (
    <section className="hp-cld-amplify">
      <div className="hp-cld-amplify-head">
        <div>
          <h2 className="hp-h2">Cloudinary — amplify &amp; AI delivery</h2>
          <p className="hp-muted-main hp-tight">
            Same <code className="hp-code">{publicId}</code> — generative restore, upscale, and enhance via URL-gen; tags from
            Cloudinary Admin API (enable auto-tagging / AI in your product for richer labels).
          </p>
        </div>
        <span className="hp-cloudinary-mark hp-cloudinary-mark--sm">CLOUDINARY</span>
      </div>

      <div className="hp-cld-amplify-tags" aria-label="Image tags">
        <span className="hp-cld-tags-title">Tags &amp; metadata</span>
        {infoErr ? (
          <p className="hp-cld-tags-err">{infoErr}</p>
        ) : info ? (
          <>
            {info.tags.length > 0 ? (
              <div className="hp-tag-row">
                {info.tags.map((t) => (
                  <span key={t} className="hp-ai-tag">
                    {t}
                  </span>
                ))}
              </div>
            ) : (
              <p className="hp-muted-main hp-tight">No tags on this asset yet — add upload presets or AI tagging in Cloudinary.</p>
            )}
            {info.width && info.height ? (
              <p className="hp-cld-meta-line">
                Stored {info.width}×{info.height}
                {info.faces != null ? ' · face metadata available' : ''}
              </p>
            ) : null}
            {info.colors && info.colors.length > 0 ? (
              <div className="hp-color-chips" aria-label="Dominant colors">
                {info.colors.slice(0, 8).map((c) => (
                  <span
                    key={c.color}
                    className="hp-color-dot"
                    style={{ background: c.color }}
                    title={`${c.color} (${c.score})`}
                  />
                ))}
              </div>
            ) : null}
          </>
        ) : (
          <p className="hp-muted-main hp-tight">Loading tags…</p>
        )}
      </div>

      <div className="hp-cld-amplify-grid">
        {variants.map((v) => (
          <figure key={v.key} className="hp-cld-variant">
            <figcaption className="hp-cld-cap">
              <strong>{v.label}</strong>
              <span className="hp-cld-cap-hint">{v.hint}</span>
              <button
                type="button"
                className="hp-btn hp-btn-outline hp-btn-tiny"
                onClick={() => window.open(v.img.toURL(), '_blank', 'noopener,noreferrer')}
              >
                Open URL
              </button>
            </figcaption>
            <AdvancedImage cldImg={v.img} alt="" className="hp-cld-variant-img" />
          </figure>
        ))}
      </div>
    </section>
  )
}
