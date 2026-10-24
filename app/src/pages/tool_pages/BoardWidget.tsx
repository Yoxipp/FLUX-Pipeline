// BoardWidget.tsx — the Miro-like board (ADR 0066 n°1): a free surface INSIDE its row of
// the page grid. Cards, notes and images placed freely, links between them, pan and zoom.
// Every item is a record of a `kind: board` collection (fixed fields: type x y w h text
// color image from to), written to the author's own journal: two people moving and
// retyping the same note both keep their change (per field merge, page_data.py).
// The view (pan, zoom) is per viewer and never written. Images are copied by the backend
// from a local file (ADR 0005), shown through the media route.
//
// Mouse: drag the background = pan, wheel = zoom at the cursor, drag a card = move,
// double click the background = new note, double click a card = edit its text,
// "Lier" then two cards = a link, Suppr = delete the selection.

import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as RPointerEvent, type WheelEvent } from 'react'
import { ImagePlus, Link2, Maximize, Minus, Plus, StickyNote, Square, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { flowsApi } from '../../api/flows'
import { usePageData } from '../../hooks/usePages'
import type { PageRecord } from '../flow_editor/types'
import { useTr } from '../flow_editor/useTr'
import type { DataWidgetProps } from './DataWidgets'

// Flat, muted fills (no glow). Text stays dark on them in both themes.
const COLORS: Record<string, string> = {
  yellow: 'oklch(90% 0.07 95)', green: 'oklch(88% 0.06 150)', blue: 'oklch(88% 0.05 240)',
  pink: 'oklch(88% 0.06 0)', grey: 'oklch(90% 0.01 250)', white: 'oklch(98% 0 0)',
}
const SIZE = { note: [180, 120], card: [220, 90], image: [240, 180] } as const
const ZOOM_MIN = 0.2
const ZOOM_MAX = 3

type Item = PageRecord & { type?: string; x?: number; y?: number; w?: number; h?: number; text?: string; color?: string; image?: string; from?: string; to?: string }

const num = (v: unknown, d: number) => typeof v === 'number' && Number.isFinite(v) ? v : d
const dims = (it: Item) => {
  const [dw, dh] = SIZE[(it.type as keyof typeof SIZE) ?? 'note'] ?? SIZE.note
  return { x: num(it.x, 0), y: num(it.y, 0), w: num(it.w, dw), h: num(it.h, dh) }
}

export function BoardWidget({ page, widget: w, project, preview }: DataWidgetProps) {
  const { tr } = useTr()
  const collection = w.source?.data ?? ''
  const data = usePageData(page.id, collection, project, !!collection && !preview)
  const canEdit = data.canWrite && !preview
  const [view, setView] = useState({ x: 40, y: 40, z: 1 })
  const [selected, setSelected] = useState<string | null>(null)
  const [editing, setEditing] = useState<string | null>(null)
  const [linkFrom, setLinkFrom] = useState<string | null | 'armed'>(null)
  const [moving, setMoving] = useState<Record<string, { x: number; y: number }>>({})
  const surface = useRef<HTMLDivElement>(null)
  const drag = useRef<{ kind: 'pan' | 'move'; rid?: string; sx: number; sy: number; ox: number; oy: number; moved: boolean } | null>(null)

  const items = data.records as Item[]
  const cards = useMemo(() => items.filter(it => it.type !== 'link'), [items])
  const links = useMemo(() => items.filter(it => it.type === 'link'), [items])
  const byId = useMemo(() => Object.fromEntries(cards.map(c => [c.rid, c])), [cards])
  const place = (it: Item) => ({ ...dims(it), ...(moving[it.rid] ?? {}) })

  // Screen point -> board point.
  const toBoard = useCallback((cx: number, cy: number) => {
    const r = surface.current!.getBoundingClientRect()
    return { x: (cx - r.left - view.x) / view.z, y: (cy - r.top - view.y) / view.z }
  }, [view])

  const add = useCallback((fields: Record<string, unknown>) => {
    data.put(fields).then(rid => { if (rid) { setSelected(rid); if (fields.type !== 'image') setEditing(rid) } }).catch(err => toast.error((err as Error).message))
  }, [data])

  const center = () => {
    const r = surface.current?.getBoundingClientRect()
    return r ? toBoard(r.left + r.width / 2 - 90, r.top + r.height / 2 - 60) : { x: 0, y: 0 }
  }

  const addImage = async () => {
    const path = await window.electronAPI?.openFile([{ name: 'Images', extensions: ['png', 'jpg', 'jpeg', 'gif', 'webp'] }])
    if (!path) return
    try {
      const { image } = await flowsApi.addPageImage(page.id, collection, path, project)
      add({ type: 'image', image, ...center(), w: SIZE.image[0], h: SIZE.image[1] })
    } catch (err) { toast.error((err as Error).message) }
  }

  const remove = useCallback((rid: string) => {
    // A card takes its links with it.
    const ops = [rid, ...links.filter(l => l.from === rid || l.to === rid).map(l => l.rid)].map(r => ({ op: 'del' as const, rid: r }))
    data.write(ops).catch(err => toast.error((err as Error).message))
    setSelected(null)
  }, [data, links])

  const fit = useCallback(() => {
    const r = surface.current?.getBoundingClientRect()
    if (!r || !cards.length) { setView({ x: 40, y: 40, z: 1 }); return }
    const boxes = cards.map(dims)
    const x0 = Math.min(...boxes.map(b => b.x)), y0 = Math.min(...boxes.map(b => b.y))
    const x1 = Math.max(...boxes.map(b => b.x + b.w)), y1 = Math.max(...boxes.map(b => b.y + b.h))
    const z = Math.max(ZOOM_MIN, Math.min(1.5, Math.min((r.width - 60) / (x1 - x0 || 1), (r.height - 60) / (y1 - y0 || 1))))
    setView({ z, x: 30 - x0 * z + (r.width - 60 - (x1 - x0) * z) / 2, y: 30 - y0 * z + (r.height - 60 - (y1 - y0) * z) / 2 })
  }, [cards])
  const fitted = useRef(false)
  useEffect(() => { if (!fitted.current && data.loaded && cards.length) { fitted.current = true; fit() } }, [data.loaded, cards.length, fit])

  const onWheel = (e: WheelEvent<HTMLDivElement>) => {
    const r = surface.current!.getBoundingClientRect()
    const px = e.clientX - r.left, py = e.clientY - r.top
    setView(v => {
      const z = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, v.z * (e.deltaY < 0 ? 1.1 : 1 / 1.1)))
      return { z, x: px - (px - v.x) * (z / v.z), y: py - (py - v.y) * (z / v.z) }
    })
  }

  const onDown = (e: RPointerEvent<HTMLDivElement>, rid?: string) => {
    if (e.button !== 0 || editing) return
    e.stopPropagation()
    surface.current?.focus()
    if (rid && linkFrom) {
      if (linkFrom === 'armed') setLinkFrom(rid)
      else if (linkFrom !== rid) { add({ type: 'link', from: linkFrom, to: rid }); setLinkFrom(null) }
      return
    }
    setSelected(rid ?? null)
    const it = rid ? byId[rid] : undefined
    const start = it ? place(it) : view
    drag.current = { kind: rid ? 'move' : 'pan', rid, sx: e.clientX, sy: e.clientY, ox: start.x, oy: start.y, moved: false }
    e.currentTarget.setPointerCapture(e.pointerId)
  }
  const onMove = (e: RPointerEvent<HTMLDivElement>) => {
    const d = drag.current
    if (!d) return
    const dx = e.clientX - d.sx, dy = e.clientY - d.sy
    if (Math.abs(dx) + Math.abs(dy) > 2) d.moved = true
    if (d.kind === 'pan') setView(v => ({ ...v, x: d.ox + dx, y: d.oy + dy }))
    else if (canEdit && d.rid) setMoving(m => ({ ...m, [d.rid!]: { x: Math.round(d.ox + dx / view.z), y: Math.round(d.oy + dy / view.z) } }))
  }
  const onUp = (e: RPointerEvent<HTMLDivElement>) => {
    const d = drag.current
    drag.current = null
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId)
    if (d?.kind === 'move' && d.rid && d.moved && moving[d.rid]) {
      const to = moving[d.rid]
      data.put({ x: to.x, y: to.y }, d.rid)
        .catch(err => toast.error((err as Error).message))
        .finally(() => setMoving(m => { const n = { ...m }; delete n[d.rid!]; return n }))
    }
  }

  const onKey = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (editing || !canEdit || !selected) return
    if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); remove(selected) }
  }

  const sel = selected ? items.find(i => i.rid === selected) : undefined
  const tool = (title: string, onClick: () => void, icon: React.ReactNode, on = false) => (
    <button type="button" className="btn ghost sm" title={title} onClick={onClick}
            style={{ background: on ? 'var(--paper-2)' : undefined, padding: '2px 6px' }}>{icon}</button>
  )

  return (
    <div style={{ border: '1px solid var(--rule)', borderRadius: 8, background: 'var(--paper)', overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '6px 8px', borderBottom: '1px solid var(--rule)' }}>
        {w.label && <span style={{ fontSize: 12.5, fontWeight: 600, marginRight: 8 }}>{w.label}</span>}
        {canEdit && <>
          {tool(tr('Note', 'Note'), () => add({ type: 'note', color: 'yellow', text: '', ...center() }), <StickyNote size={13} />)}
          {tool(tr('Carte', 'Card'), () => add({ type: 'card', color: 'white', text: '', ...center() }), <Square size={13} />)}
          {window.electronAPI && tool(tr('Image (copiee dans le board)', 'Image (copied into the board)'), () => { void addImage() }, <ImagePlus size={13} />)}
          {tool(linkFrom ? tr('Clique la carte d\'arrivee', 'Click the target card') : tr('Lier deux cartes', 'Link two cards'),
                () => setLinkFrom(l => l ? null : 'armed'), <Link2 size={13} />, !!linkFrom)}
          {sel && sel.type !== 'link' && sel.type !== 'image' && Object.keys(COLORS).map(c => (
            <button type="button" key={c} title={c} onClick={() => { data.put({ color: c }, sel.rid).catch(err => toast.error((err as Error).message)) }}
                    style={{ width: 14, height: 14, borderRadius: 3, background: COLORS[c], border: sel.color === c ? '2px solid var(--ink)' : '1px solid var(--rule-2)', cursor: 'pointer', padding: 0 }} />
          ))}
          {sel && tool(tr('Supprimer (Suppr)', 'Delete (Del)'), () => remove(sel.rid), <Trash2 size={13} />)}
        </>}
        <span style={{ flex: 1 }} />
        {tool(tr('Zoom arriere', 'Zoom out'), () => setView(v => ({ ...v, z: Math.max(ZOOM_MIN, v.z / 1.2) })), <Minus size={13} />)}
        <span className="cap" style={{ minWidth: 38, textAlign: 'center' }}>{Math.round(view.z * 100)} %</span>
        {tool(tr('Zoom avant', 'Zoom in'), () => setView(v => ({ ...v, z: Math.min(ZOOM_MAX, v.z * 1.2) })), <Plus size={13} />)}
        {tool(tr('Tout voir', 'Fit'), fit, <Maximize size={13} />)}
      </div>
      <div ref={surface} tabIndex={0} onKeyDown={onKey} onWheel={onWheel}
           onPointerDown={e => onDown(e)} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp}
           onDoubleClick={e => { if (canEdit && e.target === e.currentTarget) add({ type: 'note', color: 'yellow', text: '', ...toBoard(e.clientX - 90, e.clientY - 60) }) }}
           style={{ position: 'relative', height: w.height ?? 520, overflow: 'hidden', outline: 'none', touchAction: 'none',
                    cursor: linkFrom ? 'crosshair' : drag.current?.kind === 'pan' ? 'grabbing' : 'default',
                    backgroundColor: 'var(--bg-deep)',
                    backgroundImage: 'radial-gradient(var(--rule) 1px, transparent 1px)',
                    backgroundSize: `${24 * view.z}px ${24 * view.z}px`, backgroundPosition: `${view.x}px ${view.y}px` }}>
        <div style={{ position: 'absolute', left: 0, top: 0, transformOrigin: '0 0', transform: `translate(${view.x}px, ${view.y}px) scale(${view.z})`, pointerEvents: 'none' }}>
          <svg style={{ position: 'absolute', left: 0, top: 0, overflow: 'visible', pointerEvents: 'none' }} width={1} height={1}>
            {links.map(l => {
              const a = l.from ? byId[l.from] : undefined, b = l.to ? byId[l.to] : undefined
              if (!a || !b) return null
              const pa = place(a), pb = place(b)
              const on = selected === l.rid
              return (
                <line key={l.rid} x1={pa.x + pa.w / 2} y1={pa.y + pa.h / 2} x2={pb.x + pb.w / 2} y2={pb.y + pb.h / 2}
                      stroke={on ? 'var(--accent)' : 'var(--ink-3)'} strokeWidth={on ? 3 : 1.5} style={{ pointerEvents: 'stroke', cursor: 'pointer' }}
                      onPointerDown={e => { e.stopPropagation(); setSelected(l.rid); surface.current?.focus() }} />
              )
            })}
          </svg>
          {cards.map(it => {
            const p = place(it)
            const on = selected === it.rid
            return (
              <div key={it.rid} onPointerDown={e => onDown(e as unknown as RPointerEvent<HTMLDivElement>, it.rid)}
                   onDoubleClick={e => { e.stopPropagation(); if (canEdit && it.type !== 'image') setEditing(it.rid) }}
                   title={`${it._created_by}${it._by !== it._created_by ? ` / ${it._by}` : ''}`}
                   style={{ position: 'absolute', left: p.x, top: p.y, width: p.w, minHeight: it.type === 'image' ? undefined : p.h,
                            background: it.type === 'image' ? 'transparent' : COLORS[it.color ?? (it.type === 'card' ? 'white' : 'yellow')] ?? COLORS.yellow,
                            border: on ? '2px solid var(--accent)' : linkFrom === it.rid ? '2px dashed var(--accent)' : '1px solid oklch(70% 0.02 250 / 0.5)',
                            borderRadius: it.type === 'note' ? 2 : 6, padding: it.type === 'image' ? 0 : 10, color: 'oklch(25% 0.02 250)',
                            boxShadow: '0 1px 2px oklch(0% 0 0 / 0.12)', pointerEvents: 'auto', cursor: canEdit ? 'grab' : 'default',
                            fontSize: 13, lineHeight: 1.35, whiteSpace: 'pre-wrap', wordBreak: 'break-word', userSelect: 'none' }}>
                {it.type === 'image' && it.image
                  ? <img src={flowsApi.pageImageUrl(page.id, collection, it.image, project)} alt="" draggable={false}
                         style={{ width: '100%', display: 'block', borderRadius: 6 }} />
                  : editing === it.rid
                    ? <textarea autoFocus defaultValue={it.text ?? ''} onPointerDown={e => e.stopPropagation()}
                                onBlur={e => { setEditing(null); if (e.target.value !== (it.text ?? '')) data.put({ text: e.target.value }, it.rid).catch(err => toast.error((err as Error).message)) }}
                                onKeyDown={e => { if (e.key === 'Escape') (e.target as HTMLTextAreaElement).blur() }}
                                style={{ width: '100%', minHeight: p.h - 20, border: 'none', outline: 'none', background: 'transparent', color: 'inherit', font: 'inherit', resize: 'none' }} />
                    : (it.text || <span style={{ opacity: 0.45 }}>{canEdit ? tr('Double clic pour ecrire', 'Double click to write') : ''}</span>)}
              </div>
            )
          })}
        </div>
        {data.error && <div className="cap" style={{ position: 'absolute', left: 10, bottom: 8, color: 'var(--err)' }}>{data.error}</div>}
        {data.loaded && !cards.length && !data.error && (
          <div className="cap" style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--ink-4)', pointerEvents: 'none' }}>
            {canEdit ? tr('Board vide : double clic pour poser une note', 'Empty board: double click to drop a note') : tr('Board vide', 'Empty board')}
          </div>
        )}
      </div>
    </div>
  )
}
