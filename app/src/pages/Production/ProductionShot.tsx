// ProductionShot — DaVinci-style timeline with two ordered tracks.
//
// Layout:
//   ┌──────────┬───────────────────────────────────────────┐
//   │ SEQUENCE │  [ 001 ]  [ 002 ]  [ 003 ] …              │  ← taller row
//   ├──────────┼───────────────────────────────────────────┤  ← drag handle
//   │  SHOT    │  [010][020]   [010]   [010][020][030]      │  ← smaller row
//   └──────────┴───────────────────────────────────────────┘
//
// - Left column: two solid colored blocks with track name (accent color per track).
// - Right side: each row background is a darkened tint of its track color.
// - Clip content: big number ("001") + optional label under it.
// - Row heights persist in localStorage and are adjustable via a drag handle.
// - Sequences and shots are ordered by their `order` field. Newly created seqs
//   get an `order` that places them right before the next-higher SEQ number.

import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowDownUp, Bookmark, ChevronLeft, ChevronRight, Minus, MoveVertical, Plus } from 'lucide-react'
import { api } from '../../api/client'
import { useProject } from '../../ProjectContext'
import { useI18n } from '../../i18n'
import type {
  ProductionSequence, ProductionShot as Shot, ProductionState,
} from '../../types'
import type { Selection } from './Production'
import { defaultSeqColor, shotColorFromSeqColor } from './util'

interface Props {
  state:           ProductionState
  setState:        (patch: (prev: ProductionState) => ProductionState) => void
  selection:       Selection
  setSelection:    (s: Selection) => void
  onEntityClicked?: () => void
}

// H zoom == per-shot width. Min is intentionally tiny so a whole sequence can be
// squashed to a compact overview (shots become thin slivers); the number/label
// just clip out at small sizes.
const ZOOM_MIN = 3
const ZOOM_MAX = 260
const ZOOM_DEF = 120
const LS_ZOOM = 'flux.production.shot.zoom'

const SEQ_ROW_DEF = 84
const SHOT_ROW_DEF = 40
const ROW_MIN = 30
const ROW_MAX = 220
const LS_SEQ_H = 'flux.production.shot.seqRowH'
const LS_SHOT_H = 'flux.production.shot.shotRowH'

const VZOOM_MIN = 0.6
const VZOOM_MAX = 3.0
const VZOOM_DEF = 1.0
const LS_VZOOM = 'flux.production.shot.vzoom'

// Bookmarks are per-user (stored in User.json via /settings/user-data under
// `production.bookmarks.<project>`). Not scoped to the machine.
type BookmarkKind = 'seq' | 'shot'
interface Bookmark { kind: BookmarkKind; entityId: string }

function sanitizeBookmarks(raw: unknown): Bookmark[] {
  if (!Array.isArray(raw)) return []
  return raw.filter((b: unknown): b is Bookmark => {
    const x = b as Bookmark
    return !!x && (x.kind === 'seq' || x.kind === 'shot') && typeof x.entityId === 'string'
  })
}

async function loadBookmarksForProject(project: string): Promise<Bookmark[]> {
  if (!project) return []
  try {
    const data = await api.getUserData()
    const prod = (data.production ?? {}) as { bookmarks?: Record<string, unknown> }
    return sanitizeBookmarks(prod.bookmarks?.[project])
  } catch { return [] }
}

async function saveBookmarksForProject(project: string, list: Bookmark[]) {
  if (!project) return
  try {
    const data = await api.getUserData()
    const prod = ((data.production ?? {}) as Record<string, unknown>)
    const bookmarks = { ...(prod.bookmarks as Record<string, unknown> | undefined ?? {}), [project]: list }
    await api.setUserData({ production: { ...prod, bookmarks } })
  } catch { /* keep local optimistic state */ }
}

const HEADER_W = 118

function parseNum(name: string, prefix: 'SEQ' | 'SHOT'): number {
  const m = name.toUpperCase().match(new RegExp(`^${prefix}(\\d+)`))
  return m ? Number(m[1]) : Number.NaN
}

