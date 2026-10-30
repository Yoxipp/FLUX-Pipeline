// BoardWidget.tsx — the Miro-like board (ADR 0066 n°1, v2 ADR 0071): a free surface INSIDE
// its row of the page grid. Notes, cards, shapes, free text and images, links with arrows
// and labels, pan and zoom. Every object is a record of a `kind: board` collection (flat
// fields, model.ts), written to the author's own journal: two people moving and restyling
// the same note both keep their change (per field merge, page_data.py).
// The view (pan, zoom), the selection and the undo stack are per viewer, never written.
// Only the objects in view are rendered (culling, ADR 0071 n°2); a drag writes on release.
//
// Mouse: drag the background = rectangle selection (Shift adds), middle / right button,
// Space or the hand tool = pan, wheel = zoom at the cursor, drag an object = move the
// selection, corner handles = resize (Shift or an image keeps the ratio), double click the
// background = new note, double click an object = edit its text.
// Keys: Ctrl+Z / Ctrl+Y undo / redo (own ops only), Ctrl+C / X / V / D, Ctrl+A, Suppr,
// Ctrl+G / Ctrl+Shift+G group, Ctrl+L lock, Ctrl+] / Ctrl+[ order, Ctrl+F search, Shift+1 fit.

import { memo, useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as RPointerEvent } from 'react'
import {
  Bold, BringToFront, Circle, Copy, Diamond, Group, Hand, ImagePlus, Link2, Lock, LockOpen, Magnet, Map as MapIcon, Maximize,
  Minus, MousePointer2, MoveLeft, MoveRight, Plus, Redo2, Search, SendToBack, Square, Squircle, StickyNote, Trash2, Type,
  Undo2, Ungroup, RectangleHorizontal,
} from 'lucide-react'
import { toast } from 'sonner'
import { flowsApi } from '../../api/flows'
import { usePageData } from '../../hooks/usePages'
import type { PageDataOp } from '../flow_editor/types'
import { useTr } from '../flow_editor/useTr'
import type { DataWidgetProps } from './DataWidgets'
import { BoardItem, BoardLink, type Corner, type ItemHandlers } from './board/BoardItem'
import { BoardMinimap } from './board/BoardMinimap'
import {
  CLIP_TAG, FILLS, FONT_SIZES, GRID, SIZE, STROKES, bounds, dims, fieldsOf, fontOf, intersects, inversePut, newGroupId,
  parseClip, restoreOp, type Box, type ClipData, type Item, type Shape,
} from './board/model'
import { useBoardHistory } from './board/useBoardHistory'

const ZOOM_MIN = 0.1
const ZOOM_MAX = 4
const SNAP_PX = 6        // alignment distance, in screen pixels
const CULL_PX = 300      // objects this far outside the view are still rendered

type Drag =
  | { kind: 'pan'; sx: number; sy: number; ox: number; oy: number }
  | { kind: 'marquee'; bx: number; by: number; add: string[] }
  | { kind: 'move'; sx: number; sy: number; start: Record<string, Box>; others: Box[]; moved: boolean; click: string; shift: boolean }
  | { kind: 'resize'; rid: string; corner: Corner; sx: number; sy: number; start: Box; ratio: boolean }
type Guide = { x?: number; y?: number }

const fail = (err: unknown) => toast.error((err as Error).message)
const snapTo = (v: number) => Math.round(v / GRID) * GRID

// Objects and links in view. Memoised: its props do not change while panning (the culling
// area is coarse), so a pan only moves the transform of the parent.
interface LayerProps {
  visible: Item[]; links: Item[]; byId: Map<string, Item>; boxOf: (it: Item) => Box
  selSet: Set<string>; matchSet: Set<string>; singleCard: string | null; editing: string | null
  linkFrom: string | null | 'armed'; canEdit: boolean; media: (it: Item) => string | undefined
  placeholder: string; handlers: ItemHandlers; onLinkDown: (e: RPointerEvent, rid: string) => void
}
const BoardLayer = memo(function BoardLayer(p: LayerProps) {
  return <>
    <svg style={{ position: 'absolute', left: 0, top: 0, overflow: 'visible', pointerEvents: 'none', zIndex: 0 }} width={1} height={1}>
      {p.links.map(l => {
        const a = p.byId.get(l.from!)!, b = p.byId.get(l.to!)!
        return <BoardLink key={l.rid} it={l} a={p.boxOf(a)} b={p.boxOf(b)} aShape={a.type === 'shape' ? a.shape : undefined}
                          bShape={b.type === 'shape' ? b.shape : undefined} selected={p.selSet.has(l.rid)} onDown={p.onLinkDown} />
      })}
    </svg>
    {p.visible.map(it => {
      const b = p.boxOf(it)
      return <BoardItem key={it.rid} it={it} x={b.x} y={b.y} w={b.w} h={b.h} selected={p.selSet.has(it.rid)}
                        handles={p.singleCard === it.rid} editing={p.editing === it.rid} linkSource={p.linkFrom === it.rid}
                        match={p.matchSet.has(it.rid)} canEdit={p.canEdit} mediaUrl={it.type === 'image' ? p.media(it) : undefined}
                        placeholder={p.placeholder} on={p.handlers} />
    })}
  </>
})

