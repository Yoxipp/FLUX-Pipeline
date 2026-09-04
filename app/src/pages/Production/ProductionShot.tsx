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
import { defaultSeqColor, shotColorFromSeqColor } from './util'

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
const SHOT_ROW_DEF = 40
const ROW_MIN = 30
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

  // Column widths per seq: at least one seq-block wide, growing with shot count.
  // Shots are small fixed-size squares — they don't stretch with the horizontal
  // zoom (which controls seq width instead).
  const gap = 6
  const shotSquare = Math.max(24, Math.min(42, Math.round(effShotH * 0.62)))
  const shotBlockW = shotSquare
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
  // Resize a seq clip by dragging its right edge → add / remove shots.
  // Auto-created shots follow the SHOT010, SHOT020, … convention; removed
  // shots are the trailing (highest-numbered) ones.
  const resizeSeqShots = (seqId: string, targetShotCount: number) => {
    setState(prev => {
      const current = prev.shots.filter(s => s.seq_id === seqId).sort((a, b) => a.order - b.order)
      const clamped = Math.max(0, targetShotCount)
      if (clamped === current.length) return prev
      if (clamped > current.length) {
        const toAdd = clamped - current.length
        // Next SHOT number: (max existing / 10 + 1) * 10 → 010, 020, 030…
        const nums = current
          .map(s => Number((s.name.match(/SHOT(\d+)/i) || [])[1] ?? NaN))
          .filter(n => !Number.isNaN(n))
        let nextNum = nums.length ? Math.max(...nums) + 1 : 1
        const newShots: Shot[] = []
        for (let i = 0; i < toAdd; i++) {
          newShots.push({
            id: `shot_${Math.random().toString(36).slice(2, 12)}`,
            seq_id: seqId,
            name: `SHOT${String(nextNum).padStart(3, '0')}`,
            order: current.length + i,
            inherit_tasks: true, inherit_assets: true,
            tasks: [], assets: [], task_details: {}, origin: 'user',
          })
          nextNum += 1
        }
        return { ...prev, shots: [...prev.shots, ...newShots] }
      }
      // shrink: drop the last N
      const toRemove = current.slice(clamped).map(s => s.id)
      const removeSet = new Set(toRemove)
      return { ...prev, shots: prev.shots.filter(s => !removeSet.has(s.id)) }
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
          <div style={{ overflowX: 'auto', overflowY: 'hidden' }}>
            <div style={{ minWidth: HEADER_W + contentW, display: 'flex', flexDirection: 'column' }}>
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
                        shotBlockW={shotBlockW}
                        onResize={(nextShotCount) => resizeSeqShots(seq.id, nextShotCount)}
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
                      <div key={seq.id} style={{ width: cellW, display: 'flex', gap: 4, alignItems: 'center' }}>
                        {shots.map(shot => (
                          <ShotClip
                            key={shot.id}
                            shot={shot}
                            width={shotSquare}
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

// ── seq clip (with right-edge resize grip) ──────────────────────────────────
function SeqClip({ seq, width, height, active, onClick, onDragStart, onDrop, shotCount, shotBlockW, onResize }: {
  seq:         ProductionSequence
  width:       number
  height:      number
  active:      boolean
  onClick:     () => void
  onDragStart: React.DragEventHandler
  onDrop:      React.DragEventHandler
  shotCount:   number
  shotBlockW:  number
  onResize:    (nextShotCount: number) => void
}) {
  const num = parseNum(seq.name, 'SEQ')
  const numStr = Number.isNaN(num) ? seq.name : String(num).padStart(3, '0')
  const seqColor = effectiveSeqColor(seq)
  const [dragCount, setDragCount] = useState<number | null>(null)
  const previewCount = dragCount ?? shotCount

  const onGripDown = (e: React.MouseEvent) => {
    e.stopPropagation(); e.preventDefault()
    const startX = e.clientX
    const startCount = shotCount
    const onMove = (ev: MouseEvent) => {
      const delta = ev.clientX - startX
      const next = Math.max(0, startCount + Math.round(delta / (shotBlockW + 4)))
      setDragCount(next)
    }
    const onUp = () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
      setDragCount(prev => {
        if (prev !== null && prev !== shotCount) onResize(prev)
        return null
      })
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }

  return (
    <div style={{ position: 'relative', display: 'inline-block' }}>
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
      {/* Right-edge resize grip */}
      <div
        onMouseDown={onGripDown}
        title={`Étirer : ${previewCount} shot${previewCount > 1 ? 's' : ''}`}
        style={{
          position: 'absolute', top: 6, bottom: 6, right: -3, width: 6,
          cursor: 'ew-resize', borderRadius: 3,
          background: dragCount !== null ? 'var(--accent)' : 'transparent',
          zIndex: 2,
        }}
        onMouseEnter={e => { if (dragCount === null) e.currentTarget.style.background = 'color-mix(in oklch, var(--accent) 50%, transparent)' }}
        onMouseLeave={e => { if (dragCount === null) e.currentTarget.style.background = 'transparent' }}
      />
      {/* Preview tooltip while dragging */}
      {dragCount !== null && dragCount !== shotCount && (
        <div style={{
          position: 'absolute', top: -22, right: -4,
          padding: '2px 6px', borderRadius: 4,
          background: 'var(--accent)', color: 'var(--paper)',
          fontFamily: 'var(--mono)', fontSize: 9, fontWeight: 700, letterSpacing: '0.04em',
          whiteSpace: 'nowrap', pointerEvents: 'none', zIndex: 4,
        }}>
          {dragCount > shotCount ? '+' : ''}{dragCount - shotCount} · {dragCount} SHOT{dragCount > 1 ? 'S' : ''}
        </div>
      )}
    </div>
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
        width, height, minWidth: Math.min(width, 24),
        display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
        borderRadius: 5,
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
        overflow: 'hidden', padding: '4px 8px',
        transition: 'filter 0.12s, box-shadow 0.15s',
        position: 'relative', zIndex: 1,
      }}
      onMouseEnter={e => (e.currentTarget.style.filter = 'brightness(1.08)')}
      onMouseLeave={e => (e.currentTarget.style.filter = 'brightness(1)')}
    >
      {badge && (
        <span style={{
          position: 'absolute', top: 3, right: 4,
          fontFamily: 'var(--mono)', fontSize: 7, fontWeight: 700,
          padding: '1px 4px', borderRadius: 3,
          background: 'rgba(0,0,0,0.35)', color: 'var(--paper)',
          letterSpacing: '0.06em', pointerEvents: 'none',
        }}>{badge}</span>
      )}
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