function useLocalNumber(key: string, def: number, clampMin: number, clampMax: number): [number, (n: number) => void] {
  const [v, setV] = useState<number>(() => {
    try { const s = Number(localStorage.getItem(key)); if (!Number.isNaN(s) && s > 0) return Math.min(clampMax, Math.max(clampMin, s)) } catch { /* blocked */ }
    return def
  })
  const set = (n: number) => {
    const c = Math.min(clampMax, Math.max(clampMin, n))
    setV(c)
    try { localStorage.setItem(key, String(c)) } catch { /* blocked */ }
  }
  return [v, set]
}

export function ProductionShot({ state, setState, selection, setSelection, onEntityClicked }: Props) {
  const { t } = useI18n()
  const { project } = useProject()

  const [pxPerBlock, setZoom] = useLocalNumber(LS_ZOOM, ZOOM_DEF, ZOOM_MIN, ZOOM_MAX)
  const [seqRowH,   setSeqRowH]  = useLocalNumber(LS_SEQ_H,  SEQ_ROW_DEF,  ROW_MIN, ROW_MAX)
  const [shotRowH,  setShotRowH] = useLocalNumber(LS_SHOT_H, SHOT_ROW_DEF, ROW_MIN, ROW_MAX)
  const [vZoom, setVZoom] = useState<number>(() => {
    try { const v = Number(localStorage.getItem(LS_VZOOM)); if (!Number.isNaN(v) && v > 0) return Math.max(VZOOM_MIN, Math.min(VZOOM_MAX, v)) } catch { /* blocked */ }
    return VZOOM_DEF
  })
  const setVZ = (v: number) => {
    const c = Math.max(VZOOM_MIN, Math.min(VZOOM_MAX, v))
    setVZoom(c)
    try { localStorage.setItem(LS_VZOOM, String(c)) } catch { /* blocked */ }
  }
  // Effective row heights (base × vertical zoom).
  const effSeqH  = Math.round(seqRowH * vZoom)
  const effShotH = Math.round(shotRowH * vZoom)

  const sequences = useMemo(
    () => [...state.sequences].sort((a, b) => a.order - b.order),
    [state.sequences],
  )
  const shotsBySeq = useMemo(() => {
    const m = new Map<string, Shot[]>()
    for (const s of state.shots) {
      const list = m.get(s.seq_id) ?? []
      list.push(s)
      m.set(s.seq_id, list)
    }
    for (const list of m.values()) list.sort((a, b) => a.order - b.order)
    return m
  }, [state.shots])

  // Column widths per seq: at least one seq-block wide, growing with shot count.
  // Shots are small fixed-size squares — they don't stretch with the horizontal
  // zoom (which controls seq width instead).
  // Gaps shrink with the zoom so a squashed sequence stays a compact row of slivers.
  const gap = pxPerBlock < 12 ? 3 : 6
  const shotGap = pxPerBlock < 12 ? 1 : 4
  const shotSquare = Math.max(24, Math.min(42, Math.round(effShotH * 0.62)))
  // Timeline is purely visual (no create/delete by resize). The horizontal zoom
  // slider sizes EACH SHOT directly; the sequence column is just the sum of its
  // shots, so it grows both with the zoom and with the shot count — the sequence
  // follows its shots. An empty sequence still shows one shot-wide block.
  const shotW = pxPerBlock
  const colWidths = sequences.map(seq => {
    const n = shotsBySeq.get(seq.id)?.length ?? 0
    const content = n > 0 ? n * shotW + (n - 1) * shotGap : shotW
    return content + gap
  })

  // Drag handle between the two tracks
  const dragRef = useRef<{ startY: number; startSeq: number; startShot: number } | null>(null)
  const onHandleDown = (e: React.MouseEvent) => {
    e.preventDefault()
    dragRef.current = { startY: e.clientY, startSeq: seqRowH, startShot: shotRowH }
    const onMove = (ev: MouseEvent) => {
      const d = dragRef.current
      if (!d) return
      const delta = ev.clientY - d.startY
      // Symmetric: dragging down grows SEQ, shrinks SHOT.
      setSeqRowH(d.startSeq + delta)
      setShotRowH(d.startShot - delta)
    }
    const onUp = () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
      dragRef.current = null
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }

  // ── bookmarks (per-user, stored in User.json) ────────────────────────────
  const [bookmarks, setBookmarks] = useState<Bookmark[]>([])
  const projectKey = project || ''
  useEffect(() => {
    let alive = true
    if (!projectKey) { setBookmarks([]); return }
    void loadBookmarksForProject(projectKey).then(list => { if (alive) setBookmarks(list) })
    return () => { alive = false }
  }, [projectKey])
  const persistBookmarks = (list: Bookmark[]) => {
    setBookmarks(list)   // optimistic
    void saveBookmarksForProject(projectKey, list)
  }
  // Compute the x coordinate (inside the scroll wrapper, after the sticky
  // HEADER_W) of a given bookmark. Returns null when the target no longer
  // exists in state.
  const scrollWrapRef = useRef<HTMLDivElement | null>(null)
  const bookmarkX = (bm: Bookmark): number | null => {
    if (bm.kind === 'seq') {
      const idx = sequences.findIndex(s => s.id === bm.entityId)
      if (idx < 0) return null
      const before = colWidths.slice(0, idx).reduce((a, b) => a + b, 0)
      return HEADER_W + 10 + before
    }
    // shot
    const shot = state.shots.find(s => s.id === bm.entityId)
    if (!shot) return null
    const seqIdx = sequences.findIndex(s => s.id === shot.seq_id)
    if (seqIdx < 0) return null
    const before = colWidths.slice(0, seqIdx).reduce((a, b) => a + b, 0)
    const shotList = shotsBySeq.get(shot.seq_id) ?? []
    const shotIdx = shotList.findIndex(s => s.id === shot.id)
    if (shotIdx < 0) return null
    return HEADER_W + 10 + before + shotIdx * (shotW + shotGap)
  }
  const bookmarkExistsFor = (kind: BookmarkKind, id: string) =>
    bookmarks.some(b => b.kind === kind && b.entityId === id)
  const toggleBookmarkOnSelection = () => {
    if (selection.kind === 'seq') {
      persistBookmarks(bookmarkExistsFor('seq', selection.id)
        ? bookmarks.filter(b => !(b.kind === 'seq' && b.entityId === selection.id))
        : [...bookmarks, { kind: 'seq', entityId: selection.id }])
    } else if (selection.kind === 'shot') {
      persistBookmarks(bookmarkExistsFor('shot', selection.id)
        ? bookmarks.filter(b => !(b.kind === 'shot' && b.entityId === selection.id))
        : [...bookmarks, { kind: 'shot', entityId: selection.id }])
    }
  }
  const bookmarkActive =
    (selection.kind === 'seq'  && bookmarkExistsFor('seq',  selection.id)) ||
    (selection.kind === 'shot' && bookmarkExistsFor('shot', selection.id))
  const canBookmark = selection.kind === 'seq' || selection.kind === 'shot'
  // Sorted x-positions (with target ids) for prev/next navigation.
  const bookmarkPositions = bookmarks
    .map(b => ({ b, x: bookmarkX(b) }))
    .filter((p): p is { b: Bookmark; x: number } => p.x !== null)
    .sort((a, b) => a.x - b.x)
  const scrollToBookmark = (x: number) => {
    const el = scrollWrapRef.current
    if (!el) return
    // Bring the bookmark just after the sticky header cell.
    el.scrollTo({ left: Math.max(0, x - HEADER_W - 6), behavior: 'smooth' })
  }
  const gotoBookmark = (dir: -1 | 1) => {
    if (bookmarkPositions.length === 0) return
    const el = scrollWrapRef.current
    const curX = (el?.scrollLeft ?? 0) + HEADER_W + 8   // small tolerance
    let next: { b: Bookmark; x: number } | undefined
    if (dir === 1) {
      next = bookmarkPositions.find(p => p.x > curX) ?? bookmarkPositions[0]
    } else {
      const prev = [...bookmarkPositions].reverse().find(p => p.x < curX - 6)
      next = prev ?? bookmarkPositions[bookmarkPositions.length - 1]
    }
    if (!next) return
    scrollToBookmark(next.x)
    // Also focus the target so MenuEdit / MenuSpec reflect it.
    setSelection({ kind: next.b.kind, id: next.b.entityId })
    onEntityClicked?.()
  }

  const reorderSeq = (draggedId: string, targetId: string) => {
    if (draggedId === targetId) return
    setState(prev => {
      const list = [...prev.sequences].sort((a, b) => a.order - b.order)
      const from = list.findIndex(s => s.id === draggedId)
      const to   = list.findIndex(s => s.id === targetId)
      if (from < 0 || to < 0) return prev
      const [src] = list.splice(from, 1)
      list.splice(to, 0, src)
      const orderMap = new Map(list.map((s, i) => [s.id, i]))
      return { ...prev, sequences: prev.sequences.map(s => ({ ...s, order: orderMap.get(s.id) ?? s.order })) }
    })
  }
  const reorderShot = (draggedId: string, targetId: string) => {
    if (draggedId === targetId) return
    setState(prev => {
      const src = prev.shots.find(s => s.id === draggedId)
      const dst = prev.shots.find(s => s.id === targetId)
      if (!src || !dst || src.seq_id !== dst.seq_id) return prev
      const list = prev.shots.filter(s => s.seq_id === src.seq_id).sort((a, b) => a.order - b.order)
      const from = list.findIndex(s => s.id === draggedId)
      const to   = list.findIndex(s => s.id === targetId)
      const [moved] = list.splice(from, 1)
      list.splice(to, 0, moved)
      const orderMap = new Map(list.map((s, i) => [s.id, i]))
      return { ...prev, shots: prev.shots.map(s => (orderMap.has(s.id) ? { ...s, order: orderMap.get(s.id)! } : s)) }
    })
  }

  return (
    <div style={{ padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 12, minHeight: '100%' }}
         onClick={(e) => { if (e.target === e.currentTarget) setSelection({ kind: 'none' }) }}>
      {/* Toolbar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap' }}>
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          <ArrowDownUp size={11} strokeWidth={1.75} color="var(--ink-3)" style={{ transform: 'rotate(90deg)' }} />
          <span className="cap" style={{ fontSize: 9, letterSpacing: '0.08em', color: 'var(--ink-3)' }}>H</span>
          <button onClick={() => setZoom(pxPerBlock <= 20 ? pxPerBlock - 2 : pxPerBlock - 20)} style={_zoomBtn}><Minus size={11} strokeWidth={2} /></button>
          <input type="range" min={ZOOM_MIN} max={ZOOM_MAX} step={1} value={pxPerBlock}
                 onChange={e => setZoom(Number(e.target.value))} style={{ width: 140, accentColor: 'var(--accent)' }} />
          <button onClick={() => setZoom(pxPerBlock < 20 ? pxPerBlock + 2 : pxPerBlock + 20)} style={_zoomBtn}><Plus size={11} strokeWidth={2} /></button>
          <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink-3)', minWidth: 34 }}>{pxPerBlock}px</span>
        </div>
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          <MoveVertical size={11} strokeWidth={1.75} color="var(--ink-3)" />
          <span className="cap" style={{ fontSize: 9, letterSpacing: '0.08em', color: 'var(--ink-3)' }}>V</span>
          <button onClick={() => setVZ(vZoom - 0.1)} style={_zoomBtn}><Minus size={11} strokeWidth={2} /></button>
          <input type="range" min={VZOOM_MIN} max={VZOOM_MAX} step={0.05} value={vZoom}
                 onChange={e => setVZ(Number(e.target.value))} style={{ width: 140, accentColor: 'var(--accent)' }} />
          <button onClick={() => setVZ(vZoom + 0.1)} style={_zoomBtn}><Plus size={11} strokeWidth={2} /></button>
          <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink-3)', minWidth: 34 }}>{Math.round(vZoom * 100)}%</span>
        </div>

        {/* Bookmarks */}
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          <button
            onClick={() => gotoBookmark(-1)}
            disabled={bookmarkPositions.length === 0}
            title="Bookmark précédent"
            style={{ ..._zoomBtn, opacity: bookmarkPositions.length === 0 ? 0.4 : 1 }}
          ><ChevronLeft size={12} strokeWidth={2} /></button>
          <button
            onClick={() => gotoBookmark(1)}
            disabled={bookmarkPositions.length === 0}
            title="Bookmark suivant"
            style={{ ..._zoomBtn, opacity: bookmarkPositions.length === 0 ? 0.4 : 1 }}
          ><ChevronRight size={12} strokeWidth={2} /></button>
          <button
            onClick={toggleBookmarkOnSelection}
            disabled={!canBookmark}
            title={
              !canBookmark
                ? 'Sélectionne une séquence ou un shot pour poser un bookmark'
                : bookmarkActive ? 'Retirer le bookmark' : 'Poser un bookmark'
            }
            style={{
              ..._zoomBtn,
              width: 26,
              background: bookmarkActive ? 'var(--accent-soft)' : 'var(--paper-2)',
              color: bookmarkActive ? 'var(--accent-hi)' : (canBookmark ? 'var(--ink-2)' : 'var(--ink-4)'),
              opacity: canBookmark ? 1 : 0.55,
              borderColor: bookmarkActive ? 'var(--accent)' : 'var(--rule-2)',
            }}
          >
            <Bookmark size={12} strokeWidth={2}
                      fill={bookmarkActive ? 'var(--accent)' : 'none'} />
          </button>
          <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink-4)', minWidth: 18, textAlign: 'right' }}>
            {bookmarks.length || ''}
          </span>
        </div>
      </div>

      {sequences.length === 0 && (
        <div style={{ padding: '32px 4px', fontSize: 11, color: 'var(--ink-4)' }}>
          {t('prod.emptyTimeline')}
        </div>
      )}

      {sequences.length > 0 && (() => {
        const contentW = colWidths.reduce((a, b) => a + b, 0) + 20 /* padding */
        return (
        <div style={{
          border: '1px solid var(--rule)', borderRadius: 8, overflow: 'hidden',
          background: 'var(--paper)',
          boxShadow: 'var(--shadow-xs)',
        }}>
          {/* Single horizontal scroll container. Header cells stick to the left
              via position:sticky so they stay visible while the lanes scroll. */}
          <div ref={scrollWrapRef} className="timeline-scroll" style={{ overflowX: 'scroll', overflowY: 'hidden', position: 'relative' }}>
            <div style={{ minWidth: HEADER_W + contentW, display: 'flex', flexDirection: 'column', position: 'relative' }}>
              {/* Bookmark overlay — vertical markers spanning ruler + tracks */}
              {bookmarkPositions.map((p, i) => (
                <div key={i} style={{
                  position: 'absolute', top: 0, bottom: 0, left: p.x,
                  width: 0, borderLeft: '2px solid var(--accent)',
                  pointerEvents: 'none', zIndex: 4, opacity: 0.85,
                }}>
                  <div style={{
                    position: 'absolute', top: 2, left: -8,
                    width: 16, height: 14, display: 'flex', alignItems: 'center', justifyContent: 'center',
                    borderRadius: 3, background: 'var(--accent)', color: 'var(--paper)',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.3)',
                  }}>
                    <Bookmark size={8} strokeWidth={2.4} fill="var(--paper)" />
                  </div>
                </div>
              ))}
              {/* Ruler row */}
              <div style={{ display: 'flex', alignItems: 'stretch', height: 26,
                            borderBottom: '1px solid var(--rule)', background: 'var(--paper-2)' }}>
                <div style={{
                  width: HEADER_W, flexShrink: 0,
                  position: 'sticky', left: 0, zIndex: 3,
                  borderRight: '1px solid var(--rule)',
                  background: 'var(--paper-2)',
                  display: 'flex', alignItems: 'center', padding: '0 12px',
                  fontFamily: 'var(--sans)', fontSize: 9, fontWeight: 600,
                  letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--ink-4)',
                }}>Timeline</div>
                <div style={{ display: 'flex', padding: '0 10px' }}>
                  {sequences.map((seq, i) => {
                    const num = parseNum(seq.name, 'SEQ')
                    const label = Number.isNaN(num) ? seq.name : String(num).padStart(3, '0')
                    return (
                      <div key={seq.id} style={{
                        width: colWidths[i] - gap, marginRight: gap,
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        borderLeft: i === 0 ? 'none' : '1px solid var(--rule)',
                        fontFamily: 'var(--sans)', fontSize: 10, fontWeight: 600,
                        color: 'var(--ink-3)', letterSpacing: '0.04em',
                      }}>{label}</div>
                    )
                  })}
                </div>
              </div>

              {/* SEQ row */}
              <TrackRow
                title="Sequence"
                subtitle={`${sequences.length} clip${sequences.length > 1 ? 's' : ''}`}
                color="var(--prod-seq)"
                height={effSeqH}
                colWidths={colWidths}
                gap={gap}
              >
                <div style={{ display: 'flex', padding: '0 10px', gap, alignItems: 'center', height: '100%' }}>
                  {sequences.map((seq, i) => {
                    const shotCount = shotsBySeq.get(seq.id)?.length ?? 0
                    return (
                      <SeqClip
                        key={seq.id}
                        seq={seq}
                        width={colWidths[i] - gap}
                        height={effSeqH - 18}
                        active={selection.kind === 'seq' && selection.id === seq.id}
                        onClick={() => { setSelection({ kind: 'seq', id: seq.id }); onEntityClicked?.() }}
                        onDragStart={e => {
                          e.dataTransfer.effectAllowed = 'move'
                          e.dataTransfer.setData('text/flux-seq-id', seq.id)
                        }}
                        onDrop={e => {
                          const from = e.dataTransfer.getData('text/flux-seq-id')
                          if (from && from !== seq.id) { e.preventDefault(); reorderSeq(from, seq.id) }
                        }}
                        shotCount={shotCount}
                      />
                    )
                  })}
                </div>
              </TrackRow>

              {/* Vertical drag handle between tracks */}
              <div
                onMouseDown={onHandleDown}
                title="Redimensionner les rangées"
                style={{
                  height: 3, cursor: 'ns-resize',
                  background: 'var(--rule)',
                  transition: 'background 0.1s',
                }}
                onMouseEnter={e => (e.currentTarget.style.background = 'var(--accent)')}
                onMouseLeave={e => (e.currentTarget.style.background = 'var(--rule)')}
              />

              {/* SHOT row */}
              <TrackRow
                title="Shot"
                subtitle={`${state.shots.length} clip${state.shots.length > 1 ? 's' : ''}`}
                color="var(--prod-shot)"
                height={effShotH}
                colWidths={colWidths}
                gap={gap}
                noBottomBorder
              >
                <div style={{ display: 'flex', padding: '0 10px', gap, alignItems: 'center', height: '100%' }}>
                  {sequences.map((seq, i) => {
                    const shots = shotsBySeq.get(seq.id) ?? []
                    const cellW = colWidths[i] - gap
                    const seqCol = effectiveSeqColor(seq)
                    return (
                      <div key={seq.id} style={{ width: cellW, display: 'flex', gap: shotGap, alignItems: 'center' }}>
                        {shots.map(shot => (
                          <ShotClip
                            key={shot.id}
                            shot={shot}
                            width={shotW}
                            height={shotSquare}
                            seqColor={seqCol}
                            active={selection.kind === 'shot' && selection.id === shot.id}
                            onClick={() => { setSelection({ kind: 'shot', id: shot.id }); onEntityClicked?.() }}
                            onDragStart={e => {
                              e.dataTransfer.effectAllowed = 'move'
                              e.dataTransfer.setData('text/flux-shot-id', shot.id)
                            }}
                            onDrop={e => {
                              const from = e.dataTransfer.getData('text/flux-shot-id')
                              if (from && from !== shot.id) { e.preventDefault(); reorderShot(from, shot.id) }
                            }}
                          />
                        ))}
                      </div>
                    )
                  })}
                </div>
              </TrackRow>
            </div>
          </div>
        </div>
        )
      })()}
    </div>
  )
}

