/**
 * Cloudinary delivery + upload — aligned with Cloudinary’s React Starter Kit (Beta) patterns:
 * - @cloudinary/url-gen + @cloudinary/react (AdvancedImage)
 * - Unsigned upload widget (global all.js)
 * - Transformations: fill + auto gravity (smart crop), improve, optional sharpen
 *
 * Docs: https://cloudinary.com/documentation/react_integration
 * Starter kit: npx create-cloudinary-react
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { AdvancedImage } from '@cloudinary/react'
import { Cloudinary } from '@cloudinary/url-gen'
import { fill } from '@cloudinary/url-gen/actions/resize'
import { autoGravity } from '@cloudinary/url-gen/qualifiers/gravity'
import { improve } from '@cloudinary/url-gen/actions/adjust'
import { sharpen } from '@cloudinary/url-gen/actions/adjust'

declare global {
  interface Window {
    cloudinary?: {
      createUploadWidget: (
        options: Record<string, unknown>,
        callback: (
          error: unknown,
          result: {
            event?: string
            info?: { public_id?: string; secure_url?: string; width?: number; height?: number }
          }
        ) => void
      ) => { open: () => void }
    }
  }
}

const CLOUD_NAME = import.meta.env.VITE_CLOUDINARY_CLOUD_NAME as string | undefined
const UPLOAD_PRESET = import.meta.env.VITE_CLOUDINARY_UPLOAD_PRESET as string | undefined

const AI_PROMPTS = [
  'Add @cloudinary/react video player below the images using cld.video() and AdvancedVideo.',
  'Chain delivery quality auto: use quality from @cloudinary/url-gen/actions/delivery with auto on the smart-crop image.',
  'Add a second upload folder homepulse/alerts and show the last 3 public_ids as thumbnail AdvancedImages.',
  'Replace sharpen with unsharpMask for alert thumbnails to match backend Cloudinary e_sharpen:80 style.',
] as const

export function CloudinaryPlayground() {
  const [widgetReady, setWidgetReady] = useState(Boolean(window.cloudinary))
  const [publicId, setPublicId] = useState('')
  const [lastInfo, setLastInfo] = useState<string>('')
  const [copyMsg, setCopyMsg] = useState('')

  const cld = useMemo(() => {
    if (!CLOUD_NAME) return null
    return new Cloudinary({ cloud: { cloudName: CLOUD_NAME }, url: { secure: true } })
  }, [])

  useEffect(() => {
    if (window.cloudinary) return
    const script = document.createElement('script')
    script.src = 'https://widget.cloudinary.com/v2.0/global/all.js'
    script.async = true
    script.onload = () => setWidgetReady(true)
    document.body.appendChild(script)
  }, [])

  const smartCropImg = useMemo(() => {
    if (!cld || !publicId) return null
    // Starter-kit style: fill + g_auto keeps the important region in frame
    return cld
      .image(publicId)
      .resize(fill().width(720).height(405).gravity(autoGravity()))
      .adjust(improve())
      .adjust(sharpen(80))
  }, [cld, publicId])

  const plainFillImg = useMemo(() => {
    if (!cld || !publicId) return null
    return cld.image(publicId).resize(fill().width(720).height(405))
  }, [cld, publicId])

  const openWidget = useCallback(() => {
    if (!window.cloudinary || !CLOUD_NAME || !UPLOAD_PRESET) return
    const widget = window.cloudinary.createUploadWidget(
      {
        cloudName: CLOUD_NAME,
        uploadPreset: UPLOAD_PRESET,
        multiple: false,
        sources: ['local', 'camera', 'url'],
        folder: 'homepulse/raw',
        clientAllowedFormats: ['jpg', 'jpeg', 'png', 'webp', 'gif'],
        maxImageFileSize: 12_000_000,
      },
      (error, result) => {
        if (error || !result) return
        if (result.event === 'success' && result.info?.public_id) {
          setPublicId(result.info.public_id)
          const u = result.info.secure_url ?? ''
          const w = result.info.width ?? '?'
          const h = result.info.height ?? '?'
          setLastInfo(`${u}\n(${w}×${h})`)
        }
      }
    )
    widget.open()
  }, [])

  const copyPrompt = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopyMsg('Copied to clipboard.')
      setTimeout(() => setCopyMsg(''), 2000)
    } catch {
      setCopyMsg('Could not copy — select manually.')
    }
  }

  const configured = Boolean(CLOUD_NAME && UPLOAD_PRESET)

  return (
    <div className="cld-playground">
      <section className="card">
        <h2>Cloudinary — React SDK (Starter Kit patterns)</h2>
        <p className="hint">
          Same stack as <code>npx create-cloudinary-react</code>:{' '}
          <strong>@cloudinary/react</strong> + <strong>@cloudinary/url-gen</strong> + upload widget. Use an{' '}
          <strong>unsigned upload preset</strong> in the Cloudinary Console (Upload → Upload presets → Signing mode:
          Unsigned).
        </p>
        <ul className="cld-checklist">
          <li>
            <strong>Cloud name:</strong> {CLOUD_NAME || <span className="warn-inline">set VITE_CLOUDINARY_CLOUD_NAME</span>}
          </li>
          <li>
            <strong>Unsigned preset:</strong>{' '}
            {UPLOAD_PRESET || <span className="warn-inline">set VITE_CLOUDINARY_UPLOAD_PRESET</span>}
          </li>
        </ul>
        <button type="button" onClick={openWidget} disabled={!widgetReady || !configured}>
          Upload image (widget)
        </button>
        {!configured && (
          <p className="warn">Add both variables to <code>frontend/.env.local</code> — see <code>frontend/.env.example</code>.</p>
        )}
        {publicId && (
          <p className="mono cld-pid">
            <strong>public_id:</strong> {publicId}
          </p>
        )}
        {lastInfo && (
          <pre className="out small cld-url">{lastInfo}</pre>
        )}
      </section>

      {publicId && smartCropImg && plainFillImg && (
        <section className="card">
          <h2>Delivery — transformations</h2>
          <p className="hint">
            <strong>Left:</strong> <code>fill</code> + <code>g_auto</code> + <code>e_improve</code> +{' '}
            <code>e_sharpen:80</code> (matches HomePulse alert-style tuning).{' '}
            <strong>Right:</strong> plain <code>fill</code> only — compare crop focus.
          </p>
          <div className="cld-grid">
            <figure>
              <figcaption>Smart crop (auto gravity)</figcaption>
              <div className="preview">
                <AdvancedImage cldImg={smartCropImg} alt="Smart crop" />
              </div>
            </figure>
            <figure>
              <figcaption>Fill only (no gravity)</figcaption>
              <div className="preview">
                <AdvancedImage cldImg={plainFillImg} alt="Plain fill" />
              </div>
            </figure>
          </div>
        </section>
      )}

      <section className="card">
        <h2>AI assistant prompts (from Starter Kit “Explore”)</h2>
        <p className="hint">Click to copy, then paste into Cursor / Copilot / Claude.</p>
        <ul className="cld-prompts">
          {AI_PROMPTS.map((p) => (
            <li key={p}>
              <button type="button" className="prompt-chip" onClick={() => copyPrompt(p)}>
                Copy prompt
              </button>
              <span>{p}</span>
            </li>
          ))}
        </ul>
        {copyMsg && <p className="ok-msg">{copyMsg}</p>}
      </section>
    </div>
  )
}