export function BoardWidget({ page, widget: w, project, preview }: DataWidgetProps) {
  const { tr } = useTr()
  const collection = w.source?.data ?? ''
  const data = usePageData(page.id, collection, project, !!collection)
  const canEdit = data.canWrite && !preview
  const history = useBoardHistory(data.write)
  const height = w.height ?? 520
  const [view, setView] = useState({ x: 40, y: 40, z: 1 })
  const [size, setSize] = useState({ w: 800, h: height })
  const [selection, setSelection] = useState<string[]>([])
  const [editing, setEditing] = useState<string | null>(null)
  const [linkFrom, setLinkFrom] = useState<string | null | 'armed'>(null)
  const [ghost, setGhost] = useState<Record<string, Box>>({})
  const [marquee, setMarquee] = useState<Box | null>(null)
  const [guides, setGuides] = useState<Guide[]>([])
  const [hand, setHand] = useState(false)
  const [space, setSpace] = useState(false)
  const [panning, setPanning] = useState(false)
  const [snap, setSnap] = useState(true)
  const [showMap, setShowMap] = useState(true)
  const [query, setQuery] = useState('')
  const [hit, setHit] = useState(-1)
  const surface = useRef<HTMLDivElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  const labelRef = useRef<HTMLInputElement>(null)
  const drag = useRef<Drag | null>(null)
  const clip = useRef<ClipData | null>(null)

  // -- derived ---------------------------------------------------------------
  const items = data.records as Item[]
  const byId = useMemo(() => new Map(items.map(it => [it.rid, it])), [items])
  // Back to front: z, then creation order (a stable sort keeps the journal order).
  const cards = useMemo(() => items.filter(it => it.type !== 'link').sort((a, b) => (a.z ?? 0) - (b.z ?? 0)), [items])
  const links = useMemo(() => items.filter(it => it.type === 'link'), [items])
  const selSet = useMemo(() => new Set(selection), [selection])
  const boxOf = useCallback((it: Item) => ghost[it.rid] ?? dims(it), [ghost])
  const boxes = useMemo(() => cards.map(dims), [cards])
  const viewport: Box = { x: -view.x / view.z, y: -view.y / view.z, w: size.w / view.z, h: size.h / view.z }
  // Culling area on a coarse grid (zoom rounded down by quarter octaves, half-view cells):
  // it changes only when the view leaves it, so a pan does not re-render the objects.
  const zq = 2 ** (Math.floor(Math.log2(view.z) * 4) / 4)
  const spanW = size.w / zq + CULL_PX / zq, spanH = size.h / zq + CULL_PX / zq
  const cellX = Math.floor(viewport.x / (spanW / 2)), cellY = Math.floor(viewport.y / (spanH / 2))
  const cull = useMemo<Box>(() => ({ x: (cellX - 1) * spanW / 2, y: (cellY - 1) * spanH / 2, w: spanW * 2.5, h: spanH * 2.5 }),
                            [cellX, cellY, spanW, spanH])
  const visible = useMemo(() => cards.filter(c => selSet.has(c.rid) || editing === c.rid || intersects(boxOf(c), cull)),
                          [cards, selSet, editing, boxOf, cull])
  const visibleLinks = useMemo(() => links.filter(l => {
    const a = l.from ? byId.get(l.from) : undefined, b = l.to ? byId.get(l.to) : undefined
    return a && b && a.type !== 'link' && b.type !== 'link' && intersects(bounds([boxOf(a), boxOf(b)])!, cull)
  }), [links, byId, boxOf, cull])
  const selCards = selection.map(r => byId.get(r)).filter((i): i is Item => !!i && i.type !== 'link')
  const selLinks = selection.map(r => byId.get(r)).filter((i): i is Item => !!i && i.type === 'link')
  const matches = useMemo(() => {
    const q = query.trim().toLowerCase()
    return q ? items.filter(it => (it.text ?? it.label ?? '').toLowerCase().includes(q)) : []
  }, [items, query])
  const matchSet = useMemo(() => new Set(matches.map(m => m.rid)), [matches])

  // -- view ------------------------------------------------------------------
  useEffect(() => {
    const el = surface.current
    if (!el) return
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }))
    ro.observe(el)
    // Native listener: React's wheel listener is passive, the page would scroll too.
    const wheel = (e: WheelEvent) => {
      e.preventDefault()
      const r = el.getBoundingClientRect()
      const px = e.clientX - r.left, py = e.clientY - r.top
      setView(v => {
        const z = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, v.z * Math.exp(-e.deltaY * 0.0015)))
        return { z, x: px - (px - v.x) * (z / v.z), y: py - (py - v.y) * (z / v.z) }
      })
    }
    el.addEventListener('wheel', wheel, { passive: false })
    return () => { ro.disconnect(); el.removeEventListener('wheel', wheel) }
  }, [])

  const toBoard = useCallback((cx: number, cy: number) => {
    const r = surface.current!.getBoundingClientRect()
    return { x: (cx - r.left - view.x) / view.z, y: (cy - r.top - view.y) / view.z }
  }, [view])

  const centreOn = useCallback((b: Box) => {
    setView(v => ({ ...v, x: size.w / 2 - (b.x + b.w / 2) * v.z, y: size.h / 2 - (b.y + b.h / 2) * v.z }))
  }, [size])

  const fit = useCallback(() => {
    const all = bounds(cards.map(dims))
    if (!all) { setView({ x: 40, y: 40, z: 1 }); return }
    const z = Math.max(ZOOM_MIN, Math.min(1.5, Math.min((size.w - 60) / (all.w || 1), (size.h - 60) / (all.h || 1))))
    setView({ z, x: size.w / 2 - (all.x + all.w / 2) * z, y: size.h / 2 - (all.y + all.h / 2) * z })
  }, [cards, size])
  const fitted = useRef(false)
  useEffect(() => { if (!fitted.current && data.loaded && cards.length && size.w > 0) { fitted.current = true; fit() } }, [data.loaded, cards.length, fit, size.w])

  // Top left corner that puts a w x h object in the middle of the view.
  const middle = (ow: number, oh: number) => ({ x: Math.round(viewport.x + viewport.w / 2 - ow / 2), y: Math.round(viewport.y + viewport.h / 2 - oh / 2) })

  // -- writes (each one goes on the undo stack) -----------------------------
  const withGroups = useCallback((rids: string[]) => {
    const groups = new Set(rids.map(r => byId.get(r)?.group).filter(Boolean))
    if (!groups.size) return rids
    return [...new Set([...rids, ...cards.filter(c => c.group && groups.has(c.group)).map(c => c.rid)])]
  }, [byId, cards])

  const update = useCallback((changes: { rid: string; fields: Record<string, unknown> }[], evenLocked = false) => {
    const ok = changes.filter(c => byId.has(c.rid) && (evenLocked || !byId.get(c.rid)!.locked))
    if (!ok.length) return
    const redo: PageDataOp[] = ok.map(c => ({ op: 'put', rid: c.rid, fields: c.fields }))
    const undo = ok.map(c => inversePut(byId.get(c.rid)!, c.fields))
    data.write(redo).then(() => history.push({ redo, undo })).catch(fail)
  }, [byId, data, history])

  const createRaw = useCallback(async (list: Record<string, unknown>[]) => {
    const rids = await data.write(list.map(fields => ({ op: 'put' as const, fields })))
    return rids
  }, [data])
  const pushCreated = useCallback((rids: string[], list: Record<string, unknown>[]) => {
    history.push({ redo: rids.map((rid, i) => ({ op: 'put', rid, fields: list[i], restore: true })),
                   undo: rids.map(rid => ({ op: 'del', rid })) })
  }, [history])

  const add = useCallback((fields: Record<string, unknown>) => {
    createRaw([fields]).then(rids => {
      pushCreated(rids, [fields])
      if (!rids[0]) return
      setSelection([rids[0]])
      if (fields.type !== 'image' && fields.type !== 'link') setEditing(rids[0])
    }).catch(fail)
  }, [createRaw, pushCreated])

  const topZ = () => cards.reduce((m, c) => Math.max(m, c.z ?? 0), 0) + 1
  const addAtMiddle = (type: Item['type'], extra: Record<string, unknown> = {}) => {
    const [ow, oh] = SIZE[type ?? 'note']
    add({ type, ...middle(ow, oh), w: ow, h: oh, z: topZ(), text: '', ...extra })
  }

  const addImage = async () => {
    const path = await window.electronAPI?.openFile([{ name: 'Images', extensions: ['png', 'jpg', 'jpeg', 'gif', 'webp'] }])
    if (!path) return
    try {
      const { image } = await flowsApi.addPageImage(page.id, collection, path, project)
      // Box from the real ratio, longest side 320.
      const [nw, nh] = await new Promise<[number, number]>(ok => {
        const img = new Image()
        img.onload = () => ok([img.naturalWidth || SIZE.image[0], img.naturalHeight || SIZE.image[1]])
        img.onerror = () => ok(SIZE.image)
        img.src = flowsApi.pageImageUrl(page.id, collection, image, project)
      })
      const k = 320 / Math.max(nw, nh)
      const ow = Math.round(nw * k), oh = Math.round(nh * k)
      add({ type: 'image', image, ...middle(ow, oh), w: ow, h: oh, z: topZ() })
    } catch (err) { fail(err) }
  }

  const remove = useCallback((rids: string[]) => {
    const gone = new Set(rids.filter(r => byId.has(r) && !byId.get(r)!.locked))
    // An object takes its links with it.
    for (const l of links) if ((l.from && gone.has(l.from)) || (l.to && gone.has(l.to))) gone.add(l.rid)
    if (!gone.size) return
    const recs = [...gone].map(r => byId.get(r)!)
    const redo: PageDataOp[] = recs.map(r => ({ op: 'del', rid: r.rid }))
    data.write(redo).then(() => history.push({ redo, undo: recs.map(restoreOp) })).catch(fail)
    setSelection([])
  }, [byId, links, data, history])

  // -- clipboard -------------------------------------------------------------
  const clipOf = (rids: string[]): ClipData => {
    const set = new Set(rids)
    const list = rids.map(r => byId.get(r)).filter((i): i is Item => !!i && i.type !== 'link')
    const inner = links.filter(l => l.from && l.to && set.has(l.from) && set.has(l.to))
    return { [CLIP_TAG]: 2, page: page.id, collection, items: [...list, ...inner] }
  }

  const copy = () => {
    if (!selCards.length) return
    clip.current = clipOf(selCards.map(c => c.rid))
    navigator.clipboard?.writeText(JSON.stringify(clip.current)).catch(() => undefined)
  }

  // New rids, new groups, links re-pointed, on top of everything; *at* = where the block goes.
  const pasteItems = async (c: ClipData, at: 'middle' | { dx: number; dy: number }) => {
    const same = c.page === page.id && c.collection === collection
    const objs = c.items.filter(i => i.type !== 'link' && (same || i.type !== 'image'))
    if (objs.length < c.items.filter(i => i.type !== 'link').length)
      toast.info(tr('Images d\'un autre board ignorees (a ajouter par le bouton Image).', 'Images from another board skipped (add them with the Image button).'))
    if (!objs.length) return
    const box = bounds(objs.map(dims))!
    const shift = at === 'middle' ? { dx: viewport.x + viewport.w / 2 - (box.x + box.w / 2), dy: viewport.y + viewport.h / 2 - (box.y + box.h / 2) } : at
    const groups = new Map<string, string>()
    const z0 = Math.min(...objs.map(o => o.z ?? 0)), top = topZ()
    const list = objs.map(o => {
      const f = fieldsOf(o)
      const g = o.group ? (groups.get(o.group) ?? groups.set(o.group, newGroupId()).get(o.group)) : undefined
      return { ...f, x: Math.round(dims(o).x + shift.dx), y: Math.round(dims(o).y + shift.dy), z: top + (o.z ?? 0) - z0,
               group: g ?? null, locked: null }
    })
    try {
      const rids = await createRaw(list)
      const map = new Map(objs.map((o, i) => [o.rid, rids[i]]))
      const linkList = c.items.filter(l => l.type === 'link' && l.from && l.to && map.has(l.from) && map.has(l.to))
        .map(l => ({ ...fieldsOf(l), from: map.get(l.from!), to: map.get(l.to!) }))
      const lrids = linkList.length ? await createRaw(linkList) : []
      pushCreated([...rids, ...lrids], [...list, ...linkList])
      setSelection(rids)
    } catch (err) { fail(err) }
  }

  const paste = async () => {
    let text = ''
    try { text = await navigator.clipboard.readText() } catch { /* no clipboard access: internal copy */ }
    const c = (text && parseClip(text)) || (!text ? clip.current : null)
    if (c) { await pasteItems(c, 'middle'); return }
    // Plain text: a note with it.
    if (text.trim() && canEdit) addAtMiddle('note', { color: 'yellow', text: text.slice(0, 10_000) })
  }

  const duplicate = () => { if (selCards.length) void pasteItems(clipOf(selCards.map(c => c.rid)), { dx: 24, dy: 24 }) }

  // -- arrange ---------------------------------------------------------------
  const order = (front: boolean) => {
    const sel = [...selCards].sort((a, b) => (a.z ?? 0) - (b.z ?? 0))
    if (!sel.length) return
    const base = front ? topZ() : cards.reduce((m, c) => Math.min(m, c.z ?? 0), 0) - sel.length
    update(sel.map((c, i) => ({ rid: c.rid, fields: { z: base + i } })))
  }
  const group = (on: boolean) => {
    if (on && selCards.length < 2) return
    const g = on ? newGroupId() : null
    update(selCards.map(c => ({ rid: c.rid, fields: { group: g } })))
  }
  const lock = () => {
    const all = selCards.every(c => c.locked)
    update(selCards.map(c => ({ rid: c.rid, fields: { locked: all ? null : true } })), true)
  }
  const style = (fields: Record<string, unknown>, which: 'cards' | 'links' = 'cards') =>
    update((which === 'cards' ? selCards : selLinks).map(c => ({ rid: c.rid, fields })))
  const fontStep = (dir: 1 | -1) => update(selCards.map(c => {
    const cur = fontOf(c)
    const next = dir > 0 ? FONT_SIZES.find(s => s > cur) ?? cur : [...FONT_SIZES].reverse().find(s => s < cur) ?? cur
    return { rid: c.rid, fields: { font_size: next } }
  }))

  const nextMatch = () => {
    if (!matches.length) return
    const i = (hit + 1) % matches.length
    setHit(i)
    const m = matches[i]
    setSelection([m.rid])
    if (m.type === 'link') {
      const a = m.from ? byId.get(m.from) : undefined, b = m.to ? byId.get(m.to) : undefined
      if (a && b) centreOn(bounds([dims(a), dims(b)])!)
    } else centreOn(dims(m))
  }

  // -- pointer ---------------------------------------------------------------
  const capture = (e: RPointerEvent) => { surface.current?.focus(); surface.current?.setPointerCapture(e.pointerId) }
  const panStart = (e: RPointerEvent) => {
    drag.current = { kind: 'pan', sx: e.clientX, sy: e.clientY, ox: view.x, oy: view.y }
    setPanning(true)
    capture(e)
  }

  const onSurfaceDown = (e: RPointerEvent<HTMLDivElement>) => {
    if (editing) return
    if (e.button === 1 || e.button === 2 || hand || space) { e.preventDefault(); panStart(e); return }
    if (e.button !== 0) return
    if (linkFrom) { setLinkFrom(null); return }
    const p = toBoard(e.clientX, e.clientY)
    const add = e.shiftKey ? selection : []
    if (!e.shiftKey) setSelection([])
    drag.current = { kind: 'marquee', bx: p.x, by: p.y, add }
    capture(e)
  }

  const onItemDown = (e: RPointerEvent, rid: string) => {
    if (e.button !== 0 || hand || space || editing === rid) return   // the surface pans
    e.stopPropagation()
    const it = byId.get(rid)
    if (!it) return
    if (linkFrom) {
      if (it.type === 'link') return
      if (linkFrom === 'armed') setLinkFrom(rid)
      else if (linkFrom !== rid) { add({ type: 'link', from: linkFrom, to: rid, arrow_end: true }); setLinkFrom(null) }
      return
    }
    const mine = withGroups([rid])
    let sel = selection
    if (e.shiftKey) {
      sel = selSet.has(rid) ? selection.filter(r => !mine.includes(r)) : [...new Set([...selection, ...mine])]
      setSelection(sel)
      surface.current?.focus()
      return
    }
    if (!selSet.has(rid)) { sel = mine; setSelection(sel) }
    if (it.type === 'link' || !canEdit) { surface.current?.focus(); return }
    const start: Record<string, Box> = {}
    for (const r of sel) { const c = byId.get(r); if (c && c.type !== 'link' && !c.locked) start[r] = dims(c) }
    const others = visible.filter(c => !start[c.rid]).map(dims)
    drag.current = { kind: 'move', sx: e.clientX, sy: e.clientY, start, others, moved: false, click: rid, shift: false }
    capture(e)
  }

  const onResizeDown = (e: RPointerEvent, rid: string, corner: Corner) => {
    e.stopPropagation()
    const it = byId.get(rid)
    if (!it || it.locked || !canEdit) return
    drag.current = { kind: 'resize', rid, corner, sx: e.clientX, sy: e.clientY, start: dims(it), ratio: it.type === 'image' }
    capture(e)
  }

  // Shift the moving block so one of its edges / centres meets a neighbour's; grid otherwise.
  const align = (block: Box, others: Box[]) => {
    const tol = SNAP_PX / view.z
    let bx: { d: number; at: number } | null = null, by: { d: number; at: number } | null = null
    const xs = [block.x, block.x + block.w / 2, block.x + block.w], ys = [block.y, block.y + block.h / 2, block.y + block.h]
    for (const o of others) {
      for (const t of [o.x, o.x + o.w / 2, o.x + o.w]) for (const s of xs) {
        const d = t - s
        if (Math.abs(d) <= tol && (!bx || Math.abs(d) < Math.abs(bx.d))) bx = { d, at: t }
      }
      for (const t of [o.y, o.y + o.h / 2, o.y + o.h]) for (const s of ys) {
        const d = t - s
        if (Math.abs(d) <= tol && (!by || Math.abs(d) < Math.abs(by.d))) by = { d, at: t }
      }
    }
    const g: Guide[] = []
    if (bx) g.push({ x: bx.at })
    if (by) g.push({ y: by.at })
    return { dx: bx ? bx.d : snapTo(block.x) - block.x, dy: by ? by.d : snapTo(block.y) - block.y, guides: g }
  }

  const onMove = (e: RPointerEvent<HTMLDivElement>) => {
    const d = drag.current
    if (!d) return
    if (d.kind === 'pan') { setView(v => ({ ...v, x: d.ox + e.clientX - d.sx, y: d.oy + e.clientY - d.sy })); return }
    if (d.kind === 'marquee') {
      const p = toBoard(e.clientX, e.clientY)
      setMarquee({ x: Math.min(p.x, d.bx), y: Math.min(p.y, d.by), w: Math.abs(p.x - d.bx), h: Math.abs(p.y - d.by) })
      return
    }
    const dx = (e.clientX - d.sx) / view.z, dy = (e.clientY - d.sy) / view.z
    if (d.kind === 'move') {
      if (!d.moved && Math.abs(dx) + Math.abs(dy) < 3 / view.z) return
      d.moved = true
      const rids = Object.keys(d.start)
      if (!rids.length) return
      let ox = dx, oy = dy, g: Guide[] = []
      if (snap && !e.altKey) {
        const block = bounds(rids.map(r => d.start[r]))!
        const a = align({ ...block, x: block.x + dx, y: block.y + dy }, d.others)
        ox += a.dx; oy += a.dy; g = a.guides
      }
      const next: Record<string, Box> = {}
      for (const r of rids) next[r] = { ...d.start[r], x: Math.round(d.start[r].x + ox), y: Math.round(d.start[r].y + oy) }
      setGhost(next)
      setGuides(g)
      return
    }
    // resize
    const s = d.start
    let x0 = s.x, y0 = s.y, x1 = s.x + s.w, y1 = s.y + s.h
    if (d.corner.includes('w')) x0 += dx; else x1 += dx
    if (d.corner.includes('n')) y0 += dy; else y1 += dy
    if (snap && !e.altKey) { x0 = d.corner.includes('w') ? snapTo(x0) : x0; x1 = d.corner.includes('e') ? snapTo(x1) : x1
                             y0 = d.corner.includes('n') ? snapTo(y0) : y0; y1 = d.corner.includes('s') ? snapTo(y1) : y1 }
    let nw = Math.max(24, x1 - x0), nh = Math.max(16, y1 - y0)
    if (d.ratio || e.shiftKey) { const k = Math.max(nw / s.w, nh / s.h); nw = Math.round(s.w * k); nh = Math.round(s.h * k) }
    const nx = d.corner.includes('w') ? s.x + s.w - nw : s.x, ny = d.corner.includes('n') ? s.y + s.h - nh : s.y
    setGhost({ [d.rid]: { x: Math.round(nx), y: Math.round(ny), w: Math.round(nw), h: Math.round(nh) } })
  }

  const onUp = (e: RPointerEvent<HTMLDivElement>) => {
    const d = drag.current
    drag.current = null
    if (surface.current?.hasPointerCapture(e.pointerId)) surface.current.releasePointerCapture(e.pointerId)
    setPanning(false)
    setGuides([])
    if (!d) return
    if (d.kind === 'marquee') {
      const m = marquee
      setMarquee(null)
      if (m && m.w + m.h > 2) {
        const hits = cards.filter(c => intersects(dims(c), m)).map(c => c.rid)
        setSelection([...new Set([...d.add, ...withGroups(hits)])])
      }
      return
    }
    if (d.kind === 'move') {
      if (!d.moved) { if (selection.length > 1 && !e.shiftKey) setSelection(withGroups([d.click])); return }
      update(Object.keys(ghost).map(r => ({ rid: r, fields: { x: ghost[r].x, y: ghost[r].y } })))
    } else if (d.kind === 'resize' && ghost[d.rid]) {
      update([{ rid: d.rid, fields: { ...ghost[d.rid] } }])
    }
    setGhost({})   // the optimistic write already moved the records
  }

  // -- keys ------------------------------------------------------------------
  const onKey = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (editing || (e.target as HTMLElement) !== surface.current) return
    const ctrl = e.ctrlKey || e.metaKey, k = e.key.toLowerCase()
    if (e.key === ' ') { e.preventDefault(); setSpace(true); return }
    if (e.key === 'Escape') { setSelection([]); setLinkFrom(null); return }
    if (e.shiftKey && e.code === 'Digit1') { e.preventDefault(); fit(); return }
    if (ctrl && k === 'f') { e.preventDefault(); searchRef.current?.focus(); return }
    if (ctrl && k === 'a') { e.preventDefault(); setSelection(cards.map(c => c.rid)); return }
    if (ctrl && k === 'c') { e.preventDefault(); copy(); return }
    if (!canEdit) return
    if (ctrl && (k === 'y' || (k === 'z' && e.shiftKey))) { e.preventDefault(); history.redo().catch(fail); return }
    if (ctrl && k === 'z') { e.preventDefault(); history.undo().catch(fail); return }
    if (ctrl && k === 'v') { e.preventDefault(); void paste(); return }
    if (ctrl && k === 'x') { e.preventDefault(); copy(); remove(selection); return }
    if (ctrl && k === 'd') { e.preventDefault(); duplicate(); return }
    if (ctrl && k === 'g') { e.preventDefault(); group(!e.shiftKey); return }
    if (ctrl && k === 'l') { e.preventDefault(); lock(); return }
    if (ctrl && (e.key === ']' || e.key === '[')) { e.preventDefault(); order(e.key === ']'); return }
    if ((e.key === 'Delete' || e.key === 'Backspace') && selection.length) { e.preventDefault(); remove(selection); return }
    if (e.key === 'Enter' && selCards.length === 1 && selCards[0].type !== 'image') { e.preventDefault(); setEditing(selCards[0].rid) }
  }

  // Stable handlers for the memoised items: they call the latest closures.
  const latest = useRef({ onItemDown, onResizeDown, update, canEdit, byId })
  latest.current = { onItemDown, onResizeDown, update, canEdit, byId }
  const handlers = useMemo<ItemHandlers>(() => ({
    down: (e, rid) => latest.current.onItemDown(e, rid),
    double: rid => {
      const it = latest.current.byId.get(rid)
      if (latest.current.canEdit && it && !it.locked && it.type !== 'image') setEditing(rid)
    },
    commitText: (rid, text) => latest.current.update([{ rid, fields: { text } }]),
    stopEdit: () => setEditing(null),
    resize: (e, rid, corner) => latest.current.onResizeDown(e, rid, corner),
  }), [])
  const onLinkDown = useCallback((e: RPointerEvent, rid: string) => latest.current.onItemDown(e, rid), [])

  // -- render ----------------------------------------------------------------
  const tool = (title: string, onClick: () => void, icon: React.ReactNode, on = false, disabled = false) => (
    <button type="button" className="btn ghost sm" title={title} onClick={onClick} disabled={disabled}
            style={{ background: on ? 'var(--paper-2)' : undefined, padding: '2px 6px', opacity: disabled ? 0.4 : undefined }}>{icon}</button>
  )
  const swatch = (key: string, css: string, active: boolean, onClick: () => void, ring = false) => (
    <button type="button" key={key} title={key} onClick={onClick}
            style={{ width: 14, height: 14, borderRadius: ring ? 7 : 3, padding: 0, cursor: 'pointer',
                     background: key === 'none' ? 'linear-gradient(135deg, transparent 45%, var(--err) 45%, var(--err) 55%, transparent 55%)' : ring ? 'transparent' : css,
                     border: ring && key !== 'none' ? `3px solid ${css}` : active ? '2px solid var(--ink)' : '1px solid var(--rule-2)',
                     outline: ring && active ? '1px solid var(--ink)' : undefined, outlineOffset: 1 }} />
  )
  const sep = <span style={{ width: 1, height: 16, background: 'var(--rule)', margin: '0 4px' }} />
  const one = <T,>(list: Item[], pick: (i: Item) => T) => list.length && list.every(i => pick(i) === pick(list[0])) ? pick(list[0]) : undefined
  const singleLink = selLinks.length === 1 ? selLinks[0] : undefined
  const singleCard = selCards.length === 1 && selection.length === 1 && !selCards[0].locked && canEdit ? selCards[0].rid : null
  const placeholder = tr('Double clic pour ecrire', 'Double click to write')
  const media = useCallback((it: Item) => it.image ? flowsApi.pageImageUrl(page.id, collection, it.image, project) : undefined,
                            [page.id, collection, project])

  return (
    <div style={{ border: '1px solid var(--rule)', borderRadius: 8, background: 'var(--paper)', overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 2, padding: '6px 8px', borderBottom: '1px solid var(--rule)', flexWrap: 'wrap' }}>
        {w.label && <span style={{ fontSize: 12.5, fontWeight: 600, marginRight: 8 }}>{w.label}</span>}
        {tool(tr('Selection', 'Select'), () => setHand(false), <MousePointer2 size={13} />, !hand)}
        {tool(tr('Main (deplacer la vue, ou Espace)', 'Hand (pan, or Space)'), () => setHand(true), <Hand size={13} />, hand)}
        {canEdit && <>
          {sep}
          {tool(tr('Note', 'Note'), () => addAtMiddle('note', { color: 'yellow' }), <StickyNote size={13} />)}
          {tool(tr('Carte', 'Card'), () => addAtMiddle('card', { color: 'white' }), <Square size={13} />)}
          {tool(tr('Texte', 'Text'), () => addAtMiddle('text'), <Type size={13} />)}
          {tool(tr('Forme', 'Shape'), () => addAtMiddle('shape', { shape: 'rect', color: 'white', stroke: 'ink' }), <RectangleHorizontal size={13} />)}
          {window.electronAPI && tool(tr('Image (copiee dans le board)', 'Image (copied into the board)'), () => { void addImage() }, <ImagePlus size={13} />)}
          {tool(linkFrom ? tr('Clique l\'objet d\'arrivee', 'Click the target object') : tr('Lier deux objets', 'Link two objects'),
                () => setLinkFrom(l => l ? null : 'armed'), <Link2 size={13} />, !!linkFrom)}
          {sep}
          {tool(tr('Annuler (Ctrl+Z, tes actions seulement)', 'Undo (Ctrl+Z, your own actions only)'), () => { history.undo().catch(fail) }, <Undo2 size={13} />, false, !history.canUndo)}
          {tool(tr('Retablir (Ctrl+Y)', 'Redo (Ctrl+Y)'), () => { history.redo().catch(fail) }, <Redo2 size={13} />, false, !history.canRedo)}
        </>}
        <span style={{ flex: 1 }} />
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, border: '1px solid var(--rule-2)', borderRadius: 5, padding: '0 6px', height: 24, background: 'var(--bg-deep)' }}>
          <Search size={12} style={{ color: 'var(--ink-4)' }} />
          <input ref={searchRef} value={query} placeholder={tr('Chercher', 'Search')}
                 onChange={e => { setQuery(e.target.value); setHit(-1) }}
                 onKeyDown={e => { if (e.key === 'Enter') nextMatch(); if (e.key === 'Escape') { setQuery(''); surface.current?.focus() } }}
                 style={{ width: 110, border: 'none', outline: 'none', background: 'transparent', color: 'var(--ink)', fontSize: 12 }} />
          {query && <span className="cap" style={{ color: 'var(--ink-4)' }}>{matches.length ? `${Math.max(hit, 0) + 1}/${matches.length}` : '0'}</span>}
        </span>
        {tool(tr('Magnetisme (grille et alignement ; Alt pour l\'ignorer)', 'Snapping (grid and alignment; Alt to skip)'), () => setSnap(s => !s), <Magnet size={13} />, snap)}
        {tool(tr('Mini-carte', 'Minimap'), () => setShowMap(s => !s), <MapIcon size={13} />, showMap)}
        {tool(tr('Zoom arriere', 'Zoom out'), () => setView(v => ({ ...v, z: Math.max(ZOOM_MIN, v.z / 1.2) })), <Minus size={13} />)}
        <span className="cap" style={{ minWidth: 38, textAlign: 'center' }}>{Math.round(view.z * 100)} %</span>
        {tool(tr('Zoom avant', 'Zoom in'), () => setView(v => ({ ...v, z: Math.min(ZOOM_MAX, v.z * 1.2) })), <Plus size={13} />)}
        {tool(tr('Tout voir (Maj+1)', 'Fit (Shift+1)'), fit, <Maximize size={13} />)}
      </div>

      {canEdit && selection.length > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 3, padding: '4px 8px', borderBottom: '1px solid var(--rule)', flexWrap: 'wrap', background: 'var(--paper-2)' }}>
          <span className="cap" style={{ marginRight: 6 }}>{selection.length} {tr('selectionne(s)', 'selected')}</span>
          {selCards.length > 0 && <>
            {Object.entries(FILLS).map(([k, css]) => swatch(k, css, one(selCards, i => i.color) === k, () => style({ color: k })))}
            {sep}
            {Object.entries(STROKES).map(([k, css]) => swatch(k, css, one(selCards, i => i.stroke) === k, () => style({ stroke: k }), true))}
            {sep}
            {tool(tr('Texte plus petit', 'Smaller text'), () => fontStep(-1), <span style={{ fontSize: 10 }}>A-</span>)}
            <span className="cap" style={{ minWidth: 20, textAlign: 'center' }}>{one(selCards, fontOf) ?? '-'}</span>
            {tool(tr('Texte plus grand', 'Bigger text'), () => fontStep(1), <span style={{ fontSize: 13 }}>A+</span>)}
            {tool(tr('Gras', 'Bold'), () => style({ bold: one(selCards, i => !!i.bold) ? null : true }), <Bold size={13} />, !!one(selCards, i => !!i.bold))}
            {selCards.some(c => c.type === 'shape') && <>
              {sep}
              {([['rect', <Square size={13} key="r" />], ['round', <Squircle size={13} key="o" />], ['ellipse', <Circle size={13} key="e" />],
                 ['diamond', <Diamond size={13} key="d" />]] as [Shape, React.ReactNode][]).map(([s, icon]) =>
                <span key={s}>{tool(s, () => update(selCards.filter(c => c.type === 'shape').map(c => ({ rid: c.rid, fields: { shape: s } }))), icon,
                                    one(selCards.filter(c => c.type === 'shape'), i => i.shape ?? 'rect') === s)}</span>)}
            </>}
            {sep}
          </>}
          {selLinks.length > 0 && <>
            {Object.entries(STROKES).filter(([k]) => k !== 'none').map(([k, css]) => swatch(k, css, one(selLinks, i => i.stroke) === k, () => style({ stroke: k }, 'links'), true))}
            {sep}
            {(['solid', 'dashed', 'dotted'] as const).map(d => (
              <span key={d}>{tool(d, () => style({ dash: d }, 'links'),
                <svg width={18} height={8}><line x1={1} y1={4} x2={17} y2={4} stroke="currentColor" strokeWidth={1.5}
                                                 strokeDasharray={d === 'dashed' ? '5 3' : d === 'dotted' ? '1.5 2.5' : undefined} /></svg>,
                (one(selLinks, i => i.dash ?? 'solid')) === d)}</span>
            ))}
            {tool(tr('Fleche au debut', 'Arrow at start'), () => style({ arrow_start: one(selLinks, i => !!i.arrow_start) ? null : true }, 'links'), <MoveLeft size={13} />, !!one(selLinks, i => !!i.arrow_start))}
            {tool(tr('Fleche a la fin', 'Arrow at end'), () => style({ arrow_end: one(selLinks, i => !!i.arrow_end) ? null : true }, 'links'), <MoveRight size={13} />, !!one(selLinks, i => !!i.arrow_end))}
            {singleLink && <input key={singleLink.rid} ref={labelRef} defaultValue={singleLink.label ?? ''} placeholder={tr('Libelle', 'Label')}
                                  onBlur={e => { if (e.target.value !== (singleLink.label ?? '')) update([{ rid: singleLink.rid, fields: { label: e.target.value || null } }]) }}
                                  onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
                                  style={{ width: 120, height: 22, padding: '0 6px', border: '1px solid var(--rule-2)', borderRadius: 4, background: 'var(--bg-deep)', color: 'var(--ink)', fontSize: 12 }} />}
            {sep}
          </>}
          {selCards.length > 0 && <>
            {tool(tr('Devant (Ctrl+])', 'Bring to front (Ctrl+])'), () => order(true), <BringToFront size={13} />)}
            {tool(tr('Derriere (Ctrl+[)', 'Send to back (Ctrl+[)'), () => order(false), <SendToBack size={13} />)}
            {selCards.some(c => c.group)
              ? tool(tr('Degrouper (Ctrl+Maj+G)', 'Ungroup (Ctrl+Shift+G)'), () => group(false), <Ungroup size={13} />)
              : tool(tr('Grouper (Ctrl+G)', 'Group (Ctrl+G)'), () => group(true), <Group size={13} />, false, selCards.length < 2)}
            {tool(selCards.every(c => c.locked) ? tr('Deverrouiller (Ctrl+L)', 'Unlock (Ctrl+L)') : tr('Verrouiller (Ctrl+L)', 'Lock (Ctrl+L)'), lock,
                  selCards.every(c => c.locked) ? <LockOpen size={13} /> : <Lock size={13} />, selCards.every(c => c.locked))}
            {tool(tr('Dupliquer (Ctrl+D)', 'Duplicate (Ctrl+D)'), duplicate, <Copy size={13} />)}
          </>}
          {tool(tr('Supprimer (Suppr)', 'Delete (Del)'), () => remove(selection), <Trash2 size={13} />)}
        </div>
      )}

      <div ref={surface} tabIndex={0} onKeyDown={onKey} onKeyUp={e => { if (e.key === ' ') setSpace(false) }}
           onBlur={() => setSpace(false)} onContextMenu={e => e.preventDefault()}
           onPointerDown={onSurfaceDown} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp}
           onDoubleClick={e => { if (canEdit && e.target === e.currentTarget) { const p = toBoard(e.clientX, e.clientY); add({ type: 'note', color: 'yellow', text: '', x: Math.round(p.x - 90), y: Math.round(p.y - 60), z: topZ() }) } }}
           style={{ position: 'relative', height, overflow: 'hidden', outline: 'none', touchAction: 'none',
                    cursor: linkFrom ? 'crosshair' : panning ? 'grabbing' : hand || space ? 'grab' : 'default',
                    backgroundColor: 'var(--bg-deep)',
                    backgroundImage: 'radial-gradient(var(--rule) 1px, transparent 1px)',
                    backgroundSize: `${24 * view.z}px ${24 * view.z}px`, backgroundPosition: `${view.x}px ${view.y}px` }}>
        <div style={{ position: 'absolute', left: 0, top: 0, transformOrigin: '0 0', transform: `translate(${view.x}px, ${view.y}px) scale(${view.z})`, pointerEvents: 'none' }}>
          <BoardLayer visible={visible} links={visibleLinks} byId={byId} boxOf={boxOf} selSet={selSet} matchSet={matchSet}
                      singleCard={singleCard} editing={editing} linkFrom={linkFrom} canEdit={canEdit} media={media}
                      placeholder={placeholder} handlers={handlers} onLinkDown={onLinkDown} />
          {guides.length > 0 && <svg style={{ position: 'absolute', left: 0, top: 0, overflow: 'visible', zIndex: 3 }} width={1} height={1}>
            {guides.map((g, i) => g.x !== undefined
              ? <line key={i} x1={g.x} x2={g.x} y1={viewport.y} y2={viewport.y + viewport.h} stroke="var(--accent)" strokeWidth={1 / view.z} strokeDasharray={`${4 / view.z} ${3 / view.z}`} />
              : <line key={i} y1={g.y} y2={g.y} x1={viewport.x} x2={viewport.x + viewport.w} stroke="var(--accent)" strokeWidth={1 / view.z} strokeDasharray={`${4 / view.z} ${3 / view.z}`} />)}
          </svg>}
          {marquee && <div style={{ position: 'absolute', left: marquee.x, top: marquee.y, width: marquee.w, height: marquee.h, zIndex: 4,
                                    border: `${1 / view.z}px solid var(--accent)`, background: 'oklch(60% 0.12 245 / 0.08)' }} />}
        </div>
        {showMap && cards.length > 0 && <BoardMinimap boxes={boxes} viewport={viewport} onCenter={(x, y) => centreOn({ x, y, w: 0, h: 0 })} />}
        {data.error && <div className="tp-note" style={{ position: 'absolute', left: 10, bottom: 8, color: preview ? undefined : 'var(--err)' }}>
          {preview ? tr('Apercu : enregistre la page pour lire ses donnees.', 'Preview: save the page to read its data.') : data.error}</div>}
        {data.loaded && !cards.length && !data.error && (
          <div className="tp-note" style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--ink-4)', pointerEvents: 'none' }}>
            {canEdit ? tr('Board vide : double clic pour poser une note', 'Empty board: double click to drop a note') : tr('Board vide', 'Empty board')}
          </div>
        )}
      </div>
    </div>
  )
}