// ── track row (ApexGantt-style: flat lane + light column dividers) ──────────
function TrackRow({ title, color, subtitle, height, children, colWidths, gap, noBottomBorder }: {
  title:      string
  color:      string
  subtitle?:  string
  height:     number
  children:   React.ReactNode
  colWidths?: number[]
  gap?:       number
  noBottomBorder?: boolean
}) {
  return (
    <div style={{
      display: 'flex', alignItems: 'stretch',
      minHeight: height, height,
      borderBottom: noBottomBorder ? 'none' : '1px solid var(--rule)',
    }}>
      {/* left header — small colored dot + label + subtitle (sticky) */}
      <div style={{
        width: HEADER_W, flexShrink: 0,
        position: 'sticky', left: 0, zIndex: 3,
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '0 12px',
        background: 'var(--paper-2)',
        borderRight: '1px solid var(--rule)',
      }}>
        <span style={{
          width: 8, height: 8, borderRadius: '50%',
          background: color, flexShrink: 0,
          boxShadow: `0 0 0 2px color-mix(in oklch, ${color} 22%, transparent)`,
        }} />
        <div style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          <span style={{
            fontFamily: 'var(--sans)', fontWeight: 600,
            fontSize: 12, color: 'var(--ink)',
          }}>{title}</span>
          {subtitle && (
            <span style={{
              fontFamily: 'var(--sans)', fontWeight: 500,
              fontSize: 9, color: 'var(--ink-4)', marginTop: 1,
            }}>{subtitle}</span>
          )}
        </div>
      </div>
      {/* right lane — flat paper bg with subtle column dividers */}
      <div style={{
        flex: 1, minWidth: 0,
        background: 'var(--paper)',
        position: 'relative',
      }}>
        {/* column dividers (drawn as an absolutely-positioned strip so they don't collide with the flex children) */}
        {colWidths && colWidths.length > 1 && (
          <div style={{
            position: 'absolute', top: 0, bottom: 0, left: 10, pointerEvents: 'none',
            display: 'flex',
          }}>
            {colWidths.slice(0, -1).map((w, i) => (
              <div key={i} style={{
                width: w, marginRight: (gap ?? 6),
                borderRight: '1px dashed var(--rule)',
                opacity: 0.7,
              }} />
            ))}
          </div>
        )}
        {children}
      </div>
    </div>
  )
}

