import { useEffect, useState } from 'react'
import { AdvancedImage } from '@cloudinary/react'
import { Cloudinary } from '@cloudinary/url-gen'
import { fill } from '@cloudinary/url-gen/actions/resize'

declare global {
  interface Window {
    cloudinary?: {
      createUploadWidget: (
        options: Record<string, unknown>,
        callback: (
          error: unknown,
          result: { event?: string; info?: { public_id?: string; secure_url?: string } }
        ) => void
      ) => { open: () => void }
    }
  }
}

const cloudName = import.meta.env.VITE_CLOUDINARY_CLOUD_NAME
const unsignedPreset = import.meta.env.VITE_CLOUDINARY_UPLOAD_PRESET
const signedPreset = import.meta.env.VITE_CLOUDINARY_SIGNED_PRESET

const cld = new Cloudinary({
  cloud: { cloudName },
  url: { secure: true },
})

function App() {
  const [widgetReady, setWidgetReady] = useState(Boolean(window.cloudinary))
  const [publicId, setPublicId] = useState<string>('')

  useEffect(() => {
    if (window.cloudinary) return

    const script = document.createElement('script')
    script.src = 'https://widget.cloudinary.com/v2.0/global/all.js'
    script.async = true
    script.onload = () => setWidgetReady(true)
    document.body.appendChild(script)
  }, [])

  const previewImage = publicId
    ? cld.image(publicId).resize(fill().width(720).height(420))
    : null

  function openUnsignedWidget() {
    if (!window.cloudinary || !unsignedPreset) return

    const widget = window.cloudinary.createUploadWidget(
      {
        cloudName,
        uploadPreset: unsignedPreset,
        multiple: false,
        sources: ['local', 'camera', 'url'],
        folder: 'homepulse/raw',
      },
      (error, result) => {
        if (error || !result) return
        if (result.event === 'success' && result.info?.public_id) {
          setPublicId(result.info.public_id)
        }
      }
    )

    widget.open()
  }

  const isConfigured = Boolean(cloudName && unsignedPreset)

  return (
    <main className="page">
      <h1>Cloudinary React Base</h1>
      <p className="subtitle">
        Fresh starter base is ready. Unsigned uploads run in frontend, and signed preset is saved for backend flow.
      </p>

      <section className="card">
        <p><strong>Cloud name:</strong> {cloudName || 'missing'}</p>
        <p><strong>Unsigned preset:</strong> {unsignedPreset || 'missing'}</p>
        <p><strong>Signed preset:</strong> {signedPreset || 'missing'}</p>
        <button onClick={openUnsignedWidget} disabled={!widgetReady || !isConfigured}>
          Upload (unsigned)
        </button>
        {!isConfigured && (
          <p className="warn">
            Set `VITE_CLOUDINARY_CLOUD_NAME` and `VITE_CLOUDINARY_UPLOAD_PRESET` in `frontend/.env.local`.
          </p>
        )}
      </section>

      <section className="card">
        <h2>Preview</h2>
        {previewImage ? (
          <AdvancedImage cldImg={previewImage} />
        ) : (
          <p className="muted">Upload an image to verify the pipeline.</p>
        )}
      </section>
    </main>
  )
}

export default App
