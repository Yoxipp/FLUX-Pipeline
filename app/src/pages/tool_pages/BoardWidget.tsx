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
// v3 (ADR 0074): pen / highlighter / eraser tools (a stroke is written on release, the eraser
// removes whole strokes), frames (moving one moves what is inside, presentation in reading
// order), images pasted (Ctrl+V of a screenshot) or dropped from the explorer (copied by the
// backend from a file path), FLUX cards (FluxCard.tsx) and shipped board templates.
// v4 (ADR 0075): comments and reactions on an object (one record per author, badges under
// the object, panel with who / when), a shared timer, PNG / PDF export (exportBoard.ts).

import { memo, useCallback, useEffect, useMemo, useRef, useState, type DragEvent, type PointerEvent as RPointerEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Bold, ChevronLeft, Download, Grid3x3, MessageSquare, Timer, ChevronRight, Circle, Clapperboard, Copy, Diamond, Eraser, Frame, Group, Hand, Highlighter, ImagePlus,
  LayoutTemplate, Link2, Lock, LockOpen, Magnet, Map as MapIcon, Maximize, Minus, MousePointer2, MoveLeft, MoveRight, PenLine, Play, Plus,
  Redo2, Search, Square, Squircle, StickyNote, Trash2, Type, Undo2, Ungroup, RectangleHorizontal, X,
} from 'lucide-react'
import { toast } from 'sonner'
import { flowsApi } from '../../api/flows'
import { usePageData } from '../../hooks/usePages'
import { useSettings } from '../../hooks/useSettings'
import type { BoardTemplate, PageDataOp } from '../flow_editor/types'
import { expandFluxPath } from '../Production/util'
import { useTr } from '../flow_editor/useTr'
import type { DataWidgetProps } from './DataWidgets'
import { BoardItem, BoardLink, type Corner, type ItemHandlers } from './board/BoardItem'
import { BoardMinimap } from './board/BoardMinimap'
import { FluxBoardContext, FluxPicker, resolveRef, useBoardProduction, type FluxBoardData } from './board/FluxCard'
import {
  CLIP_TAG, EMOJI, FILLS, FONT_SIZES, GRID, META_TYPES, SIZE, STROKES, bounds, dims, fieldsOf, fontOf, inkFields, inkHit, inside,
  intersects, inversePut, newGroupId, parseClip, readingOrder, restoreOp, type Box, type ClipData, type Emoji, type Item, type Pt, type Shape,
} from './board/model'
import { pdfBytes, pngBytes, regionOf, renderBoard, saveFile } from './board/exportBoard'
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
  | { kind: 'draw'; pts: Pt[] }
  | { kind: 'erase' }
type Tool = 'select' | 'hand' | 'pen' | 'highlighter' | 'eraser'
const IMAGE_EXT = /\.(png|jpe?g|gif|webp)$/i
type Guide = { x?: number; y?: number }

const fail = (err: unknown) => toast.error((err as Error).message)

// Order icons: a square with one arrow (one step) or two (all the way), up = forward.
function OrderIcon({ up = false, double = false }: { up?: boolean; double?: boolean }) {
  const head = (y: number) => up ? `M10.5 ${y + 2} L12.5 ${y} L14.5 ${y + 2}` : `M10.5 ${y - 2} L12.5 ${y} L14.5 ${y - 2}`
  return (
    <svg width={16} height={14} viewBox="0 0 16 14" fill="none" stroke="currentColor" strokeWidth={1.4} strokeLinecap="round" strokeLinejoin="round">
      <rect x={1} y={3} width={8} height={8} rx={1} />
      <path d={up ? 'M12.5 12 V2' : 'M12.5 2 V12'} />
      <path d={head(up ? 2 : 12)} />
      {double && <path d={head(up ? 5.5 : 8.5)} />}
    </svg>
  )
}
const snapTo = (v: number) => Math.round(v / GRID) * GRID

// Objects and links in view. Memoised: its props do not change while panning (the culling
// area is coarse), so a pan only moves the transform of the parent.
interface LayerProps {
  visible: Item[]; links: Item[]; byId: Map<string, Item>; boxOf: (it: Item) => Box
  selSet: Set<string>; matchSet: Set<string>; singleCard: string | null; editing: string | null
  linkFrom: string | null | 'armed'; canEdit: boolean; media: (it: Item) => string | undefined; faded: Set<string>
  badgeOf: (rid: string) => string | undefined
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
                        placeholder={p.placeholder} on={p.handlers} faded={p.faded.has(it.rid)} badges={p.badgeOf(it.rid)} />
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
  const [tool, setTool] = useState<Tool>('select')
  const hand = tool === 'hand'
  const drawing = tool === 'pen' || tool === 'highlighter' || tool === 'eraser'
  const [penColor, setPenColor] = useState('ink')
  const [draft, setDraft] = useState<Pt[] | null>(null)
  const [erasing, setErasing] = useState<Set<string>>(() => new Set())
  const [present, setPresent] = useState<number | null>(null)
  const [fluxPicker, setFluxPicker] = useState(false)
  const [templates, setTemplates] = useState<BoardTemplate[] | null>(null)
  const [showTemplates, setShowTemplates] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()
  const { settings } = useSettings()
  const { lang } = useTr()
  const [space, setSpace] = useState(false)
  const [panning, setPanning] = useState(false)
  const [snap, setSnap] = useState(true)
  const [showMap, setShowMap] = useState(true)
  // Dotted background: a per viewer choice kept on this machine (never written in the board).
  const [dots, setDots] = useState(() => { try { return localStorage.getItem('flux.board.dots') !== '0' } catch { return true } })
  const toggleDots = () => setDots(d => { try { localStorage.setItem('flux.board.dots', d ? '0' : '1') } catch { /* private mode */ } return !d })
  const [query, setQuery] = useState('')
  const [hit, setHit] = useState(-1)
  const surface = useRef<HTMLDivElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  const labelRef = useRef<HTMLInputElement>(null)
  const drag = useRef<Drag | null>(null)
  const clip = useRef<ClipData | null>(null)
  // The object under the last press: with the pointer captured by the surface (drag), the
  // double click lands on the surface, not on the object, so we remember which one it was.
  const lastDown = useRef<{ rid: string; t: number } | null>(null)

  // -- derived ---------------------------------------------------------------
  const items = data.records as Item[]
  const byId = useMemo(() => new Map(items.map(it => [it.rid, it])), [items])
  // Back to front: z, then creation order (a stable sort keeps the journal order).
  // Frames always behind the rest.
  const cards = useMemo(() => items.filter(it => !META_TYPES.has(it.type ?? ''))
    .sort((a, b) => (a.type === 'frame' ? 0 : 1) - (b.type === 'frame' ? 0 : 1) || (a.z ?? 0) - (b.z ?? 0)), [items])
  const frames = useMemo(() => readingOrder(cards.filter(c => c.type === 'frame')), [cards])
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
    return q ? items.filter(it => (it.type === 'link' || !META_TYPES.has(it.type ?? '')) && (it.text ?? it.label ?? '').toLowerCase().includes(q)) : []
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

