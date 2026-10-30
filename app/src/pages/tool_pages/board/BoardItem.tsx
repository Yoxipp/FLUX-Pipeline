// BoardItem.tsx — one object of the board and one link, memoised (ADR 0071 n°2): a drag
// re-renders only what moves. Geometry comes in as plain numbers, handlers are stable.
// v3 (ADR 0074): a frame (tinted area, name above it), a stroke (`ink`, only its line takes
// the pointer), a FLUX card (FluxCard.tsx, read from Production through a context).

import { memo, type PointerEvent as RPointerEvent } from 'react'
import { Lock } from 'lucide-react'
import { FluxCardBody } from './FluxCard'
import { edgePoint, fillOf, fontOf, strokeOf, type Box, type Item } from './model'

export type Corner = 'nw' | 'ne' | 'sw' | 'se'
export interface ItemHandlers {
  down: (e: RPointerEvent, rid: string) => void
  double: (rid: string) => void
  commitText: (rid: string, text: string) => void
  stopEdit: () => void
  resize: (e: RPointerEvent, rid: string, corner: Corner) => void
}

interface ItemProps {
  it: Item; x: number; y: number; w: number; h: number
  selected: boolean; handles: boolean; editing: boolean; linkSource: boolean; match: boolean
  canEdit: boolean; mediaUrl?: string; placeholder: string; on: ItemHandlers; faded?: boolean
}

const INK = 'oklch(25% 0.02 250)'
const CORNERS: Corner[] = ['nw', 'ne', 'sw', 'se']

function shapeSvg(it: Item, w: number, h: number) {
  const fill = fillOf(it), stroke = strokeOf(it, 'ink'), sw = 1.5
  const common = { fill, stroke, strokeWidth: sw, vectorEffect: 'non-scaling-stroke' as const }
  const s = it.shape ?? 'rect'
  return (
    <svg width={w} height={h} style={{ position: 'absolute', inset: 0, overflow: 'visible' }}>
      {s === 'ellipse' ? <ellipse cx={w / 2} cy={h / 2} rx={w / 2} ry={h / 2} {...common} />
        : s === 'diamond' ? <polygon points={`${w / 2},0 ${w},${h / 2} ${w / 2},${h} 0,${h / 2}`} {...common} />
        : <rect x={0} y={0} width={w} height={h} rx={s === 'round' ? Math.min(16, h / 4) : 2} {...common} />}
    </svg>
  )
}

