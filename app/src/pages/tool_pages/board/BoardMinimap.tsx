// BoardMinimap.tsx — every object as a grey box plus the visible frame; click or drag to
// move the view there. Framed on the objects only and memoised on them: panning only
// moves the frame rectangle (clipped when the view is off the objects).

import { memo, useMemo, useRef } from 'react'
import { bounds, type Box } from './model'

const W = 180, H = 110

interface Props { boxes: Box[]; viewport: Box; onCenter: (x: number, y: number) => void }

const Boxes = memo(function Boxes({ boxes, k, ox, oy }: { boxes: Box[]; k: number; ox: number; oy: number }) {
  return <>{boxes.map((b, i) => <rect key={i} x={(b.x - ox) * k} y={(b.y - oy) * k}
                                      width={Math.max(1, b.w * k)} height={Math.max(1, b.h * k)} fill="var(--ink-4)" opacity={0.55} />)}</>
})

export function BoardMinimap({ boxes, viewport, onCenter }: Props) {
  const f = useMemo(() => {
    const all = bounds(boxes) ?? { x: 0, y: 0, w: 1, h: 1 }
    const pad = Math.max(all.w, all.h) * 0.1 + 40
    const k = Math.min(W / (all.w + 2 * pad), H / (all.h + 2 * pad))
    return { k, ox: all.x + all.w / 2 - W / k / 2, oy: all.y + all.h / 2 - H / k / 2 }
  }, [boxes])
  const drag = useRef(false)
  const go = (e: React.PointerEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect()
    onCenter((e.clientX - r.left) / f.k + f.ox, (e.clientY - r.top) / f.k + f.oy)
  }
  return (
    <svg width={W} height={H} onPointerDown={e => { e.stopPropagation(); drag.current = true; e.currentTarget.setPointerCapture(e.pointerId); go(e) }}
         onPointerMove={e => { if (drag.current) go(e) }} onPointerUp={() => { drag.current = false }}
         style={{ position: 'absolute', right: 10, bottom: 10, background: 'var(--paper)', border: '1px solid var(--rule)', overflow: 'hidden',
                  borderRadius: 6, boxShadow: '0 1px 3px oklch(0% 0 0 / 0.15)', cursor: 'pointer', zIndex: 5 }}>
      <Boxes boxes={boxes} k={f.k} ox={f.ox} oy={f.oy} />
      <rect x={(viewport.x - f.ox) * f.k} y={(viewport.y - f.oy) * f.k} width={viewport.w * f.k} height={viewport.h * f.k}
            fill="none" stroke="var(--accent)" strokeWidth={1.5} />
    </svg>
  )
}