  const fitBox = useCallback((all: Box | null, maxZ = 1.5) => {
    if (!all) { setView({ x: 40, y: 40, z: 1 }); return }
    const z = Math.max(ZOOM_MIN, Math.min(maxZ, Math.min((size.w - 60) / (all.w || 1), (size.h - 60) / (all.h || 1))))
    setView({ z, x: size.w / 2 - (all.x + all.w / 2) * z, y: size.h / 2 - (all.y + all.h / 2) * z })
  }, [size])
  const fit = useCallback(() => fitBox(bounds(cards.map(dims))), [cards, fitBox])
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
      if (!['image', 'link', 'ink', 'flux'].includes(String(fields.type))) setEditing(rids[0])
    }).catch(fail)
  }, [createRaw, pushCreated])

  const topZ = () => cards.reduce((m, c) => Math.max(m, c.z ?? 0), 0) + 1
  const addAtMiddle = (type: Item['type'], extra: Record<string, unknown> = {}) => {
    const [ow, oh] = SIZE[type ?? 'note']
    add({ type, ...middle(ow, oh), w: ow, h: oh, z: topZ(), text: '', ...extra })
  }

  const addImage = async () => {
    const path = await window.electronAPI?.openFile([{ name: 'Images', extensions: ['png', 'jpg', 'jpeg', 'gif', 'webp'] }])
    if (path) await addImageFrom(path)
  }

  // The backend COPIES the file into the board's media (ADR 0005); *at* = centre in board units.
  const addImageFrom = async (path: string, at?: { x: number; y: number }) => {
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
      const pos = at ? { x: Math.round(at.x - ow / 2), y: Math.round(at.y - oh / 2) } : middle(ow, oh)
      add({ type: 'image', image, ...pos, w: ow, h: oh, z: topZ() })
    } catch (err) { fail(err) }
  }

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    const files = [...e.dataTransfer.files]
    if (!files.length) return
    e.preventDefault()
    if (!canEdit) return
    const toPath = window.electronAPI?.pathForFile
    if (!toPath) { toast.info(tr('Deposer un fichier : seulement dans FLUX (Electron).', 'Dropping a file: only in the FLUX app.')); return }
    const p0 = toBoard(e.clientX, e.clientY)
    const images = files.filter(f => IMAGE_EXT.test(f.name))
    if (images.length < files.length) toast.info(tr('Seules les images sont acceptees (png, jpg, gif, webp).', 'Only images are accepted (png, jpg, gif, webp).'))
    images.forEach((f, i) => { const path = toPath(f); if (path) void addImageFrom(path, { x: p0.x + i * 40, y: p0.y + i * 40 }) })
  }

  const remove = useCallback((rids: string[]) => {
    const gone = new Set(rids.filter(r => byId.has(r) && !byId.get(r)!.locked))
    // An object takes its links with it.
    for (const l of links) if ((l.from && gone.has(l.from)) || (l.to && gone.has(l.to))) gone.add(l.rid)
    // ... and its comments and reactions (all authors: the object is gone).
    for (const it of items) if ((it.type === 'comment' || it.type === 'reaction') && it.target && gone.has(it.target)) gone.add(it.rid)
    if (!gone.size) return
    const recs = [...gone].map(r => byId.get(r)!)
    const redo: PageDataOp[] = recs.map(r => ({ op: 'del', rid: r.rid }))
    data.write(redo).then(() => history.push({ redo, undo: recs.map(restoreOp) })).catch(fail)
    setSelection([])
  }, [byId, links, items, data, history])

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
    const fromBoard = text ? parseClip(text) : null
    if (fromBoard) { await pasteItems(fromBoard, 'middle'); return }
    // A screenshot: Electron writes it as a temp file, the backend copies it (ADR 0074 n°2).
    if (!text.trim() && canEdit) {
      const img = await window.electronAPI?.saveClipboardImage?.().catch(() => null)
      if (img) { await addImageFrom(img); return }
    }
    if (!text && clip.current) { await pasteItems(clip.current, 'middle'); return }
    // Plain text: a note with it.
    if (text.trim() && canEdit) addAtMiddle('note', { color: 'yellow', text: text.slice(0, 10_000) })
  }

  // -- templates and FLUX cards ------------------------------------------------
  const openTemplates = () => {
    setShowTemplates(s => !s)
    if (!templates) flowsApi.boardTemplates().then(r => setTemplates(r.templates)).catch(fail)
  }
  // A template goes in like a paste: new rids, links re-pointed from the keys, one undo.
  const insertTemplate = (t: BoardTemplate) => {
    setShowTemplates(false)
    const list = t.items.map(({ key, text_en, ...f }) =>
      ({ ...f, rid: key, ...(lang === 'en' && typeof text_en === 'string' ? { text: text_en } : {}) })) as unknown as Item[]
    void pasteItems({ [CLIP_TAG]: 2, page: page.id, collection, items: list }, 'middle')
  }

  const hasFlux = useMemo(() => cards.some(c => c.type === 'flux'), [cards])
  const production = useBoardProduction(project, hasFlux || fluxPicker)
  const workspace = settings?.workspace
  const fluxCtx = useMemo<FluxBoardData>(() => ({
    project, payload: production,
    resolve: ref => resolveRef(production?.production, production?.publishes_by_task ?? {}, ref),
    open: t => navigate('/production', { state: { openFavorite: { project, class: t.group, name: t.name, task: 'ENTITY' } } }),
    reveal: t => { if (t.publish?.dest_folder) navigate('/projects', { state: { openPath: expandFluxPath(t.publish.dest_folder, workspace) } }) },
  }), [project, production, navigate, workspace])
  const addFlux = (ref: string) => { setFluxPicker(false); addAtMiddle('flux', { ref, text: null }) }

  // -- comments, reactions (one record per author, ADR 0075 n°2) -------------
  const notes = useMemo(() => {
    const m = new Map<string, { r: Map<Emoji, { n: number; mine?: Item }>; c: Item[] }>()
    for (const it of items) {
      if ((it.type !== 'reaction' && it.type !== 'comment') || !it.target) continue
      let e = m.get(it.target)
      if (!e) { e = { r: new Map(), c: [] }; m.set(it.target, e) }
      if (it.type === 'comment') e.c.push(it)
      else if (it.emoji && it.emoji in EMOJI) {
        const x = e.r.get(it.emoji) ?? { n: 0 }
        x.n++
        if (it._created_by === data.me) x.mine = it
        e.r.set(it.emoji, x)
      }
    }
    return m
  }, [items, data.me])
  const badgeOf = useCallback((rid: string) => {
    const e = notes.get(rid)
    if (!e) return undefined
    const parts = [...e.r].map(([k, v]) => `${k}:${v.n}:${v.mine ? 1 : 0}`)
    if (e.c.length) parts.push(`c:${e.c.length}:0`)
    return parts.join(' ') || undefined
  }, [notes])
  const [notesFor, setNotesFor] = useState<string | null>(null)
  const [draftComment, setDraftComment] = useState('')
  const delRecords = (recs: Item[]) => {
    const redo: PageDataOp[] = recs.map(r => ({ op: 'del', rid: r.rid }))
    data.write(redo).then(() => history.push({ redo, undo: recs.map(restoreOp) })).catch(fail)
  }
  const react = (rid: string, emoji: Emoji) => {
    if (!canEdit) return
    const mine = notes.get(rid)?.r.get(emoji)?.mine
    if (mine) { delRecords([mine]); return }
    const f = { type: 'reaction', target: rid, emoji }
    createRaw([f]).then(rids => pushCreated(rids, [f])).catch(fail)
  }
  const sendComment = (rid: string) => {
    const text = draftComment.trim()
    if (!text || !canEdit) return
    const f = { type: 'comment', target: rid, text: text.slice(0, 10_000) }
    setDraftComment('')
    createRaw([f]).then(rids => pushCreated(rids, [f])).catch(fail)
  }
  const when = (iso: string | null | undefined) => {
    if (!iso) return ''
    const d = new Date(iso)
    return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(lang === 'en' ? 'en-GB' : 'fr-FR', { dateStyle: 'short', timeStyle: 'short' })
  }

  // -- shared timer (ADR 0075 n°4) -------------------------------------------
  const timers = useMemo(() => items.filter(it => it.type === 'timer' && it.ends_at), [items])
  const timer = useMemo(() => [...timers].sort((a, b) => String(b._created_at ?? '').localeCompare(String(a._created_at ?? '')))[0], [timers])
  const [now, setNow] = useState(() => Date.now())
  const [showTimer, setShowTimer] = useState(false)
  useEffect(() => {
    if (!timer) return
    const t = setInterval(() => setNow(Date.now()), 500)
    return () => clearInterval(t)
  }, [timer])
  const left = timer ? Math.max(0, Math.round((new Date(timer.ends_at!).getTime() - now) / 1000)) : 0
  const rang = useRef<string | null>(null)
  useEffect(() => {
    if (timer && left === 0 && rang.current !== timer.rid) {
      rang.current = timer.rid
      toast.info(tr('Minuteur termine.', 'Timer finished.'))
    }
  }, [timer, left, tr])
  const startTimer = (minutes: number) => {
    setShowTimer(false)
    const ends = new Date(Date.now() + minutes * 60_000).toISOString().replace('Z', '+00:00')
    data.write([...timers.map(t => ({ op: 'del' as const, rid: t.rid })),
                { op: 'put', fields: { type: 'timer', ends_at: ends, seconds: minutes * 60 } }]).catch(fail)
  }
  const stopTimer = () => { if (timers.length) data.write(timers.map(t => ({ op: 'del' as const, rid: t.rid }))).catch(fail) }
  const clock = (sec: number) => `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}`

  // -- export PNG / PDF (redrawn from the records, ADR 0075 n°5) ---------------
  const [showExport, setShowExport] = useState(false)
  const [exporting, setExporting] = useState(false)
  const runExport = async (kind: 'png' | 'pdf', scope: 'board' | 'frame' | 'frames') => {
    setShowExport(false)
    const fluxText = (it: Item) => {
      const t = fluxCtx.resolve(it.ref ?? '')
      return t ? `${t.kind} ${t.group} / ${t.name}${t.task ? ` ${t.task}` : ''}${t.publish ? `\n${t.publish.file}` : ''}` : (it.ref ?? '')
    }
    const src = { cards, links, byId, media, fluxText }
    const picked = scope === 'board' ? [regionOf(cards.map(dims))]
      : scope === 'frame' ? selCards.filter(c => c.type === 'frame').slice(0, kind === 'png' ? 1 : undefined).map(f => regionOf([dims(f)]))
      : frames.map(f => regionOf([dims(f)]))
    const regions = picked.filter((r): r is Box => !!r)
    if (!regions.length) { toast.info(tr('Rien a exporter.', 'Nothing to export.')); return }
    setExporting(true)
    try {
      const canvases = await Promise.all(regions.map(r => renderBoard(src, r, 2)))
      const bytes = kind === 'png' ? await pngBytes(canvases[0]) : await pdfBytes(canvases)
      const name = `${page.id}_${scope === 'board' ? 'board' : scope === 'frame' ? (selCards.find(c => c.type === 'frame')?.text || 'cadre') : 'cadres'}.${kind}`
        .replace(/[\\/:*?"<>|]+/g, '_')
      const saved = await saveFile(name, bytes, kind)
      if (saved) toast.success(tr(`Exporte : ${saved}`, `Exported: ${saved}`))
    } catch (err) { fail(err) } finally { setExporting(false) }
  }

  // -- presentation (frames in reading order, nothing written) ----------------
  const startPresent = () => {
    if (!frames.length) { toast.info(tr('Aucun cadre a presenter.', 'No frame to present.')); return }
    setSelection([]); setEditing(null)
    setPresent(0)
    root.current?.requestFullscreen?.().catch(() => undefined)
  }
  const stopPresent = useCallback(() => {
    setPresent(null)
    if (document.fullscreenElement) document.exitFullscreen().catch(() => undefined)
  }, [])
  useEffect(() => {
    const onFs = () => { if (!document.fullscreenElement) setPresent(null) }
    document.addEventListener('fullscreenchange', onFs)
    return () => document.removeEventListener('fullscreenchange', onFs)
  }, [])
  useEffect(() => {
    if (present === null) return
    const f = frames[Math.min(present, frames.length - 1)]
    if (f) fitBox(dims(f), 4)
    surface.current?.focus()
  }, [present, frames, fitBox])

  const duplicate = () => { if (selCards.length) void pasteItems(clipOf(selCards.map(c => c.rid)), { dx: 24, dy: 24 }) }

  // -- arrange ---------------------------------------------------------------
  const order = (front: boolean) => {
    const sel = [...selCards].sort((a, b) => (a.z ?? 0) - (b.z ?? 0))
    if (!sel.length) return
    const base = front ? topZ() : cards.reduce((m, c) => Math.min(m, c.z ?? 0), 0) - sel.length
    update(sel.map((c, i) => ({ rid: c.rid, fields: { z: base + i } })))
  }
  // One step: just above (below) the next object the selection overlaps, in drawing order.
  const orderStep = (up: boolean) => {
    if (!selCards.length) return
    const block = bounds(selCards.map(dims))!
    const idx = selCards.map(c => cards.indexOf(c)).filter(i => i >= 0)
    const tier = (c: Item) => c.type === 'frame'
    const sameTier = (c: Item) => tier(c) === tier(selCards[0])
    const range = up ? cards.slice(Math.max(...idx) + 1) : cards.slice(0, Math.min(...idx)).reverse()
    const target = range.find(c => !selSet.has(c.rid) && sameTier(c) && intersects(dims(c), block))
    if (!target) { toast.info(up ? tr('Deja devant les objets voisins.', 'Already above its neighbours.') : tr('Deja derriere les objets voisins.', 'Already below its neighbours.')); return }
    const tz = target.z ?? 0
    const beyond = cards.filter(c => !selSet.has(c.rid) && sameTier(c) && (up ? (c.z ?? 0) > tz : (c.z ?? 0) < tz)).map(c => c.z ?? 0)
    const next = beyond.length ? (up ? Math.min(...beyond) : Math.max(...beyond)) : tz + (up ? 1 : -1)
    const sel = [...selCards].sort((a, b) => (a.z ?? 0) - (b.z ?? 0))
    const gap = (next - tz) / (sel.length + 1)
    update(sel.map((c, i) => ({ rid: c.rid, fields: { z: tz + gap * (i + 1) } })))
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

  // Eraser: every stroke under the pointer fades, then goes (whole strokes, ADR 0074 n°4).
  const eraseAt = (x: number, y: number) => {
    const tol = 6 / view.z
    const hits = visible.filter(c => c.type === 'ink' && !c.locked && !erasing.has(c.rid) && inkHit(c, x, y, tol))
    if (hits.length) setErasing(s => new Set([...s, ...hits.map(h => h.rid)]))
  }

  const onSurfaceDown = (e: RPointerEvent<HTMLDivElement>) => {
    lastDown.current = null
    if (editing) { setEditing(null); return }   // the textarea commits on blur
    if (e.button === 1 || e.button === 2 || hand || space) { e.preventDefault(); panStart(e); return }
    if (e.button !== 0) return
    if (linkFrom) { setLinkFrom(null); return }
    const p = toBoard(e.clientX, e.clientY)
    if (drawing && canEdit && present === null) {
      setSelection([])
      if (tool === 'eraser') { drag.current = { kind: 'erase' }; eraseAt(p.x, p.y) }
      else { drag.current = { kind: 'draw', pts: [[p.x, p.y]] }; setDraft([[p.x, p.y]]) }
      capture(e)
      return
    }
    const add = e.shiftKey ? selection : []
    if (!e.shiftKey) setSelection([])
    drag.current = { kind: 'marquee', bx: p.x, by: p.y, add }
    capture(e)
  }

  const onItemDown = (e: RPointerEvent, rid: string) => {
    if (e.button === 0) lastDown.current = { rid, t: Date.now() }
    if (e.button !== 0 || hand || space || drawing || editing === rid) return   // the surface pans or draws
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
    // A frame carries what lies entirely inside it.
    for (const r of Object.keys(start)) {
      if (byId.get(r)?.type !== 'frame') continue
      for (const c of cards) if (!start[c.rid] && c.type !== 'frame' && !c.locked && inside(dims(c), start[r])) start[c.rid] = dims(c)
    }
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
    if (d.kind === 'draw') {
      const p = toBoard(e.clientX, e.clientY), last = d.pts[d.pts.length - 1]
      if (Math.hypot(p.x - last[0], p.y - last[1]) * view.z < 2) return
      d.pts.push([p.x, p.y])
      setDraft([...d.pts])
      return
    }
    if (d.kind === 'erase') { const p = toBoard(e.clientX, e.clientY); eraseAt(p.x, p.y); return }
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
    if (d.kind === 'draw') {
      setDraft(null)
      const hl = tool === 'highlighter'
      const f = inkFields(d.pts, 0.8 / view.z)
      if (f) add({ type: 'ink', ...f, z: topZ(), stroke: penColor, stroke_width: hl ? 16 : 3, highlight: hl || null })
      return
    }
    if (d.kind === 'erase') {
      const rids = [...erasing]
      setErasing(new Set())
      if (rids.length) remove(rids)
      return
    }
    if (d.kind === 'marquee') {
      const m = marquee
      setMarquee(null)
      if (m && m.w + m.h > 2) {
        // A frame only when the rectangle holds all of it (else every selection inside a frame takes it).
        const hits = cards.filter(c => c.type === 'frame' ? inside(dims(c), m) : intersects(dims(c), m)).map(c => c.rid)
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
    // The whole widget listens (a click on a swatch or a button keeps Suppr working); text fields keep their keys.
    const target = e.target as HTMLElement
    if (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return
    const ctrl = e.ctrlKey || e.metaKey, k = e.key.toLowerCase()
    if (present !== null) {
      e.preventDefault()
      if (['ArrowRight', 'ArrowDown', 'PageDown', ' ', 'Enter'].includes(e.key)) setPresent(i => Math.min((i ?? 0) + 1, frames.length - 1))
      else if (['ArrowLeft', 'ArrowUp', 'PageUp', 'Backspace'].includes(e.key)) setPresent(i => Math.max((i ?? 0) - 1, 0))
      else if (e.key === 'Escape') stopPresent()
      return
    }
    if (e.key === 'Escape' && tool !== 'select') { setTool('select'); return }
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
    if (ctrl && (e.key === ']' || e.key === '[' || e.code === 'BracketRight' || e.code === 'BracketLeft')) {
      e.preventDefault()
      const up = e.key === ']' || e.code === 'BracketRight'
      if (e.shiftKey) order(up); else orderStep(up)
      return
    }
    if ((e.key === 'Delete' || e.key === 'Backspace') && selection.length) { e.preventDefault(); remove(selection); return }
    if (e.key === 'Enter' && selCards.length === 1 && selCards[0].type !== 'image') { e.preventDefault(); setEditing(selCards[0].rid) }
  }

  // Stable handlers for the memoised items: they call the latest closures.
  const latest = useRef({ onItemDown, onResizeDown, update, canEdit, byId, react })
  latest.current = { onItemDown, onResizeDown, update, canEdit, byId, react }
  const handlers = useMemo<ItemHandlers>(() => ({
    down: (e, rid) => latest.current.onItemDown(e, rid),
    double: rid => {
      const it = latest.current.byId.get(rid)
      if (latest.current.canEdit && it && !it.locked && it.type !== 'image') setEditing(rid)
    },
    commitText: (rid, text) => latest.current.update([{ rid, fields: { text } }]),
    stopEdit: () => setEditing(null),
    resize: (e, rid, corner) => latest.current.onResizeDown(e, rid, corner),
    react: (rid, emoji) => latest.current.react(rid, emoji),
    openNotes: rid => { setSelection([rid]); setNotesFor(rid) },
  }), [])
  const onLinkDown = useCallback((e: RPointerEvent, rid: string) => latest.current.onItemDown(e, rid), [])

  // -- render ----------------------------------------------------------------
  const btn = (title: string, onClick: () => void, icon: React.ReactNode, on = false, disabled = false) => (
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
  const singleCard = selCards.length === 1 && selection.length === 1 && !selCards[0].locked && selCards[0].type !== 'ink' && canEdit
    ? selCards[0].rid : null
  const placeholder = tr('Double clic pour ecrire', 'Double click to write')
  const media = useCallback((it: Item) => it.image ? flowsApi.pageImageUrl(page.id, collection, it.image, project) : undefined,
                            [page.id, collection, project])

  const presenting = present !== null
  const current = presenting ? frames[Math.min(present, frames.length - 1)] : undefined
  return (
    <FluxBoardContext.Provider value={fluxCtx}>
    <div ref={root} onKeyDown={onKey} onKeyUp={e => { if (e.key === ' ') setSpace(false) }} style={{ border: '1px solid var(--rule)', borderRadius: 8, background: 'var(--paper)', overflow: 'hidden',
                             ...(presenting ? { display: 'flex', flexDirection: 'column', height: '100%' } : {}) }}>
      {!presenting && <>
      <div style={{ display: 'flex', alignItems: 'center', gap: 2, padding: '6px 8px', borderBottom: '1px solid var(--rule)', flexWrap: 'wrap' }}>
        {w.label && <span style={{ fontSize: 12.5, fontWeight: 600, marginRight: 8 }}>{w.label}</span>}
        {btn(tr('Selection', 'Select'), () => setTool('select'), <MousePointer2 size={13} />, tool === 'select')}
        {btn(tr('Main (deplacer la vue, ou Espace)', 'Hand (pan, or Space)'), () => setTool('hand'), <Hand size={13} />, hand)}
        {canEdit && <>
          {sep}
          {btn(tr('Note', 'Note'), () => addAtMiddle('note', { color: 'yellow' }), <StickyNote size={13} />)}
          {btn(tr('Carte', 'Card'), () => addAtMiddle('card', { color: 'white' }), <Square size={13} />)}
          {btn(tr('Texte', 'Text'), () => addAtMiddle('text'), <Type size={13} />)}
          {btn(tr('Forme', 'Shape'), () => addAtMiddle('shape', { shape: 'rect', color: 'white', stroke: 'ink' }), <RectangleHorizontal size={13} />)}
          {window.electronAPI && btn(tr('Image (copiee dans le board)', 'Image (copied into the board)'), () => { void addImage() }, <ImagePlus size={13} />)}
          {btn(linkFrom ? tr('Clique l\'objet d\'arrivee', 'Click the target object') : tr('Lier deux objets', 'Link two objects'),
                () => setLinkFrom(l => l ? null : 'armed'), <Link2 size={13} />, !!linkFrom)}
          {btn(tr('Cadre', 'Frame'), () => addAtMiddle('frame', { color: 'grey', text: `${tr('Cadre', 'Frame')} ${frames.length + 1}`, z: 0 }), <Frame size={13} />)}
          {btn(tr('Carte FLUX (asset, shot, publish)', 'FLUX card (asset, shot, publish)'),
                () => { if (!project) toast.info(tr('Ouvre un projet pour poser une carte FLUX.', 'Open a project to drop a FLUX card.')); else setFluxPicker(s => !s) },
                <Clapperboard size={13} />, fluxPicker)}
          {btn(tr('Modeles de board', 'Board templates'), openTemplates, <LayoutTemplate size={13} />, showTemplates)}
          {sep}
          {btn(tr('Stylo', 'Pen'), () => setTool(t => t === 'pen' ? 'select' : 'pen'), <PenLine size={13} />, tool === 'pen')}
          {btn(tr('Surligneur', 'Highlighter'), () => { setTool(t => t === 'highlighter' ? 'select' : 'highlighter'); setPenColor(c => c === 'ink' ? 'yellow' : c) },
                <Highlighter size={13} />, tool === 'highlighter')}
          {btn(tr('Gomme (efface les traits entiers)', 'Eraser (removes whole strokes)'), () => setTool(t => t === 'eraser' ? 'select' : 'eraser'),
                <Eraser size={13} />, tool === 'eraser')}
          {sep}
          {btn(tr('Annuler (Ctrl+Z, tes actions seulement)', 'Undo (Ctrl+Z, your own actions only)'), () => { history.undo().catch(fail) }, <Undo2 size={13} />, false, !history.canUndo)}
          {btn(tr('Retablir (Ctrl+Y)', 'Redo (Ctrl+Y)'), () => { history.redo().catch(fail) }, <Redo2 size={13} />, false, !history.canRedo)}
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
        {btn(tr('Magnetisme (grille et alignement ; Alt pour l\'ignorer)', 'Snapping (grid and alignment; Alt to skip)'), () => setSnap(s => !s), <Magnet size={13} />, snap)}
        {btn(tr('Mini-carte', 'Minimap'), () => setShowMap(s => !s), <MapIcon size={13} />, showMap)}
        {btn(tr('Points du fond', 'Background dots'), toggleDots, <Grid3x3 size={13} />, dots)}
        {btn(tr('Zoom arriere', 'Zoom out'), () => setView(v => ({ ...v, z: Math.max(ZOOM_MIN, v.z / 1.2) })), <Minus size={13} />)}
        <span className="cap" style={{ minWidth: 38, textAlign: 'center' }}>{Math.round(view.z * 100)} %</span>
        {btn(tr('Zoom avant', 'Zoom in'), () => setView(v => ({ ...v, z: Math.min(ZOOM_MAX, v.z * 1.2) })), <Plus size={13} />)}
        {btn(tr('Tout voir (Maj+1)', 'Fit (Shift+1)'), fit, <Maximize size={13} />)}
        {btn(tr('Presenter les cadres', 'Present the frames'), startPresent, <Play size={13} />, false, !frames.length)}
        {btn(tr('Exporter en PNG ou PDF', 'Export as PNG or PDF'), () => setShowExport(s => !s), <Download size={13} />, showExport, exporting || !cards.length)}
        {timer
          ? <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, marginLeft: 4, padding: '0 6px', height: 22, borderRadius: 5, fontSize: 12,
                           fontVariantNumeric: 'tabular-nums', background: left === 0 ? 'oklch(88% 0.07 25)' : 'var(--paper-2)', color: left === 0 ? 'oklch(35% 0.1 25)' : 'var(--ink)' }}
                  title={tr('Minuteur partage avec tout le board', 'Timer shared with the whole board')}>
              <Timer size={12} />{left === 0 ? tr('Termine', 'Done') : clock(left)}
              {canEdit && <button type="button" onClick={stopTimer} title={tr('Arreter le minuteur', 'Stop the timer')}
                                  style={{ border: 'none', background: 'transparent', cursor: 'pointer', color: 'inherit', padding: 0, display: 'inline-flex' }}><X size={12} /></button>}
            </span>
          : canEdit && btn(tr('Minuteur partage', 'Shared timer'), () => setShowTimer(s => !s), <Timer size={13} />, showTimer)}
      </div>


      </>}

      <div ref={surface} tabIndex={0}
           onBlur={() => setSpace(false)} onContextMenu={e => e.preventDefault()}
           onPointerDown={onSurfaceDown} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp}
           onDragOver={e => { if (e.dataTransfer.types.includes('Files')) e.preventDefault() }} onDrop={onDrop}
           onDoubleClick={e => {
             const hit = lastDown.current
             if (hit && Date.now() - hit.t < 700) { handlers.double(hit.rid); return }   // an object: edit its text (a frame: its name)
             if (canEdit && !drawing && !presenting && e.target === e.currentTarget) { const p = toBoard(e.clientX, e.clientY); add({ type: 'note', color: 'yellow', text: '', x: Math.round(p.x - 90), y: Math.round(p.y - 60), z: topZ() }) } }}
           style={{ position: 'relative', height: presenting ? undefined : height, flex: presenting ? 1 : undefined,
                    overflow: 'hidden', outline: 'none', touchAction: 'none',
                    cursor: linkFrom || drawing ? 'crosshair' : panning ? 'grabbing' : hand || space ? 'grab' : 'default',
                    backgroundColor: 'var(--bg-deep)',
                    backgroundImage: dots ? 'radial-gradient(var(--rule) 1px, transparent 1px)' : 'none',
                    backgroundSize: `${24 * view.z}px ${24 * view.z}px`, backgroundPosition: `${view.x}px ${view.y}px` }}>
        <div style={{ position: 'absolute', left: 0, top: 0, transformOrigin: '0 0', transform: `translate(${view.x}px, ${view.y}px) scale(${view.z})`, pointerEvents: 'none' }}>
          <BoardLayer visible={visible} links={visibleLinks} byId={byId} boxOf={boxOf} selSet={selSet} matchSet={matchSet}
                      singleCard={singleCard} editing={editing} linkFrom={linkFrom} canEdit={canEdit} media={media}
                      placeholder={placeholder} handlers={handlers} onLinkDown={onLinkDown} faded={erasing} badgeOf={badgeOf} />
          {draft && draft.length > 0 && <svg style={{ position: 'absolute', left: 0, top: 0, overflow: 'visible', zIndex: 3 }} width={1} height={1}>
            <polyline points={draft.map(q => `${q[0]},${q[1]}`).join(' ')} fill="none" stroke={STROKES[penColor] ?? STROKES.ink}
                      strokeWidth={tool === 'highlighter' ? 16 : 3} strokeLinecap="round" strokeLinejoin="round" opacity={tool === 'highlighter' ? 0.4 : 1} />
          </svg>}
          {guides.length > 0 && <svg style={{ position: 'absolute', left: 0, top: 0, overflow: 'visible', zIndex: 3 }} width={1} height={1}>
            {guides.map((g, i) => g.x !== undefined
              ? <line key={i} x1={g.x} x2={g.x} y1={viewport.y} y2={viewport.y + viewport.h} stroke="var(--accent)" strokeWidth={1 / view.z} strokeDasharray={`${4 / view.z} ${3 / view.z}`} />
              : <line key={i} y1={g.y} y2={g.y} x1={viewport.x} x2={viewport.x + viewport.w} stroke="var(--accent)" strokeWidth={1 / view.z} strokeDasharray={`${4 / view.z} ${3 / view.z}`} />)}
          </svg>}
          {marquee && <div style={{ position: 'absolute', left: marquee.x, top: marquee.y, width: marquee.w, height: marquee.h, zIndex: 4,
                                    border: `${1 / view.z}px solid var(--accent)`, background: 'oklch(60% 0.12 245 / 0.08)' }} />}
        </div>
        {!presenting && (
          // Over the board, not above it: selecting never pushes the board down.
          <div onPointerDown={e => e.stopPropagation()} onDoubleClick={e => e.stopPropagation()} onWheel={e => e.stopPropagation()}
               style={{ position: 'absolute', top: 8, left: '50%', transform: 'translateX(-50%)', zIndex: 6, maxWidth: 'calc(100% - 20px)',
                        display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4, pointerEvents: 'none' }}>
            <div style={{ pointerEvents: 'auto', display: 'contents' }}>
      {canEdit && (tool === 'pen' || tool === 'highlighter') && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 3, padding: '4px 8px', background: 'var(--paper)', border: '1px solid var(--rule)', borderRadius: 8, boxShadow: '0 2px 8px oklch(0% 0 0 / 0.18)' }}>
          <span className="cap" style={{ marginRight: 6 }}>{tool === 'pen' ? tr('Stylo', 'Pen') : tr('Surligneur', 'Highlighter')}</span>
          {Object.entries(STROKES).filter(([k]) => k !== 'none').map(([k, css]) => swatch(k, css, penColor === k, () => setPenColor(k), true))}
          <span className="cap" style={{ marginLeft: 8, color: 'var(--ink-4)' }}>{tr('Echap pour sortir', 'Esc to leave')}</span>
        </div>
      )}

      {canEdit && selection.length > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 3, padding: '4px 8px', flexWrap: 'wrap', justifyContent: 'center', background: 'var(--paper)', border: '1px solid var(--rule)', borderRadius: 8, boxShadow: '0 2px 8px oklch(0% 0 0 / 0.18)' }}>
          <span className="cap" style={{ marginRight: 6 }}>{selection.length} {tr('selectionne(s)', 'selected')}</span>
          {selCards.length > 0 && <>
            {Object.entries(FILLS).map(([k, css]) => swatch(k, css, one(selCards, i => i.color) === k, () => style({ color: k })))}
            {sep}
            {Object.entries(STROKES).map(([k, css]) => swatch(k, css, one(selCards, i => i.stroke) === k, () => style({ stroke: k }), true))}
            {sep}
            {btn(tr('Texte plus petit', 'Smaller text'), () => fontStep(-1), <span style={{ fontSize: 10 }}>A-</span>)}
            <span className="cap" style={{ minWidth: 20, textAlign: 'center' }}>{one(selCards, fontOf) ?? '-'}</span>
            {btn(tr('Texte plus grand', 'Bigger text'), () => fontStep(1), <span style={{ fontSize: 13 }}>A+</span>)}
            {btn(tr('Gras', 'Bold'), () => style({ bold: one(selCards, i => !!i.bold) ? null : true }), <Bold size={13} />, !!one(selCards, i => !!i.bold))}
            {selCards.some(c => c.type === 'shape') && <>
              {sep}
              {([['rect', <Square size={13} key="r" />], ['round', <Squircle size={13} key="o" />], ['ellipse', <Circle size={13} key="e" />],
                 ['diamond', <Diamond size={13} key="d" />]] as [Shape, React.ReactNode][]).map(([s, icon]) =>
                <span key={s}>{btn(s, () => update(selCards.filter(c => c.type === 'shape').map(c => ({ rid: c.rid, fields: { shape: s } }))), icon,
                                    one(selCards.filter(c => c.type === 'shape'), i => i.shape ?? 'rect') === s)}</span>)}
            </>}
            {sep}
          </>}
          {selLinks.length > 0 && <>
            {Object.entries(STROKES).filter(([k]) => k !== 'none').map(([k, css]) => swatch(k, css, one(selLinks, i => i.stroke) === k, () => style({ stroke: k }, 'links'), true))}
            {sep}
            {(['solid', 'dashed', 'dotted'] as const).map(d => (
              <span key={d}>{btn(d, () => style({ dash: d }, 'links'),
                <svg width={18} height={8}><line x1={1} y1={4} x2={17} y2={4} stroke="currentColor" strokeWidth={1.5}
                                                 strokeDasharray={d === 'dashed' ? '5 3' : d === 'dotted' ? '1.5 2.5' : undefined} /></svg>,
                (one(selLinks, i => i.dash ?? 'solid')) === d)}</span>
            ))}
            {btn(tr('Fleche au debut', 'Arrow at start'), () => style({ arrow_start: one(selLinks, i => !!i.arrow_start) ? null : true }, 'links'), <MoveLeft size={13} />, !!one(selLinks, i => !!i.arrow_start))}
            {btn(tr('Fleche a la fin', 'Arrow at end'), () => style({ arrow_end: one(selLinks, i => !!i.arrow_end) ? null : true }, 'links'), <MoveRight size={13} />, !!one(selLinks, i => !!i.arrow_end))}
            {singleLink && <input key={singleLink.rid} ref={labelRef} defaultValue={singleLink.label ?? ''} placeholder={tr('Libelle', 'Label')}
                                  onBlur={e => { if (e.target.value !== (singleLink.label ?? '')) update([{ rid: singleLink.rid, fields: { label: e.target.value || null } }]) }}
                                  onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
                                  style={{ width: 120, height: 22, padding: '0 6px', border: '1px solid var(--rule-2)', borderRadius: 4, background: 'var(--bg-deep)', color: 'var(--ink)', fontSize: 12 }} />}
            {sep}
          </>}
          {selCards.length > 0 && <>
            {btn(tr('Avancer d\u2019un cran (Ctrl+])', 'Bring forward (Ctrl+])'), () => orderStep(true), <OrderIcon up />)}
            {btn(tr('Reculer d\u2019un cran (Ctrl+[)', 'Send backward (Ctrl+[)'), () => orderStep(false), <OrderIcon />)}
            {btn(tr('Tout devant (Ctrl+Maj+])', 'Bring to front (Ctrl+Shift+])'), () => order(true), <OrderIcon up double />)}
            {btn(tr('Tout derriere (Ctrl+Maj+[)', 'Send to back (Ctrl+Shift+[)'), () => order(false), <OrderIcon double />)}
            {selCards.some(c => c.group)
              ? btn(tr('Degrouper (Ctrl+Maj+G)', 'Ungroup (Ctrl+Shift+G)'), () => group(false), <Ungroup size={13} />)
              : btn(tr('Grouper (Ctrl+G)', 'Group (Ctrl+G)'), () => group(true), <Group size={13} />, false, selCards.length < 2)}
            {btn(selCards.every(c => c.locked) ? tr('Deverrouiller (Ctrl+L)', 'Unlock (Ctrl+L)') : tr('Verrouiller (Ctrl+L)', 'Lock (Ctrl+L)'), lock,
                  selCards.every(c => c.locked) ? <LockOpen size={13} /> : <Lock size={13} />, selCards.every(c => c.locked))}
            {btn(tr('Dupliquer (Ctrl+D)', 'Duplicate (Ctrl+D)'), duplicate, <Copy size={13} />)}
          </>}
          {selection.length === 1 && byId.get(selection[0]) && btn(tr('Commentaires, reactions, auteur', 'Comments, reactions, author'),
                () => setNotesFor(f => f === selection[0] ? null : selection[0]), <MessageSquare size={13} />, notesFor === selection[0])}
          {btn(tr('Supprimer (Suppr)', 'Delete (Del)'), () => remove(selection), <Trash2 size={13} />)}
        </div>
      )}
            </div>
          </div>
        )}
        {presenting && current && (
          <div style={{ position: 'absolute', left: '50%', bottom: 14, transform: 'translateX(-50%)', display: 'flex', alignItems: 'center', gap: 6, zIndex: 6,
                        padding: '4px 8px', background: 'var(--paper)', border: '1px solid var(--rule)', borderRadius: 6, boxShadow: '0 2px 6px oklch(0% 0 0 / 0.2)' }}>
            {btn(tr('Precedent', 'Previous'), () => setPresent(i => Math.max((i ?? 0) - 1, 0)), <ChevronLeft size={14} />, false, present === 0)}
            <span className="cap" style={{ minWidth: 120, textAlign: 'center' }}>{(present ?? 0) + 1} / {frames.length} · {current.text || tr('Cadre', 'Frame')}</span>
            {btn(tr('Suivant', 'Next'), () => setPresent(i => Math.min((i ?? 0) + 1, frames.length - 1)), <ChevronRight size={14} />, false, present === frames.length - 1)}
            {btn(tr('Quitter (Echap)', 'Leave (Esc)'), stopPresent, <X size={14} />)}
          </div>
        )}
        {fluxPicker && <FluxPicker payload={production} onPick={addFlux} onClose={() => setFluxPicker(false)} />}
        {showTemplates && (
          <div onPointerDown={e => e.stopPropagation()} onWheel={e => e.stopPropagation()}
               style={{ position: 'absolute', left: 10, top: 10, width: 280, zIndex: 8, background: 'var(--paper)', border: '1px solid var(--rule)',
                        borderRadius: 8, boxShadow: '0 4px 14px oklch(0% 0 0 / 0.2)' }}>
            <div style={{ display: 'flex', alignItems: 'center', padding: '6px 8px', borderBottom: '1px solid var(--rule)' }}>
              <span className="cap">{tr('Inserer un modele au centre', 'Insert a template in the middle')}</span>
              <span style={{ flex: 1 }} />
              {btn(tr('Fermer', 'Close'), () => setShowTemplates(false), <X size={13} />)}
            </div>
            {!templates ? <div className="tp-note" style={{ padding: 10 }}>{tr('Chargement...', 'Loading...')}</div>
              : templates.map(t => (
                <div key={t.id} onClick={() => insertTemplate(t)} style={{ padding: '6px 10px', cursor: 'pointer', borderTop: '1px solid var(--rule)' }}>
                  <div style={{ fontSize: 12.5, fontWeight: 600 }}>{lang === 'en' ? t.label_en : t.label}</div>
                  <div style={{ fontSize: 11.5, color: 'var(--ink-3)' }}>{lang === 'en' ? t.description_en : t.description}</div>
                </div>
              ))}
          </div>
        )}
        {notesFor && byId.get(notesFor) && selection.includes(notesFor) && (() => {
          const it = byId.get(notesFor)!, e = notes.get(notesFor)
          return (
            <div onPointerDown={ev => ev.stopPropagation()} onWheel={ev => ev.stopPropagation()} onKeyDown={ev => ev.stopPropagation()}
                 style={{ position: 'absolute', right: 10, top: 10, bottom: 10, width: 290, zIndex: 7, display: 'flex', flexDirection: 'column',
                          background: 'var(--paper)', border: '1px solid var(--rule)', borderRadius: 8, boxShadow: '0 4px 14px oklch(0% 0 0 / 0.2)' }}>
              <div style={{ display: 'flex', alignItems: 'center', padding: '6px 8px', borderBottom: '1px solid var(--rule)' }}>
                <span style={{ fontSize: 12.5, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {(it.text || it.label || it.type || '').slice(0, 40)}</span>
                <span style={{ flex: 1 }} />
                {btn(tr('Fermer', 'Close'), () => setNotesFor(null), <X size={13} />)}
              </div>
              <div className="tp-note" style={{ padding: '6px 10px', fontSize: 11.5, color: 'var(--ink-3)', borderBottom: '1px solid var(--rule)' }}>
                {tr('Cree par', 'Created by')} <b>{it._created_by || '?'}</b> {when(it._created_at)}<br />
                {tr('Modifie par', 'Changed by')} <b>{it._by || '?'}</b> {when(it._at)}
              </div>
              <div style={{ display: 'flex', gap: 4, padding: '6px 10px', borderBottom: '1px solid var(--rule)' }}>
                {(Object.keys(EMOJI) as Emoji[]).map(k => {
                  const r = e?.r.get(k)
                  return <button key={k} type="button" disabled={!canEdit} onClick={() => react(notesFor, k)}
                                 style={{ fontSize: 13, padding: '1px 6px', borderRadius: 10, cursor: canEdit ? 'pointer' : 'default', color: 'var(--ink)',
                                          background: r?.mine ? 'var(--paper-2)' : 'transparent', border: r?.mine ? '1.5px solid var(--accent)' : '1px solid var(--rule-2)' }}>
                    {EMOJI[k]}{r ? ` ${r.n}` : ''}</button>
                })}
              </div>
              <div style={{ flex: 1, overflow: 'auto', padding: '4px 10px' }}>
                {!(e?.c.length) && <div className="tp-note" style={{ color: 'var(--ink-4)', padding: '6px 0' }}>{tr('Aucun commentaire.', 'No comment.')}</div>}
                {e?.c.map(c => (
                  <div key={c.rid} style={{ padding: '6px 0', borderBottom: '1px solid var(--rule)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11.5 }}>
                      <b>{c._created_by}</b><span style={{ color: 'var(--ink-4)' }}>{when(c._created_at)}</span>
                      <span style={{ flex: 1 }} />
                      {canEdit && c._created_by === data.me && <button type="button" title={tr('Supprimer mon commentaire', 'Delete my comment')} onClick={() => delRecords([c])}
                                  style={{ border: 'none', background: 'transparent', cursor: 'pointer', color: 'var(--ink-4)', padding: 0 }}><X size={11} /></button>}
                    </div>
                    <div style={{ fontSize: 12.5, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{c.text}</div>
                  </div>
                ))}
              </div>
              {canEdit && <div style={{ padding: 8, borderTop: '1px solid var(--rule)' }}>
                <textarea value={draftComment} onChange={ev => setDraftComment(ev.target.value)} rows={2}
                          placeholder={tr('Commenter (@nom previent l\u2019artiste, Ctrl+Entree pour envoyer)', 'Comment (@name notifies the artist, Ctrl+Enter to send)')}
                          onKeyDown={ev => { if (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); sendComment(notesFor) } }}
                          style={{ width: '100%', boxSizing: 'border-box', resize: 'vertical', padding: 6, border: '1px solid var(--rule-2)', borderRadius: 5,
                                   background: 'var(--bg-deep)', color: 'var(--ink)', font: 'inherit', fontSize: 12.5 }} />
                <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 4 }}>
                  <button type="button" className="btn sm" disabled={!draftComment.trim()} onClick={() => sendComment(notesFor)}>{tr('Envoyer', 'Send')}</button>
                </div>
              </div>}
            </div>
          )
        })()}
        {showTimer && (
          <div onPointerDown={ev => ev.stopPropagation()}
               style={{ position: 'absolute', right: 10, top: 10, zIndex: 8, display: 'flex', gap: 4, padding: 8, alignItems: 'center',
                        background: 'var(--paper)', border: '1px solid var(--rule)', borderRadius: 8, boxShadow: '0 4px 14px oklch(0% 0 0 / 0.2)' }}>
            <span className="cap" style={{ marginRight: 4 }}>{tr('Minuteur pour tous', 'Timer for everyone')}</span>
            {[1, 3, 5, 10, 15].map(m => <button key={m} type="button" className="btn ghost sm" onClick={() => startTimer(m)}>{m} min</button>)}
          </div>
        )}
        {showExport && (
          <div onPointerDown={ev => ev.stopPropagation()}
               style={{ position: 'absolute', right: 10, top: 10, zIndex: 8, width: 240, background: 'var(--paper)', border: '1px solid var(--rule)',
                        borderRadius: 8, boxShadow: '0 4px 14px oklch(0% 0 0 / 0.2)', padding: 4 }}>
            {([['png', 'board', tr('PNG du board entier', 'PNG of the whole board'), true],
               ['png', 'frame', tr('PNG du cadre selectionne', 'PNG of the selected frame'), selCards.some(c => c.type === 'frame')],
               ['pdf', 'board', tr('PDF du board entier', 'PDF of the whole board'), true],
               ['pdf', 'frame', tr('PDF des cadres selectionnes', 'PDF of the selected frames'), selCards.some(c => c.type === 'frame')],
               ['pdf', 'frames', tr('PDF de tous les cadres (ordre de lecture)', 'PDF of every frame (reading order)'), frames.length > 0]] as const)
              .map(([kind, scope, label, ok]) => (
                <button key={`${kind}${scope}`} type="button" disabled={!ok} onClick={() => { void runExport(kind, scope) }}
                        style={{ display: 'block', width: '100%', textAlign: 'left', padding: '6px 8px', border: 'none', borderRadius: 5, fontSize: 12.5,
                                 background: 'transparent', color: ok ? 'var(--ink)' : 'var(--ink-4)', cursor: ok ? 'pointer' : 'default' }}>{label}</button>
              ))}
          </div>
        )}
        {showMap && !presenting && cards.length > 0 && <BoardMinimap boxes={boxes} viewport={viewport} onCenter={(x, y) => centreOn({ x, y, w: 0, h: 0 })} />}
        {data.error && <div className="tp-note" style={{ position: 'absolute', left: 10, bottom: 8, color: preview ? undefined : 'var(--err)' }}>
          {preview ? tr('Apercu : enregistre la page pour lire ses donnees.', 'Preview: save the page to read its data.') : data.error}</div>}
        {data.loaded && !cards.length && !data.error && (
          <div className="tp-note" style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--ink-4)', pointerEvents: 'none' }}>
            {canEdit ? tr('Board vide : double clic pour poser une note', 'Empty board: double click to drop a note') : tr('Board vide', 'Empty board')}
          </div>
        )}
      </div>
    </div>
    </FluxBoardContext.Provider>
  )
}