// Effective color for a seq: user override else deterministic default.
const effectiveSeqColor = (seq: ProductionSequence): string =>
  seq.color || defaultSeqColor(seq.id || seq.name)

// ── seq clip ─────────────────────────────────────────────────────────────────
// The timeline is purely visual now: sequences and shots are created/deleted
// from the Edit menu, never by resizing a clip. So a seq clip is just a draggable
// (reorder) colored block — no right-edge grip.
function SeqClip({ seq, width, height, active, onClick, onDragStart, onDrop, shotCount }: {
  seq:         ProductionSequence
  width:       number
  height:      number
  active:      boolean
  onClick:     () => void
  onDragStart: React.DragEventHandler
  onDrop:      React.DragEventHandler
  shotCount:   number
}) {
  const num = parseNum(seq.name, 'SEQ')
  const numStr = Number.isNaN(num) ? seq.name : String(num).padStart(3, '0')
  const seqColor = effectiveSeqColor(seq)

  return (
    <Clip
      width={width} height={height}
      color={seqColor}
      big={numStr}
      small={seq.label || ''}
      active={active}
      onClick={onClick}
      onDragStart={onDragStart}
      onDrop={onDrop}
      acceptType="text/flux-seq-id"
      title={`${seq.name}${seq.label ? ` — ${seq.label}` : ''} · ${shotCount} shot${shotCount > 1 ? 's' : ''}`}
    />
  )
}

