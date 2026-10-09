import { useEffect, useRef, useState } from 'react'
import { ChevronsRight } from 'lucide-react'

// Slide-to-confirm control (closing FLUX, Production unlock / archive). The handle must be
// dragged to the end of the track; released earlier it snaps back. `width: 'fill'` takes
// the width of the parent (side panels), otherwise a fixed width in px (default 300).
export function SlideToConfirm({ label, onConfirm, width = 300, height = 50, tone = 'accent', disabled = false }: {
  label:     string
  onConfirm: () => void | Promise<unknown>
  width?:   number | 'fill'
  height?:   number
  tone?:     'accent' | 'danger'
  disabled?: boolean
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [measured, setMeasured] = useState(0)
  useEffect(() => {
    if (width !== 'fill' || !ref.current) return
    const el = ref.current
    const ro = new ResizeObserver(() => setMeasured(el.clientWidth))
    ro.observe(el)
    setMeasured(el.clientWidth)
    return () => ro.disconnect()
  }, [width])

  const trackW = width === 'fill' ? measured : width
  const handleW = height
  const maxX = Math.max(trackW - handleW - 6, 0)
  const [x, setX] = useState(0)
  const [done, setDone] = useState(false)

  const startDrag = (e: React.MouseEvent) => {
    if (disabled || done) return
    e.preventDefault()
    const origin = e.clientX - x
    const move = (ev: MouseEvent) => setX(Math.min(Math.max(ev.clientX - origin, 0), maxX))
    const up = (ev: MouseEvent) => {
      document.removeEventListener('mousemove', move)
      document.removeEventListener('mouseup', up)
      const nx = Math.min(Math.max(ev.clientX - origin, 0), maxX)
      if (maxX > 0 && nx >= maxX - 4) {
        setX(maxX); setDone(true)
        setTimeout(() => {
          // A promise-returning action snaps the handle back once settled (e.g. backend
          // refused), so the user can slide again; a void action keeps it at the end.
          const r = onConfirm()
          if (r instanceof Promise)
            void r.catch(() => {}).finally(() => { setX(0); setDone(false) })
        }, 120)
      }
      else setX(0)
    }
    document.addEventListener('mousemove', move)
    document.addEventListener('mouseup', up)
  }

  const danger = tone === 'danger'
  const pct = maxX > 0 ? x / maxX : 0
  const radius = height / 2
  return (
    <div ref={ref} role="slider" aria-label={label} aria-valuemin={0} aria-valuemax={100}
      aria-valuenow={Math.round(pct * 100)} aria-disabled={disabled || undefined}
      style={{
        position: 'relative', width: width === 'fill' ? '100%' : width, height, borderRadius: radius,
        background: 'var(--bg-deep)', border: '1px solid var(--rule-2)',
        boxShadow: 'var(--shadow-inset)', overflow: 'hidden', userSelect: 'none',
        opacity: disabled ? 0.5 : 1, boxSizing: width === 'fill' ? 'border-box' : undefined,
      }}>
      <div style={{
        position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: height < 44 ? 11 : 12, color: 'var(--ink-4)', opacity: 1 - pct, pointerEvents: 'none',
        whiteSpace: 'nowrap',
      }}>
        {label}
      </div>
      <div style={{
        position: 'absolute', top: 0, bottom: 0, left: 0, width: x + handleW,
        background: danger ? 'color-mix(in oklch, var(--err) 22%, transparent)' : 'var(--accent-soft)',
        borderRadius: radius, transition: done ? 'width 0.12s' : 'none',
      }} />
      <div
        onMouseDown={startDrag}
        style={{
          position: 'absolute', top: 3, left: x + 3, width: handleW - 6, height: height - 6,
          borderRadius: '50%', background: danger ? 'var(--err)' : 'var(--accent)',
          cursor: disabled ? 'not-allowed' : 'grab',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          boxShadow: 'var(--shadow-sm)', transition: x === 0 && !done ? 'left 0.12s' : 'none',
        }}
      >
        <ChevronsRight size={height < 44 ? 15 : 18} strokeWidth={2.5} color={danger ? '#fff' : 'var(--accent-hi)'} />
      </div>
    </div>
  )
}