export const BoardItem = memo(function BoardItem(p: ItemProps) {
  const { it, x, y, w, h, on } = p
  const type = it.type ?? 'note'
  const title = `${it._created_by}${it._by && it._by !== it._created_by ? ` / ${it._by}` : ''}`
  const ring = p.selected ? '2px solid var(--accent)' : p.match ? '2px solid oklch(70% 0.15 60)' : undefined
  if (type === 'ink') {
    const color = strokeOf(it, 'ink'), sw = it.stroke_width ?? 3, pts = it.points ?? ''
    return (
      <div title={title} style={{ position: 'absolute', left: x, top: y, width: w, height: h, zIndex: 1, pointerEvents: 'none',
                                  outline: ring, outlineOffset: sw / 2 + 2, opacity: p.faded ? 0.25 : 1 }}>
        <svg width={w} height={h} style={{ position: 'absolute', inset: 0, overflow: 'visible' }}>
          <polyline points={pts} fill="none" stroke={color} strokeWidth={sw} strokeLinecap={it.highlight ? 'butt' : 'round'}
                    strokeLinejoin="round" opacity={it.highlight ? 0.4 : 1} />
          <polyline points={pts} fill="none" stroke="transparent" strokeWidth={sw + 10} style={{ pointerEvents: 'stroke', cursor: 'pointer' }}
                    onPointerDown={e => on.down(e, it.rid)} />
        </svg>
      </div>
    )
  }
  if (type === 'frame') {
    return (
      <div onPointerDown={e => on.down(e, it.rid)} onDoubleClick={e => { e.stopPropagation(); on.double(it.rid) }} title={title}
           style={{ position: 'absolute', left: x, top: y, width: w, height: h, zIndex: 0, boxSizing: 'border-box', borderRadius: 4,
                    background: `color-mix(in oklch, ${fillOf(it)} 30%, transparent)`, border: '1px solid var(--rule-2)',
                    outline: ring, outlineOffset: 1, pointerEvents: 'auto', cursor: p.canEdit && !it.locked ? 'grab' : 'default' }}>
        <div style={{ position: 'absolute', left: 0, bottom: '100%', marginBottom: 4, fontSize: 13, color: 'var(--ink-2)',
                      whiteSpace: 'nowrap', fontWeight: 600 }}>
          {editing(p)
            ? <input autoFocus defaultValue={it.text ?? ''} onPointerDown={e => e.stopPropagation()}
                     onBlur={e => { on.stopEdit(); if (e.target.value !== (it.text ?? '')) on.commitText(it.rid, e.target.value) }}
                     onKeyDown={e => { e.stopPropagation(); if (e.key === 'Escape' || e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
                     style={{ font: 'inherit', color: 'var(--ink)', background: 'var(--paper)', border: '1px solid var(--rule-2)', borderRadius: 3, padding: '0 4px' }} />
            : it.text || p.placeholder}
        </div>
        {it.locked && p.selected && <Lock size={12} style={{ position: 'absolute', right: 4, top: 4, color: 'var(--ink-3)' }} />}
        {p.handles && handles(it, on)}
      </div>
    )
  }
  const isShape = type === 'shape', isImage = type === 'image', isText = type === 'text', isFlux = type === 'flux'
  const font = fontOf(it)
  const centred = isShape
  const outline = p.selected ? '2px solid var(--accent)' : p.linkSource ? '2px dashed var(--accent)'
    : p.match ? '2px solid oklch(70% 0.15 60)' : undefined
  const border = isShape || isImage || isText ? 'none'
    : it.stroke && it.stroke !== 'none' ? `1.5px solid ${strokeOf(it)}` : '1px solid oklch(70% 0.02 250 / 0.5)'
  const text = editing(p)
    ? <textarea autoFocus defaultValue={it.text ?? ''} onPointerDown={e => e.stopPropagation()}
                onBlur={e => { on.stopEdit(); if (e.target.value !== (it.text ?? '')) on.commitText(it.rid, e.target.value) }}
                onKeyDown={e => { e.stopPropagation(); if (e.key === 'Escape') (e.target as HTMLTextAreaElement).blur() }}
                style={{ width: '100%', minHeight: Math.max(20, h - 20), border: 'none', outline: 'none', background: 'transparent',
                         color: 'inherit', font: 'inherit', resize: 'none', textAlign: centred ? 'center' : 'left', padding: 0 }} />
    : (it.text || <span style={{ opacity: 0.45 }}>{p.canEdit && !it.locked ? p.placeholder : ''}</span>)
  return (
    <div onPointerDown={e => on.down(e, it.rid)}
         onDoubleClick={e => { e.stopPropagation(); on.double(it.rid) }}
         title={title}
         style={{ position: 'absolute', left: x, top: y, width: w, zIndex: 1,
                  height: isShape || isImage || isFlux ? h : undefined, minHeight: isShape || isImage || isFlux ? undefined : h,
                  background: isShape || isImage ? 'transparent' : fillOf(it), border, outline, outlineOffset: 1,
                  borderRadius: type === 'note' ? 2 : 6, padding: isImage ? 0 : isFlux ? 8 : 10,
                  // No fill: the text sits on the board itself and follows the theme.
                  color: fillOf(it) === 'transparent' ? 'var(--ink)' : INK,
                  boxShadow: type === 'note' || type === 'card' || isFlux ? '0 1px 2px oklch(0% 0 0 / 0.12)' : undefined,
                  overflow: isFlux ? 'hidden' : undefined,
                  pointerEvents: 'auto', cursor: p.canEdit && !it.locked ? 'grab' : 'default',
                  fontSize: font, fontWeight: it.bold ? 650 : undefined, lineHeight: 1.35, whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word', userSelect: 'none', boxSizing: 'border-box',
                  display: centred ? 'flex' : undefined, alignItems: 'center', justifyContent: 'center', textAlign: centred ? 'center' : undefined }}>
      {isShape && shapeSvg(it, w, h)}
      {isImage
        ? (p.mediaUrl ? <img src={p.mediaUrl} alt="" draggable={false} loading="lazy" decoding="async"
                             style={{ width: '100%', height: '100%', objectFit: 'contain', display: 'block', borderRadius: 6 }} /> : null)
        : isFlux ? <FluxCardBody fluxRef={it.ref} />
        : <div style={{ position: 'relative', width: '100%' }}>{text}</div>}
      {it.locked && p.selected && <Lock size={12} style={{ position: 'absolute', right: -16, top: -2, color: 'var(--ink-3)' }} />}
      {p.handles && handles(it, on)}
    </div>
  )
})

function handles(it: Item, on: ItemHandlers) {
  return CORNERS.map(c => (
    <span key={c} onPointerDown={e => on.resize(e, it.rid, c)}
          style={{ position: 'absolute', width: 9, height: 9, background: 'var(--paper)', border: '1.5px solid var(--accent)', borderRadius: 2,
                   left: c[1] === 'w' ? -6 : undefined, right: c[1] === 'e' ? -6 : undefined,
                   top: c[0] === 'n' ? -6 : undefined, bottom: c[0] === 's' ? -6 : undefined,
                   cursor: c === 'nw' || c === 'se' ? 'nwse-resize' : 'nesw-resize' }} />
  ))
}

function editing(p: ItemProps) { return p.editing && !p.it.locked && !['image', 'ink', 'flux'].includes(p.it.type ?? '') }

interface LinkProps {
  it: Item; a: Box; b: Box; aShape?: Item['shape']; bShape?: Item['shape']
  selected: boolean; onDown: (e: RPointerEvent, rid: string) => void
}

function arrowHead(x: number, y: number, fx: number, fy: number, size: number) {
  const ang = Math.atan2(y - fy, x - fx)
  const p = (da: number) => `${x - size * Math.cos(ang + da)},${y - size * Math.sin(ang + da)}`
  return `${x},${y} ${p(0.45)} ${p(-0.45)}`
}

export const BoardLink = memo(function BoardLink({ it, a, b, aShape, bShape, selected, onDown }: LinkProps) {
  const pa = edgePoint(a, aShape, b.x + b.w / 2, b.y + b.h / 2)
  const pb = edgePoint(b, bShape, a.x + a.w / 2, a.y + a.h / 2)
  const color = selected ? 'var(--accent)' : strokeOf(it, 'grey')
  const width = selected ? 2.5 : 1.5
  const dash = it.dash === 'dashed' ? '8 5' : it.dash === 'dotted' ? '2 4' : undefined
  const mx = (pa.x + pb.x) / 2, my = (pa.y + pb.y) / 2
  const label = it.label ?? ''
  return (
    <g>
      <line x1={pa.x} y1={pa.y} x2={pb.x} y2={pb.y} stroke={color} strokeWidth={width} strokeDasharray={dash} />
      {it.arrow_end && <polygon points={arrowHead(pb.x, pb.y, pa.x, pa.y, 11)} fill={color} />}
      {it.arrow_start && <polygon points={arrowHead(pa.x, pa.y, pb.x, pb.y, 11)} fill={color} />}
      <line x1={pa.x} y1={pa.y} x2={pb.x} y2={pb.y} stroke="transparent" strokeWidth={12}
            style={{ pointerEvents: 'stroke', cursor: 'pointer' }} onPointerDown={e => onDown(e, it.rid)} />
      {label && <g style={{ pointerEvents: 'auto', cursor: 'pointer' }} onPointerDown={e => onDown(e, it.rid)}>
        <rect x={mx - label.length * 3.4 - 6} y={my - 10} width={label.length * 6.8 + 12} height={20} rx={4}
              fill="var(--paper)" stroke={color} strokeWidth={1} />
        <text x={mx} y={my + 4} textAnchor="middle" fontSize={12} fill="var(--ink)">{label}</text>
      </g>}
    </g>
  )
})