function ShotClip({ shot, width, height, active, onClick, onDragStart, onDrop, seqColor }: {
  shot:        Shot
  width:       number
  height:      number
  active:      boolean
  onClick:     () => void
  onDragStart: React.DragEventHandler
  onDrop:      React.DragEventHandler
  seqColor:    string
}) {
  const num = parseNum(shot.name, 'SHOT')
  const numStr = Number.isNaN(num) ? shot.name : String(num).padStart(3, '0')
  // Shots that override (don't inherit tasks or assets from the parent seq)
  // get a distinct fill — accent hue instead of the seq-derived color.
  const override = !shot.inherit_tasks || !shot.inherit_assets
  const base = shotColorFromSeqColor(seqColor)
  return (
    <Clip
      width={width} height={height}
      color={override ? 'var(--accent-hi)' : base}
      big={numStr}
      small={shot.label || ''}
      active={active}
      onClick={onClick}
      onDragStart={onDragStart}
      onDrop={onDrop}
      acceptType="text/flux-shot-id"
      title={
        `${shot.name}${shot.label ? ` — ${shot.label}` : ''}` +
        (override ? '\nOverrides seq' : '')
      }
      badge={override ? 'OVR' : undefined}
    />
  )
}

// ── generic clip (big number, optional label under) ─────────────────────────
function Clip({ width, height, color, big, small, active, onClick, onDragStart, onDrop, acceptType, title, badge }: {
  width:       number
  height:      number
  color:       string
  big:         string
  small:       string
  active:      boolean
  onClick:     () => void
  onDragStart: React.DragEventHandler
  onDrop:      React.DragEventHandler
  acceptType:  string
  title:       string
  badge?:      string
}) {
  const [dragOver, setDragOver] = useState(false)
  const bigFs = Math.max(9, Math.min(30, Math.round(height * 0.34)))
  const smallFs = Math.max(8, Math.min(18, Math.round(height * 0.22)))
  // Text only when it fits: a narrow clip is a plain colored bar (name in the tooltip),
  // never a cut number spilling over its neighbours.
  const pad = width >= 36 ? 8 : width >= 16 ? 2 : 0
  const showBig = width - 2 * pad >= Math.ceil(big.length * bigFs * 0.62)
  const showSmall = showBig && width - 2 * pad >= 3 * smallFs
  return (
    <div
      draggable
      onDragStart={onDragStart}
      onDragOver={e => {
        if (!e.dataTransfer.types.includes(acceptType)) return
        e.preventDefault(); e.dataTransfer.dropEffect = 'move'
        setDragOver(true)
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={e => { setDragOver(false); onDrop(e) }}
      onClick={(e) => { e.stopPropagation(); onClick() }}
      title={title}
      style={{
        // border-box so the given width INCLUDES padding/border — otherwise each
        // clip renders ~16px wider than `width`, and the shot row overflows past
        // the sequence clip (their widths both derive from the same colWidths).
        width, height, minWidth: width, flexShrink: 0, boxSizing: 'border-box',
        display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
        borderRadius: width >= 12 ? 5 : 2,
        background: color,
        color: 'var(--paper)',
        border: `1px solid color-mix(in oklch, ${color} 75%, black 20%)`,
        outline: active
          ? '2px solid var(--accent)'
          : dragOver ? '2px dashed var(--accent-hi)' : 'none',
        outlineOffset: active ? 1 : 0,
        boxShadow: active
          ? `0 0 0 3px color-mix(in oklch, var(--accent) 22%, transparent)`
          : 'none',
        fontFamily: 'var(--sans)',
        cursor: 'pointer', userSelect: 'none',
        overflow: 'hidden', padding: `4px ${pad}px`,
        transition: 'filter 0.12s, box-shadow 0.15s',
        position: 'relative', zIndex: 1,
      }}
      onMouseEnter={e => (e.currentTarget.style.filter = 'brightness(1.08)')}
      onMouseLeave={e => (e.currentTarget.style.filter = 'brightness(1)')}
    >
      {badge && showBig && (
        <span style={{
          position: 'absolute', top: 3, right: 4,
          fontFamily: 'var(--mono)', fontSize: 7, fontWeight: 700,
          padding: '1px 4px', borderRadius: 3,
          background: 'rgba(0,0,0,0.35)', color: 'var(--paper)',
          letterSpacing: '0.06em', pointerEvents: 'none',
        }}>{badge}</span>
      )}
      {showBig && <span style={{
        fontWeight: 600, fontSize: bigFs, lineHeight: 1, letterSpacing: 0, whiteSpace: 'nowrap',
      }}>{big}</span>}
      {small && showSmall && (
        <span style={{
          marginTop: 2, fontSize: smallFs, fontWeight: 500, letterSpacing: 0,
          opacity: 0.92, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          maxWidth: '100%', textAlign: 'center',
        }}>{small}</span>
      )}
    </div>
  )
}

const _zoomBtn: React.CSSProperties = {
  width: 22, height: 22, borderRadius: 4, border: '1px solid var(--rule-2)',
  background: 'var(--paper-2)', color: 'var(--ink-2)', cursor: 'pointer',
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
}
