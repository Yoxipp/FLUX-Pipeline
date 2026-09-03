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

import { useMemo, useRef, useState } from 'react'
import { ArrowDownUp, Minus, MoveVertical, Plus } from 'lucide-react'
import { useI18n } from '../../i18n'
import type {
  ProductionSequence, ProductionShot as Shot, ProductionState,
} from '../../types'
import type { Selection } from './Production'

interface Props {
  state:           ProductionState
  setState:        (patch: (prev: ProductionState) => ProductionState) => void
  selection:       Selection
  setSelection:    (s: Selection) => void
  onEntityClicked?: () => void
}

const ZOOM_MIN = 60
const ZOOM_MAX = 260
const ZOOM_DEF = 120
const LS_ZOOM = 'flux.production.shot.zoom'

const SEQ_ROW_DEF = 84
const SHOT_ROW_DEF = 56
const ROW_MIN = 34
const ROW_MAX = 220
const LS_SEQ_H = 'flux.production.shot.seqRowH'
const LS_SHOT_H = 'flux.production.shot.shotRowH'

const VZOOM_MIN = 0.6
const VZOOM_MAX = 3.0
const VZOOM_DEF = 1.0
const LS_VZOOM = 'flux.production.shot.vzoom'

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

  // Column widths per seq: at least one block wide, growing with shot count.
  const gap = 6
  const shotBlockW = Math.max(38, Math.round(pxPerBlock * 0.62))
  const seqBlockW  = pxPerBlock
  const colWidths = sequences.map(seq => {
    const nShots = shotsBySeq.get(seq.id)?.length ?? 0
    const shotsW = nShots > 0 ? nShots * shotBlockW + Math.max(0, nShots - 1) * 4 : seqBlockW
    return Math.max(seqBlockW, shotsW) + gap
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
          <button onClick={() => setZoom(pxPerBlock - 20)} style={_zoomBtn}><Minus size={11} strokeWidth={2} /></button>
          <input type="range" min={ZOOM_MIN} max={ZOOM_MAX} step={5} value={pxPerBlock}
                 onChange={e => setZoom(Number(e.target.value))} style={{ width: 140, accentColor: 'var(--accent)' }} />
          <button onClick={() => setZoom(pxPerBlock + 20)} style={_zoomBtn}><Plus size={11} strokeWidth={2} /></button>
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
      </div>

      {sequences.length === 0 && (
        <div style={{ padding: '32px 4px', fontSize: 11, color: 'var(--ink-4)' }}>
          {t('prod.emptyTimeline')}
        </div>
      )}

      {sequences.length > 0 && (
        <div style={{
          border: '1px solid var(--rule-2)', borderRadius: 10, overflow: 'hidden',
          background: 'var(--paper)',
        }}>
          {/* SEQ row */}
          <TrackRow
            title="SEQUENCE"
            color="var(--prod-seq)"
            height={effSeqH}
          >
            <ClipRail
              width={colWidths.reduce((a, b) => a + b, 0)}
              gap={gap}
              padding={10}
            >
              {sequences.map((seq, i) => (
                <SeqClip
                  key={seq.id}
                  seq={seq}
                  width={colWidths[i] - gap}
                  height={effSeqH - 20}
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
                />
              ))}
            </ClipRail>
          </TrackRow>

          {/* Drag handle between tracks */}
          <div
            onMouseDown={onHandleDown}
            title="Redimensionner les rangées"
            style={{
              height: 6, cursor: 'ns-resize',
              background: 'linear-gradient(180deg, var(--rule) 0%, var(--rule-2) 100%)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}
          >
            <div style={{ width: 40, height: 2, borderRadius: 1, background: 'var(--ink-4)', opacity: 0.5 }} />
          </div>

          {/* SHOT row */}
          <TrackRow
            title="SHOT"
            color="var(--prod-shot)"
            height={effShotH}
          >
            <ClipRail
              width={colWidths.reduce((a, b) => a + b, 0)}
              gap={gap}
              padding={10}
            >
              {sequences.map((seq, i) => {
                const shots = shotsBySeq.get(seq.id) ?? []
                const cellW = colWidths[i] - gap
                return (
                  <div key={seq.id} style={{ width: cellW, display: 'flex', gap: 4, alignItems: 'center' }}>
                    {shots.map(shot => (
                      <ShotClip
                        key={shot.id}
                        shot={shot}
                        width={shotBlockW}
                        height={effShotH - 16}
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
            </ClipRail>
          </TrackRow>
        </div>
      )}
    </div>
  )
}

// ── track row (colored header + tinted lane) ────────────────────────────────
function TrackRow({ title, color, height, children }: {
  title:    string
  color:    string
  height:   number
  children: React.ReactNode
}) {
  return (
    <div style={{
      display: 'flex', alignItems: 'stretch',
      minHeight: height, height,
    }}>
      {/* left header block */}
      <div style={{
        width: HEADER_W, flexShrink: 0,
        display: 'flex', alignItems: 'center', justifyContent: 'flex-start',
        padding: '0 14px',
        background: color, color: 'var(--paper)',
        borderRight: `1px solid color-mix(in oklch, ${color} 50%, black)`,
        fontFamily: 'var(--sans)', fontWeight: 600,
        fontSize: 12, letterSpacing: '0.08em', textTransform: 'uppercase',
      }}>
        {title}
      </div>
      {/* right lane */}
      <div style={{
        flex: 1, minWidth: 0,
        background: `color-mix(in oklch, ${color} 12%, var(--paper))`,
        overflowX: 'auto', overflowY: 'hidden',
        display: 'flex', alignItems: 'center',
      }}>
        {children}
      </div>
    </div>
  )
}

function ClipRail({ width, gap, padding, children }: {
  width: number; gap: number; padding: number; children: React.ReactNode
}) {
  return (
    <div style={{
      display: 'flex', gap, padding: `0 ${padding}px`, alignItems: 'center',
      minWidth: Math.max(width + padding * 2, 0),
      height: '100%',
    }}>{children}</div>
  )
}

// ── seq clip ────────────────────────────────────────────────────────────────
function SeqClip({ seq, width, height, active, onClick, onDragStart, onDrop }: {
  seq:         ProductionSequence
  width:       number
  height:      number
  active:      boolean
  onClick:     () => void
  onDragStart: React.DragEventHandler
  onDrop:      React.DragEventHandler
}) {
  const num = parseNum(seq.name, 'SEQ')
  const numStr = Number.isNaN(num) ? seq.name : String(num).padStart(3, '0')
  return (
    <Clip
      width={width} height={height}
      color="var(--prod-seq)"
      big={numStr}
      small={seq.label || ''}
      active={active}
      onClick={onClick}
      onDragStart={onDragStart}
      onDrop={onDrop}
      acceptType="text/flux-seq-id"
      title={`${seq.name}${seq.label ? ` — ${seq.label}` : ''}`}
    />
  )
}

function ShotClip({ shot, width, height, active, onClick, onDragStart, onDrop }: {
  shot:        Shot
  width:       number
  height:      number
  active:      boolean
  onClick:     () => void
  onDragStart: React.DragEventHandler
  onDrop:      React.DragEventHandler
}) {
  const num = parseNum(shot.name, 'SHOT')
  const numStr = Number.isNaN(num) ? shot.name : String(num).padStart(3, '0')
  return (
    <Clip
      width={width} height={height}
      color="var(--prod-shot)"
      big={numStr}
      small={shot.label || ''}
      active={active}
      onClick={onClick}
      onDragStart={onDragStart}
      onDrop={onDrop}
      acceptType="text/flux-shot-id"
      title={`${shot.name}${shot.label ? ` — ${shot.label}` : ''}`}
    />
  )
}

// ── generic clip (big number, optional label under) ─────────────────────────
function Clip({ width, height, color, big, small, active, onClick, onDragStart, onDrop, acceptType, title }: {
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
}) {
  const [dragOver, setDragOver] = useState(false)
  const bigFs = Math.max(12, Math.min(30, Math.round(height * 0.34)))
  const smallFs = Math.max(11, Math.min(18, Math.round(height * 0.22)))
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
        width, height, minWidth: 36,
        display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
        borderRadius: 8, background: color, color: 'var(--paper)',
        border: `1px solid ${active ? 'var(--accent)' : color}`,
        outline: active ? '2px solid var(--accent-soft)' : dragOver ? '2px dashed var(--accent-hi)' : 'none',
        boxShadow: '0 3px 8px rgba(0,0,0,0.35), inset 0 1px 0 rgba(255,255,255,0.15)',
        fontFamily: 'var(--sans)',
        cursor: 'pointer', userSelect: 'none',
        overflow: 'hidden', padding: '4px 6px',
        transition: 'transform 0.12s, filter 0.12s',
      }}
      onMouseEnter={e => (e.currentTarget.style.transform = 'scale(1.03)')}
      onMouseLeave={e => (e.currentTarget.style.transform = 'scale(1)')}
    >
      <span style={{
        fontWeight: 600, fontSize: bigFs, lineHeight: 1, letterSpacing: 0,
      }}>{big}</span>
      {small && (
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
