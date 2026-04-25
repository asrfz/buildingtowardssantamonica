import { useRef, useState, useEffect, useCallback } from 'react'
import { AdvancedImage } from '@cloudinary/react'
import type { ZoneBounds, ZoneName, ZoneMap } from '../types'
import { referencePublicId } from '../types'
import { buildCalibrationFrame, ZONE_COLORS, ZONE_LABELS } from '../cloudinary/transformations'
import { captureReferenceFrame, saveZones, fetchZones } from '../api/homepulse'

// Webcam capture resolution — must match what vision_service captures at
const FRAME_W = 640
const FRAME_H = 480

const ZONE_ORDER: ZoneName[] = ['stove', 'sink', 'fridge']

interface ZoneCalibratorProps {
  userId: string
}

interface DrawState {
  startX: number
  startY: number
  currentX: number
  currentY: number
}

export function ZoneCalibrator({ userId }: ZoneCalibratorProps) {
  const canvasRef   = useRef<HTMLCanvasElement>(null)
  const imgRef      = useRef<HTMLImageElement>(null)

  const [zones, setZones]               = useState<ZoneMap>({})
  const [activeZone, setActiveZone]     = useState<ZoneName>('stove')
  const [drawing, setDrawing]           = useState(false)
  const [drawState, setDrawState]       = useState<DrawState | null>(null)
  const [referenceUrl, setReferenceUrl] = useState<string | null>(null)
  const [status, setStatus]             = useState<string>('Load a reference frame to begin.')
  const [saving, setSaving]             = useState(false)
  const [capturing, setCapturing]       = useState(false)

  // Scale factor: canvas display size vs actual frame size
  const DISPLAY_W = 640  // match 1:1 for simplicity
  const DISPLAY_H = 480
  const scaleX = FRAME_W / DISPLAY_W
  const scaleY = FRAME_H / DISPLAY_H

  // Load existing zones on mount
  useEffect(() => {
    fetchZones(userId)
      .then(setZones)
      .catch(() => {/* no zones yet is fine */})
  }, [userId])

  // Redraw canvas whenever zones or draw state changes
  useEffect(() => {
    drawCanvas()
  }, [zones, drawState, activeZone])

  function drawCanvas() {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    ctx.clearRect(0, 0, canvas.width, canvas.height)

    // Draw saved zones
    for (const [zoneName, bounds] of Object.entries(zones)) {
      if (!bounds) continue
      const color = ZONE_COLORS[zoneName] ?? '#6b7280'
      const { x, y, w, h } = bounds

      // Scale from frame coords to display coords
      const dx = x / scaleX
      const dy = y / scaleY
      const dw = w / scaleX
      const dh = h / scaleY

      ctx.fillStyle = `${color}33`
      ctx.fillRect(dx, dy, dw, dh)
      ctx.strokeStyle = color
      ctx.lineWidth = 2
      ctx.strokeRect(dx, dy, dw, dh)

      // Zone label
      ctx.fillStyle = color
      ctx.font = 'bold 13px Inter, sans-serif'
      ctx.fillText(ZONE_LABELS[zoneName] ?? zoneName, dx + 6, dy + 18)
    }

    // Draw in-progress rectangle
    if (drawing && drawState) {
      const { startX, startY, currentX, currentY } = drawState
      const x = Math.min(startX, currentX)
      const y = Math.min(startY, currentY)
      const w = Math.abs(currentX - startX)
      const h = Math.abs(currentY - startY)
      const color = ZONE_COLORS[activeZone]

      ctx.fillStyle = `${color}44`
      ctx.fillRect(x, y, w, h)
      ctx.strokeStyle = color
      ctx.lineWidth = 2
      ctx.setLineDash([6, 3])
      ctx.strokeRect(x, y, w, h)
      ctx.setLineDash([])

      // Dimensions label
      const frameW = Math.round(w * scaleX)
      const frameH = Math.round(h * scaleY)
      ctx.fillStyle = color
      ctx.font = '11px Inter, sans-serif'
      ctx.fillText(`${frameW}×${frameH}px`, x + 4, y - 4)
    }
  }

  function getCanvasCoords(e: React.MouseEvent<HTMLCanvasElement>): { x: number; y: number } {
    const canvas = canvasRef.current!
    const rect = canvas.getBoundingClientRect()
    return {
      x: e.clientX - rect.left,
      y: e.clientY - rect.top,
    }
  }

  function onMouseDown(e: React.MouseEvent<HTMLCanvasElement>) {
    const { x, y } = getCanvasCoords(e)
    setDrawing(true)
    setDrawState({ startX: x, startY: y, currentX: x, currentY: y })
  }

  function onMouseMove(e: React.MouseEvent<HTMLCanvasElement>) {
    if (!drawing || !drawState) return
    const { x, y } = getCanvasCoords(e)
    setDrawState(prev => prev ? { ...prev, currentX: x, currentY: y } : prev)
  }

  function onMouseUp(e: React.MouseEvent<HTMLCanvasElement>) {
    if (!drawing || !drawState) return
    const { startX, startY, currentX, currentY } = drawState

    const x = Math.round(Math.min(startX, currentX) * scaleX)
    const y = Math.round(Math.min(startY, currentY) * scaleY)
    const w = Math.round(Math.abs(currentX - startX) * scaleX)
    const h = Math.round(Math.abs(currentY - startY) * scaleY)

    if (w < 20 || h < 20) {
      setStatus('Rectangle too small — draw a larger area.')
      setDrawing(false)
      setDrawState(null)
      return
    }

    const newZone: ZoneBounds = { x, y, w, h }
    setZones(prev => ({ ...prev, [activeZone]: newZone }))
    setStatus(`${ZONE_LABELS[activeZone]} zone set to x:${x} y:${y} w:${w} h:${h}`)
    setDrawing(false)
    setDrawState(null)

    // Auto-advance to next zone
    const idx = ZONE_ORDER.indexOf(activeZone)
    if (idx < ZONE_ORDER.length - 1) {
      setActiveZone(ZONE_ORDER[idx + 1])
    }
  }

  async function handleCapture() {
    setCapturing(true)
    setStatus('Capturing reference frame from webcam…')
    try {
      const result = await captureReferenceFrame()
      setReferenceUrl(result.url)
      setStatus('Reference frame loaded. Draw rectangles to define zones.')
    } catch (e: any) {
      setStatus(`Capture failed: ${e.message}`)
    } finally {
      setCapturing(false)
    }
  }

  async function handleSave() {
    if (Object.keys(zones).length === 0) {
      setStatus('No zones defined yet — draw at least one zone.')
      return
    }
    setSaving(true)
    setStatus('Saving zones…')
    try {
      await saveZones(userId, zones)
      setStatus(`✅ Zones saved! (${Object.keys(zones).join(', ')}) — agents will use these coordinates.`)
    } catch (e: any) {
      setStatus(`Save failed: ${e.message}`)
    } finally {
      setSaving(false)
    }
  }

  function handleClearZone(zone: ZoneName) {
    setZones(prev => {
      const next = { ...prev }
      delete next[zone]
      return next
    })
    setStatus(`${ZONE_LABELS[zone]} zone cleared.`)
  }

  // Use the Cloudinary reference image or a raw URL
  const calibrationImg = buildCalibrationFrame(referencePublicId())

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <div>
        <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700 }}>Zone Calibrator</h2>
        <p style={{ margin: '4px 0 0', color: '#6b7280', fontSize: 14 }}>
          Draw rectangles on the camera frame to map where each zone (stove, sink, fridge) is.
          These coordinates are used to zoom into the right spot when an alert fires.
        </p>
      </div>

      {/* Controls row */}
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <button onClick={handleCapture} disabled={capturing} style={btnStyle('#2563eb')}>
          {capturing ? 'Capturing…' : '📷 Capture Reference Frame'}
        </button>

        <div style={{ display: 'flex', gap: 8 }}>
          {ZONE_ORDER.map(zone => (
            <button
              key={zone}
              onClick={() => setActiveZone(zone)}
              style={{
                ...btnStyle(ZONE_COLORS[zone]),
                opacity: activeZone === zone ? 1 : 0.5,
                outline: activeZone === zone ? `2px solid ${ZONE_COLORS[zone]}` : 'none',
                outlineOffset: 2,
              }}
            >
              {ZONE_LABELS[zone]}
            </button>
          ))}
        </div>

        <button
          onClick={handleSave}
          disabled={saving || Object.keys(zones).length === 0}
          style={btnStyle('#16a34a')}
        >
          {saving ? 'Saving…' : '💾 Save Zones'}
        </button>
      </div>

      {/* Status */}
      <div style={{
        padding: '10px 14px',
        background: '#f3f4f6',
        borderRadius: 6,
        fontSize: 13,
        color: '#374151',
        borderLeft: `3px solid ${ZONE_COLORS[activeZone]}`,
      }}>
        {status}
      </div>

      {/* Canvas over reference image */}
      <div style={{ position: 'relative', display: 'inline-block', lineHeight: 0 }}>
        {/* Background: reference image */}
        {referenceUrl ? (
          <img
            ref={imgRef}
            src={referenceUrl}
            alt="Reference frame"
            width={DISPLAY_W}
            height={DISPLAY_H}
            style={{ display: 'block', borderRadius: 8, border: '1px solid #e5e7eb' }}
          />
        ) : (
          <div style={{
            width: DISPLAY_W,
            height: DISPLAY_H,
            background: '#111827',
            borderRadius: 8,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#4b5563',
            fontSize: 15,
          }}>
            Capture a reference frame to begin calibration
          </div>
        )}

        {/* Canvas overlay for drawing */}
        <canvas
          ref={canvasRef}
          width={DISPLAY_W}
          height={DISPLAY_H}
          onMouseDown={onMouseDown}
          onMouseMove={onMouseMove}
          onMouseUp={onMouseUp}
          onMouseLeave={() => { if (drawing) { setDrawing(false); setDrawState(null) } }}
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            cursor: referenceUrl ? 'crosshair' : 'not-allowed',
            borderRadius: 8,
          }}
        />
      </div>

      {/* Zone summary + clear buttons */}
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        {ZONE_ORDER.map(zone => {
          const bounds = zones[zone]
          const color = ZONE_COLORS[zone]
          return (
            <div key={zone} style={{
              padding: '10px 14px',
              borderRadius: 8,
              border: `1px solid ${bounds ? color : '#e5e7eb'}`,
              background: bounds ? `${color}11` : '#f9fafb',
              minWidth: 160,
            }}>
              <div style={{ fontWeight: 600, color: bounds ? color : '#9ca3af', fontSize: 13 }}>
                {ZONE_LABELS[zone]}
              </div>
              {bounds ? (
                <>
                  <div style={{ fontSize: 12, color: '#6b7280', marginTop: 4 }}>
                    x:{bounds.x} y:{bounds.y} {bounds.w}×{bounds.h}px
                  </div>
                  <button
                    onClick={() => handleClearZone(zone)}
                    style={{ marginTop: 6, fontSize: 11, color: '#ef4444', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
                  >
                    ✕ Clear
                  </button>
                </>
              ) : (
                <div style={{ fontSize: 12, color: '#9ca3af', marginTop: 4 }}>Not set</div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function btnStyle(color: string): React.CSSProperties {
  return {
    background: color,
    color: '#fff',
    border: 'none',
    borderRadius: 6,
    padding: '8px 14px',
    fontSize: 13,
    fontWeight: 600,
    cursor: 'pointer',
    transition: 'opacity 0.15s',
  }
}
