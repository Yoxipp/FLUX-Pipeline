// Calendar.tsx — team calendar of the active project (2026-09-30).
//
// Each artist puts his tasks on it (what, when, optional link to an asset / shot / task)
// and everyone sees them: you commit in front of the team. A task for someone else is a
// proposal: it pings them, they accept, push it later then accept, or decline, and the
// author is pinged back. State colors: dashed = proposed, red = not started, orange = in
// progress, green = done. Month and week views, filter by person, FR / EN.
// Backend: features/calendar/calendar_store.py, routers/team_calendar.py.

import { ExpandPicker } from '../components/shared/ExpandPicker'
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { useSearchParams } from 'react-router-dom'
import { calendarLinksShot } from './Production/shotCalendar'
import { toast } from 'sonner'
import { CalendarDays, Check, ChevronDown, ChevronLeft, ChevronRight, Plus, Trash2, Upload, X, ZoomIn, ZoomOut } from 'lucide-react'
import { api } from '../api/client'
import { useProject } from '../ProjectContext'
import { useI18n } from '../i18n'
import { EMPTY_SLOTS, composeLink, parseLink, taskOptions, useCalendarLinkTokens } from '../hooks/useCalendarLinkTokens'
import type { LinkKind, LinkSlots } from '../hooks/useCalendarLinkTokens'
import type { CalendarItem, CalendarPublish, CalendarStatus } from '../types'

const POLL_MS = 30_000
// Month view = one continuous scroll of weeks (2026-09-30), 6 months back to 12 ahead.
const ROW_H = 180   // tall rectangles: room for more stacked tasks (2026-10-09)
const ZOOM_KEY = 'flux.calendar.zoom'
const ZOOM_MIN = 0.75
const ZOOM_MAX = 3
const ZOOM_STEP = 0.125
const clampZoom = (z: number) => Math.round(Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, z)) * 1000) / 1000
// 1x: no note; then 1, 2, 3... lines; from 2.5x the whole note.
const noteLinesFor = (z: number) => (z >= 2.5 ? Infinity : z <= 1 ? 0 : Math.max(1, Math.round((z - 1) * 4)))
const MONTHS_BACK = 6
const MONTHS_AHEAD = 12
const DAY_MS = 86_400_000
const weeksBetween = (a: Date, b: Date) => Math.round((Date.UTC(b.getFullYear(), b.getMonth(), b.getDate()) - Date.UTC(a.getFullYear(), a.getMonth(), a.getDate())) / (7 * DAY_MS))

// ── text (FR / EN, follows the language chosen in the settings) ──────────────
type Lang = 'fr' | 'en'
const WEEKDAYS: Record<Lang, string[]> = {
  fr: ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam', 'Dim'],
  en: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
}
const MONTHS: Record<Lang, string[]> = {
  fr: ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre'],
  en: ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'],
}
export const STATUS_LABEL: Record<Lang, Record<CalendarStatus, string>> = {
  fr: { proposed: 'Proposée, en attente', accepted: 'Pas commencée', in_progress: 'En cours', done: 'Finie', declined: 'Refusée' },
  en: { proposed: 'Proposed, waiting', accepted: 'Not started', in_progress: 'In progress', done: 'Done', declined: 'Declined' },
}
const ACTION_LABEL: Record<Lang, Record<string, string>> = {
  fr: { create: 'a créé', propose: 'a proposé', accept: 'a accepté', postpone: 'a décalé et accepté', decline: 'a refusé',
        move: 'a déplacé', start: 'a commencé', done: 'a fini', reopen: 'a remis à pas commencée' },
  en: { create: 'created', propose: 'proposed', accept: 'accepted', postpone: 'postponed and accepted', decline: 'declined',
        move: 'moved', start: 'started', done: 'finished', reopen: 'set back to not started' },
}

function useTr() {
  const { lang } = useI18n()
  const l: Lang = lang === 'en' ? 'en' : 'fr'
  return { l, tr: (fr: string, en: string) => (l === 'en' ? en : fr) }
}

// ── state colors (flat, no glow) ─────────────────────────────────────────────
export const STATE_COLOR: Record<CalendarStatus, string> = {
  proposed: 'var(--ink-3)', accepted: 'var(--err)', in_progress: 'var(--warn)', done: 'var(--ok)', declined: 'var(--ink-4)',
}

// ── dates (local, YYYY-MM-DD) ─────────────────────────────────────────────────
const pad = (n: number) => String(n).padStart(2, '0')
const iso = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
const fromIso = (s: string) => { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d) }
const addDays = (d: Date, n: number) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n)
const mondayOf = (d: Date) => addDays(d, -((d.getDay() + 6) % 7))
const todayIso = () => iso(new Date())
const same = (a: string, b: string) => a.trim().toLowerCase() === b.trim().toLowerCase()
const shortDate = (s: string, l: Lang) => { const d = fromIso(s); return `${d.getDate()} ${MONTHS[l][d.getMonth()].slice(0, 4)}.` }
const span = (it: CalendarItem, l: Lang) =>
  it.start === it.end ? shortDate(it.start, l) : `${shortDate(it.start, l)} ${l === 'en' ? 'to' : 'au'} ${shortDate(it.end, l)}`

const isLate = (it: CalendarItem) => (it.status === 'accepted' || it.status === 'in_progress') && it.end < todayIso()

const btn = (primary = false, danger = false): CSSProperties => ({
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 5, padding: '5px 10px', fontSize: 11,
  borderRadius: 6, cursor: 'pointer', fontFamily: 'var(--sans)',
  border: `1px solid ${danger ? 'var(--err)' : primary ? 'var(--rule-3)' : 'var(--rule-2)'}`,
  background: 'var(--paper-2)',
  color: danger ? 'var(--err)' : primary ? 'var(--accent-hi)' : 'var(--accent-hi)',
})
const input: CSSProperties = {
  width: '100%', boxSizing: 'border-box', padding: '5px 8px', fontSize: 11.5, borderRadius: 6,
  border: '1px solid var(--rule-2)', background: 'var(--paper-2)', color: 'var(--ink)', outline: 'none',
  fontFamily: 'var(--sans)',
}
const lbl: CSSProperties = { fontSize: 11, letterSpacing: 0.6, textTransform: 'uppercase', color: 'var(--ink-3)', marginBottom: 4 }

// ── FLUX range picker (replaces the native date inputs) ──────────────────────
// 2026-09-30: press a day and drag to another (30 -> 2), the span turns orange and
// fills Start / End. A click then a second click works too. One calendar under the
// Start / End row, as wide as the panel (never overflows it).
function DateRange({ start, end, onChange, min }: {
  start: string; end: string; onChange: (s: string, e: string) => void; min?: string
}) {
  const { l, tr } = useTr()
  const [open, setOpen] = useState(false)
  const [month, setMonth] = useState(() => fromIso(start || todayIso()))
  const [anchor, setAnchor] = useState<string | null>(null)   // first day pressed
  const [hover, setHover] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => { if (open) { setMonth(fromIso(start || todayIso())); setAnchor(null); setHover(null) } }, [open]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false) }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey) }
  }, [open])

  const commit = (a: string, b: string) => {
    const [s, e] = a <= b ? [a, b] : [b, a]
    onChange(s, e)
    setAnchor(null); setHover(null); setDragging(false); setOpen(false)
  }
  // Shown span: the one being picked, else the current value.
  const [lo, hi] = anchor
    ? [anchor, hover ?? anchor].sort()
    : [start, end]
  const first = mondayOf(new Date(month.getFullYear(), month.getMonth(), 1))
  const cells = Array.from({ length: 42 }, (_, i) => addDays(first, i))
  const today = todayIso()
  const shown = (v: string) => (v ? `${shortDate(v, l)} ${fromIso(v).getFullYear()}` : '—')
  const field = (label: string, value: string) => (
    <div style={{ flex: 1, minWidth: 0 }}>
      <div style={lbl}>{label}</div>
      <button type="button" onClick={() => setOpen(o => !o)}
              style={{ ...input, display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', textAlign: 'left',
                       borderColor: open ? 'var(--rule-3)' : 'var(--rule-2)' }}>
        <CalendarDays size={11} strokeWidth={1.8} color="var(--ink-3)" />
        {shown(value)}
      </button>
    </div>
  )

  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <div style={{ display: 'flex', gap: 6 }}>
        {field(tr('Début', 'Start'), start)}
        {field(tr('Fin', 'End'), end)}
      </div>
      {open && (
        <div
          onMouseUp={() => setDragging(false)}
          style={{
            position: 'absolute', top: 'calc(100% + 4px)', left: 0, right: 0, zIndex: 50, padding: 8,
            background: 'var(--paper)', border: '1px solid var(--rule-2)', borderRadius: 8, boxShadow: 'var(--shadow-md)',
            userSelect: 'none',
          }}>
          <div style={{ display: 'flex', alignItems: 'center', marginBottom: 6 }}>
            <button type="button" style={{ ...btn(), padding: 3 }} onClick={() => setMonth(m => new Date(m.getFullYear(), m.getMonth() - 1, 1))}><ChevronLeft size={12} /></button>
            <div style={{ flex: 1, textAlign: 'center', fontSize: 11, color: 'var(--ink)', textTransform: 'capitalize' }}>
              {MONTHS[l][month.getMonth()]} {month.getFullYear()}
            </div>
            <button type="button" style={{ ...btn(), padding: 3 }} onClick={() => setMonth(m => new Date(m.getFullYear(), m.getMonth() + 1, 1))}><ChevronRight size={12} /></button>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, minmax(0, 1fr))', rowGap: 2 }}>
            {WEEKDAYS[l].map(d => <div key={d} style={{ fontSize: 10, color: 'var(--ink-4)', textAlign: 'center', paddingBottom: 2 }}>{d.slice(0, 2)}</div>)}
            {cells.map(d => {
              const day = iso(d)
              const off = !!min && day < min
              const inSpan = !!lo && day >= lo && day <= hi
              const edge = day === lo || day === hi
              return (
                <div key={day}
                     onMouseDown={e => {
                       if (off) return
                       e.preventDefault()
                       // Second click of a click-click pick: closes the span.
                       if (anchor && !dragging) { commit(anchor, day); return }
                       setAnchor(day); setHover(day); setDragging(true)
                     }}
                     onMouseEnter={() => { if (!off && anchor) setHover(day) }}
                     onMouseUp={() => {
                       if (off || !anchor || !dragging) return
                       if (day !== anchor) commit(anchor, day)
                       else setDragging(false)   // plain click: wait for the second click
                     }}
                     style={{
                       fontSize: 11, padding: '4px 0', textAlign: 'center', cursor: off ? 'default' : 'pointer',
                       background: inSpan ? (edge ? 'color-mix(in oklch, var(--accent) 45%, transparent)' : 'var(--accent-soft)') : 'transparent',
                       borderRadius: edge ? 4 : 0,
                       outline: day === today && !inSpan ? '1px solid var(--rule-2)' : undefined, outlineOffset: -1,
                       color: off ? 'var(--ink-4)' : inSpan ? 'var(--accent-hi)' : d.getMonth() === month.getMonth() ? 'var(--accent-hi)' : 'var(--ink-3)',
                       opacity: off ? 0.5 : 1, fontWeight: edge && inSpan ? 700 : 400,
                     }}>
                  {d.getDate()}
                </div>
              )
            })}
          </div>
          <div style={{ fontSize: 11, color: 'var(--ink-4)', marginTop: 6 }}>
            {anchor
              ? tr('Clique ou relâche sur le dernier jour', 'Click or release on the last day')
              : tr('Clique-glisse du premier au dernier jour', 'Click and drag from the first to the last day')}
          </div>
        </div>
      )}
    </div>
  )
}

// ── FLUX confirm (replaces window.confirm) ───────────────────────────────────
function ConfirmDelete({ title, onCancel, onConfirm }: { title: string; onCancel: () => void; onConfirm: () => void }) {
  const { tr } = useTr()
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onCancel(); if (e.key === 'Enter') onConfirm() }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [onCancel, onConfirm])
  return (
    <div onClick={e => { if (e.target === e.currentTarget) onCancel() }}
         style={{ position: 'fixed', inset: 0, zIndex: 3000, background: 'rgba(0,0,0,0.55)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
      <div style={{ width: 340, maxWidth: '92vw', background: 'var(--paper)', border: '1px solid var(--rule-2)',
                    borderRadius: 12, boxShadow: 'var(--shadow-md)', padding: '18px 18px 14px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, fontSize: 13, fontWeight: 600, color: 'var(--ink)' }}>
          <Trash2 size={15} strokeWidth={1.9} color="var(--err)" />
          {tr('Supprimer la tâche ?', 'Delete the task?')}
        </div>
        <div style={{ fontSize: 11, color: 'var(--ink-3)', marginBottom: 16, lineHeight: 1.5 }}>
          « {title} » {tr("disparaît du calendrier de toute l'équipe.", "is removed from the whole team's calendar.")}
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button style={btn()} onClick={onCancel}>{tr('Annuler', 'Cancel')}</button>
          <button style={btn(false, true)} onClick={onConfirm}><Trash2 size={11} /> {tr('Supprimer', 'Delete')}</button>
        </div>
      </div>
    </div>
  )
}

// ── span mark (2026-10-09) ───────────────────────────────────────────────
// A task is a filled grey bar running edge to edge through its days (2026-10-14, was a
// thin line with tabs): a left edge in the status color, the name inside on the first day and
// again at the start of each week. Double-click unfolds it into a band with owner and note.
function spanHead(it: CalendarItem, today: string) {
  return it.start < today && today <= it.end ? today : it.start
}

const CELL_PAD = 5   // padding of a day cell, crossed by the line so it stays continuous
const NOTE_ROW = 13  // one note line in an unfolded band
const BAND_BASE = 34 // unfolded band: title + owner rows

// Note rows shown in an unfolded band (zoom shows more of the note, capped so a band stays readable).
function bandNoteRows(it: CalendarItem, noteLines: number) {
  return it.note && noteLines > 0 ? Math.min(noteLines, 6) : 0
}

// Height of a span mark in a cell: the same on every day of an unfolded task, so its band
// stays continuous from cell to cell.
// Folded task = a filled bar (2026-10-14): 16 px with the name inside, 6 px in dense mode.
const BAR_H = 16
const BAR_H_DENSE = 6
function spanMarkHeight(it: CalendarItem, _day: string, _today: string, open: boolean, noteLines: number, dense = false) {
  if (open) return 4 + BAND_BASE + bandNoteRows(it, noteLines) * NOTE_ROW
  return dense ? BAR_H_DENSE : BAR_H
}

function SpanTab({ color, side, open, onExpand, label }: { color: string; side: 'left' | 'right'; open: boolean; onExpand: () => void; label: string }) {
  return (
    <button onMouseDown={e => e.stopPropagation()}
            onClick={e => { e.stopPropagation(); onExpand() }}
            title={label}
            style={{ position: 'absolute', top: 3, [side]: side === 'left' ? CELL_PAD : CELL_PAD + 2,
                     width: 16, height: 9, padding: 0, border: 0, borderRadius: '0 0 8px 8px',
                     background: color, color: 'var(--bg-deep)', cursor: 'pointer',
                     display: 'flex', alignItems: 'flex-start', justifyContent: 'center' }}>
      <ChevronDown size={9} strokeWidth={3} style={{ marginTop: -1, transform: open ? 'rotate(180deg)' : undefined }} />
    </button>
  )
}

function SpanMark({ it, day, today, selected, open, noteLines, dense, onClick, onExpand }: {
  it: CalendarItem; day: string; today: string; selected: boolean; open: boolean; noteLines: number; dense: boolean; onClick: () => void; onExpand: () => void
}) {
  const { l, tr } = useTr()
  const proposed = it.status === 'proposed'
  const color = proposed ? 'var(--ink-3)' : STATE_COLOR[it.status]
  const isStart = day === it.start
  const isEnd = day === it.end
  const head = day === spanHead(it, today)
  const title = `${it.title} · ${it.owner} · ${span(it, l)} · ${STATUS_LABEL[l][it.status]}`
  const unfold = open ? tr('Replier la tâche', 'Fold the task') : tr('Déplier la tâche', 'Unfold the task')
  const inset = { left: 0, right: 0 }
  // Unfolded: a lighter band glued under the line, continuous like it; every day of the span
  // writes the task in it (2026-10-10), clear of the tabs. The tabs stay, the arrow turns up.
  const noteRows = bandNoteRows(it, noteLines)
  const height = spanMarkHeight(it, day, today, open, noteLines, dense)
  // The name shows on the first day and again at the start of each week the task runs into.
  const weekStart = new Date(day + 'T00:00:00').getDay() === 1
  const labelled = isStart || weekStart
  if (!open) {
    return (
      <div onMouseDown={e => e.stopPropagation()}
           onClick={e => { e.stopPropagation(); onClick() }}
           onDoubleClick={e => { e.stopPropagation(); onExpand() }}
           title={`${title}
${unfold} (double-clic)`}
           style={{ position: 'relative', flexShrink: 0, cursor: 'pointer', height, boxSizing: 'border-box',
                    marginLeft: isStart ? 0 : -CELL_PAD, marginRight: isEnd ? 0 : -CELL_PAD,
                    background: selected ? 'var(--rule-3)' : 'var(--paper-2)',
                    borderLeft: isStart ? `3px solid ${color}` : weekStart ? `3px dashed ${color}` : undefined,
                    borderRadius: `${isStart ? 3 : 0}px ${isEnd ? 3 : 0}px ${isEnd ? 3 : 0}px ${isStart ? 3 : 0}px`,
                    padding: dense ? 0 : '0 6px', fontSize: 11, lineHeight: `${height}px`, color: 'var(--ink)',
                    whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                    opacity: it.status === 'declined' ? 0.45 : 1 }}>
        {!dense && labelled ? it.title : null}
      </div>
    )
  }
  return (
    <div onMouseDown={e => e.stopPropagation()}
         onClick={e => { e.stopPropagation(); onClick() }}
         title={title}
         style={{ position: 'relative', flexShrink: 0, cursor: 'pointer', height,
                  marginLeft: isStart ? 0 : -CELL_PAD, marginRight: isEnd ? 0 : -CELL_PAD,
                  opacity: it.status === 'declined' ? 0.45 : 1 }}>
      <span style={{ position: 'absolute', top: 2, left: 0, right: 0, height: 2, background: color,
                     borderRadius: `${isStart ? 1 : 0}px ${isEnd ? 1 : 0}px ${isEnd ? 1 : 0}px ${isStart ? 1 : 0}px`,
                     boxShadow: selected ? '0 0 0 1px var(--rule-3)' : undefined }} />
      {open && (
        <span style={{ position: 'absolute', top: 4, ...inset, bottom: 0,
                       background: `color-mix(in oklch, ${color} 20%, transparent)` }} />
      )}
      {open && (
        <span style={{ position: 'absolute', top: 6, left: (isStart ? 0 : CELL_PAD) + (head ? 22 : 4),
                       right: isEnd ? (head ? 4 : CELL_PAD + 20) : CELL_PAD,
                       fontSize: 11, lineHeight: '14px', color: 'var(--ink)', overflow: 'hidden' }}>
          <span style={{ display: 'block', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', fontWeight: 500 }}>{it.title}</span>
          <span style={{ display: 'block', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', color: 'var(--ink-2)' }}>
            {it.owner}{it.link ? ` · ${it.link}` : ''}
          </span>
          {noteRows > 0 && (
            <span style={{ display: '-webkit-box', WebkitBoxOrient: 'vertical', WebkitLineClamp: noteRows, overflow: 'hidden',
                           fontSize: 10.5, lineHeight: `${NOTE_ROW}px`, color: 'var(--ink-3)', whiteSpace: 'pre-wrap' }}>
              {it.note}
            </span>
          )}
        </span>
      )}
      {head && <SpanTab color={color} side="left" open={open} onExpand={onExpand} label={unfold} />}
      {isEnd && !head && <SpanTab color={color} side="right" open={open} onExpand={onExpand} label={unfold} />}
      {head && !open && (
        <span style={{ position: 'absolute', top: 12, left: (isStart ? 0 : CELL_PAD) + 20, right: isEnd ? 0 : CELL_PAD,
                       fontSize: 11, lineHeight: '13px', color: 'var(--ink-2)',
                       whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {it.title}
        </span>
      )}
    </div>
  )
}

// ── chip ─────────────────────────────────────────────────────────────────────
// noteLines (zoom, 2026-10-09): 0 hides the note, Infinity shows all of it.
function Chip({ it, selected, onClick, full, noteLines = 0 }: { it: CalendarItem; selected: boolean; onClick: () => void; full?: boolean; noteLines?: number }) {
  const { l, tr } = useTr()
  const c = STATE_COLOR[it.status]
  const late = isLate(it)
  const proposed = it.status === 'proposed'
  const showNote = noteLines > 0 && !!it.note
  return (
    <div
      onMouseDown={e => e.stopPropagation()}
      onClick={e => { e.stopPropagation(); onClick() }}
      title={`${it.title} · ${it.owner} · ${span(it, l)} · ${STATUS_LABEL[l][it.status]}${late ? tr(' · en retard', ' · late') : ''}`}
      style={{
        display: 'flex', alignItems: full || showNote ? 'flex-start' : 'center', gap: 5, flexShrink: 0,
        fontSize: 11.5, lineHeight: 1.3, padding: full ? '5px 7px' : '2px 5px', borderRadius: 4, cursor: 'pointer',
        background: proposed ? 'transparent' : `color-mix(in oklch, ${c} 18%, transparent)`,
        border: proposed ? '1px dashed var(--ink-3)' : '1px solid transparent',
        borderLeft: proposed ? '1px dashed var(--ink-3)' : `3px solid ${c}`,
        outline: selected ? '1px solid var(--rule-3)' : undefined,
        opacity: it.status === 'declined' ? 0.45 : 1,
        textDecoration: it.status === 'declined' ? 'line-through' : undefined,
        color: 'var(--ink)', minWidth: 0,
      }}
    >
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ overflow: 'hidden', whiteSpace: full ? 'normal' : 'nowrap', textOverflow: 'ellipsis' }}>
          {it.status === 'done' && <Check size={9} strokeWidth={2.4} style={{ marginRight: 3, verticalAlign: -1 }} />}
          {it.title}
        </div>
        {full && <div style={{ fontSize: 11, color: 'var(--ink-2)' }}>{it.owner}{it.link ? ` · ${it.link}` : ''}</div>}
        {showNote && (
          <div style={{
            fontSize: 11, color: 'var(--ink-2)', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', marginTop: 1,
            ...(Number.isFinite(noteLines)
              ? { display: '-webkit-box', WebkitBoxOrient: 'vertical', WebkitLineClamp: noteLines, overflow: 'hidden' }
              : {}),
          }}>{it.note}</div>
        )}
      </div>
    </div>
  )
}

// ── publishes of a day (2026-09-30): one band, unfolded into time / person / file ──
const PUB_COLOR = 'var(--prod-shot)'
const PUB_KEY = 'flux.calendar.publishes'
const DENSE_KEY = 'flux.calendar.dense'

// Unfolded list: an opaque card over the grid (never clipped by the cell), spread over
// 2-3 columns when a day has many publishes (2026-09-30), kept inside the window.
const PUB_ROWS_PER_COL = 8
const PUB_COL_W = 190

function PublishBand({ pubs }: { pubs: CalendarPublish[] }) {
  const { tr } = useTr()
  const [at, setAt] = useState<{ x: number; y: number } | null>(null)
  const bandRef = useRef<HTMLDivElement>(null)
  const cardRef = useRef<HTMLDivElement>(null)
  const cols = Math.min(3, Math.max(1, Math.ceil(pubs.length / PUB_ROWS_PER_COL)))
  const width = cols * PUB_COL_W
  useEffect(() => {
    if (!at) return
    const close = (e: Event) => {
      const t = e.target as Node
      if (cardRef.current?.contains(t) || bandRef.current?.contains(t)) return
      setAt(null)
    }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setAt(null) }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', onKey)
    window.addEventListener('resize', close)
    window.addEventListener('scroll', close, true)   // grid scrolled: the card would drift
    return () => {
      window.removeEventListener('scroll', close, true)
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', onKey)
      window.removeEventListener('resize', close)
    }
  }, [at])
  const toggle = () => {
    if (at) { setAt(null); return }
    const r = bandRef.current?.getBoundingClientRect()
    if (!r) return
    const x = Math.max(8, Math.min(r.right - width, window.innerWidth - width - 8))
    setAt({ x, y: r.bottom + 4 })
  }
  // 2026-10-09: a small round badge in the top-right corner of the day, not a full band.
  const label = `${pubs.length} ${pubs.length > 1 ? tr('publishs', 'publishes') : 'publish'}`
  return (
    <>
      <div ref={bandRef} onMouseDown={e => e.stopPropagation()} onClick={e => { e.stopPropagation(); toggle() }}
           title={label}
           style={{
             position: 'absolute', top: 4, right: 4, zIndex: 2,
             minWidth: 18, height: 18, padding: pubs.length > 1 ? '0 5px 0 4px' : 0, boxSizing: 'border-box',
             borderRadius: 9, cursor: 'pointer', color: 'var(--ink)',
             background: at ? PUB_COLOR : `color-mix(in oklch, ${PUB_COLOR} 45%, var(--paper-2))`,
             border: `1px solid ${PUB_COLOR}`, boxShadow: 'var(--shadow-sm)',
             display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 2,
             fontSize: 10.5, fontWeight: 600, lineHeight: 1,
           }}>
        <Upload size={9} strokeWidth={2.2} />
        {pubs.length > 1 && <span>{pubs.length}</span>}
      </div>
      {at && (
        <div ref={cardRef} onMouseDown={e => e.stopPropagation()} onClick={e => e.stopPropagation()}
             style={{
               position: 'fixed', left: at.x, top: at.y, zIndex: 60, width,
               maxHeight: `calc(100vh - ${at.y + 12}px)`, overflowY: 'auto', cursor: 'default',
               background: 'var(--paper)', border: '1px solid var(--rule-2)', borderRadius: 8,
               boxShadow: 'var(--shadow-md)', padding: 8,
               display: 'grid', gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`,
               gridAutoFlow: 'row', columnGap: 12, rowGap: 6,
             }}>
          {pubs.map(p => (
            <div key={p.id} title={`${p.file}${p.dest_folder ? `\n${p.dest_folder}` : ''}`}
                 style={{ fontSize: 11, color: 'var(--ink-2)', lineHeight: 1.35, minWidth: 0,
                          borderLeft: `2px solid ${PUB_COLOR}`, paddingLeft: 6 }}>
              <span style={{ fontFamily: 'var(--mono)', color: 'var(--ink)' }}>{p.time}</span> · {p.user}
              <div style={{ fontFamily: 'var(--mono)', fontSize: 10.5, color: 'var(--ink-3)', overflowWrap: 'anywhere' }}>{p.file}</div>
            </div>
          ))}
        </div>
      )}
    </>
  )
}

function Legend() {
  const { l } = useTr()
  const row = (key: CalendarStatus) => (
    <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: 'var(--ink-2)' }}>
      <span style={{
        width: 14, height: 9, borderRadius: 2, flexShrink: 0,
        background: key === 'proposed' ? 'transparent' : `color-mix(in oklch, ${STATE_COLOR[key]} 18%, transparent)`,
        border: key === 'proposed' ? '1px dashed var(--ink-3)' : `1px solid ${STATE_COLOR[key]}`,
      }} />
      {STATUS_LABEL[l][key]}
    </div>
  )
  return <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>{(['proposed', 'accepted', 'in_progress', 'done'] as CalendarStatus[]).map(row)}</div>
}

// ── link picker (2026-10-09): the link is built from project tokens, never typed ──
// Output "SEQ SHOT TASK" / "CLASS ASSET TASK", read by calendarLinksShot / entityDeadline.
function LinkPicker({ project, value, onChange }: { project: string; value: string; onChange: (v: string) => void }) {
  const { tr } = useTr()
  const { loaded, production, taskTypes } = useCalendarLinkTokens(project)
  const [slots, setSlots] = useState<LinkSlots>(EMPTY_SLOTS)
  // A link that does not match the project tokens (older free text) is kept as is until replaced.
  const [legacy, setLegacy] = useState('')
  const parsedFor = useRef<string | null>(null)
  useEffect(() => {
    if (!loaded || parsedFor.current === value) return
    if (value === composeLink(production, slots)) { parsedFor.current = value; return }
    const p = parseLink(production, taskTypes, value)
    if (p) { setSlots(p); setLegacy('') } else { setLegacy(value) }
    parsedFor.current = value
  }, [loaded, production, taskTypes, value]) // eslint-disable-line react-hooks/exhaustive-deps
  const set = (patch: Partial<LinkSlots>) => {
    const next = { ...slots, ...patch }
    setSlots(next); setLegacy('')
    const text = composeLink(production, next)
    parsedFor.current = text
    onChange(text)
  }
  const sequences = useMemo(() => [...(production?.sequences ?? [])].sort((a, b) => a.order - b.order || a.name.localeCompare(b.name)), [production])
  const shots = useMemo(() => (production?.shots ?? []).filter(s => s.seq_id === slots.seqId).sort((a, b) => a.order - b.order || a.name.localeCompare(b.name)), [production, slots.seqId])
  const assets = useMemo(() => [...(production?.assets ?? [])].sort((a, b) => a.class.localeCompare(b.class) || a.name.localeCompare(b.name)), [production])
  const tasks = useMemo(() => taskOptions(production, taskTypes, slots), [production, taskTypes, slots])
  const kindBtn = (k: LinkKind, label: string) => (
    <button key={k} type="button" style={{ ...btn(slots.kind === k && !legacy), flex: 1, justifyContent: 'center', padding: '3px 6px' }}
            onClick={() => set({ ...EMPTY_SLOTS, kind: k })}>{label}</button>
  )
  if (!loaded) return <div style={{ fontSize: 11.5, color: 'var(--ink-3)' }}>{tr('Chargement des tokens…', 'Loading tokens…')}</div>
  const preview = legacy || composeLink(production, slots)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
      <div style={{ display: 'flex', gap: 4 }}>
        {kindBtn('none', tr('Aucun', 'None'))}{kindBtn('shot', tr('Plan', 'Shot'))}{kindBtn('asset', 'Asset')}
      </div>
      {slots.kind === 'shot' && (
        <div style={{ display: 'flex', gap: 4 }}>
          <select style={input} value={slots.seqId} onChange={e => set({ seqId: e.target.value, shotId: '' })}>
            <option value="">{tr('Séquence', 'Sequence')}</option>
            {sequences.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
          <select style={input} value={slots.shotId} disabled={!slots.seqId} onChange={e => set({ shotId: e.target.value })}>
            <option value="">{tr('Plan', 'Shot')}</option>
            {shots.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </div>
      )}
      {slots.kind === 'asset' && (
        <select style={input} value={slots.assetId} onChange={e => set({ assetId: e.target.value })}>
          <option value="">{tr('Asset', 'Asset')}</option>
          {assets.map(a => <option key={a.id} value={a.id}>{a.class} {a.name}</option>)}
        </select>
      )}
      {(slots.kind === 'none' || (slots.kind === 'shot' ? !!slots.shotId : !!slots.assetId)) && tasks.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3 }}>
          {tasks.map(t => {
            const on = slots.task === t && !legacy
            return (
              <button key={t} type="button" onClick={() => set({ task: on ? '' : t })}
                      style={{ fontSize: 11, fontFamily: 'var(--mono)', padding: '1px 6px', borderRadius: 10, cursor: 'pointer',
                               border: `1px solid ${on ? 'var(--rule-3)' : 'var(--rule-2)'}`,
                               background: on ? 'color-mix(in oklch, var(--accent) 22%, var(--paper))' : 'var(--paper)',
                               color: on ? 'var(--ink)' : 'var(--ink-2)' }}>{t}</button>
            )
          })}
        </div>
      )}
      {slots.kind === 'shot' && !sequences.length && <div style={{ fontSize: 11, color: 'var(--ink-3)' }}>{tr('Aucune séquence dans la Production.', 'No sequence in Production.')}</div>}
      {slots.kind === 'asset' && !assets.length && <div style={{ fontSize: 11, color: 'var(--ink-3)' }}>{tr('Aucun asset dans la Production.', 'No asset in Production.')}</div>}
      {preview && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11.5, fontFamily: 'var(--mono)', color: 'var(--ink-2)' }}>
          <span style={{ flex: 1, minWidth: 0, overflowWrap: 'anywhere' }}>{preview}</span>
          {legacy && <span style={{ fontFamily: 'inherit', fontSize: 11, color: 'var(--ink-3)' }}>{tr('(lien libre)', '(free link)')}</span>}
          <button type="button" style={{ ...btn(), padding: 2 }} title={tr('Retirer le lien', 'Remove the link')}
                  onClick={() => set({ ...EMPTY_SLOTS })}><X size={10} /></button>
        </div>
      )}
    </div>
  )
}

// ── create form ──────────────────────────────────────────────────────────────
function CreateForm({ project, me, users, range, initialLink = '', onDone, onCancel }: {
  project: string; me: string; users: string[]; range: { start: string; end: string }
  initialLink?: string; onDone: (it: CalendarItem) => void; onCancel: () => void
}) {
  const { tr } = useTr()
  const [title, setTitle] = useState('')
  const [owner, setOwner] = useState(me)
  const [start, setStart] = useState(range.start)
  const [end, setEnd] = useState(range.end)
  const [link, setLink] = useState(initialLink)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { setStart(range.start); setEnd(range.end) }, [range.start, range.end])
  const forOther = !!owner && !same(owner, me)
  const submit = async () => {
    setBusy(true)
    try {
      const r = await api.createCalendarItem(project, { title, owner, start, end: end < start ? start : end, note, link })
      toast.success(forOther ? tr(`Proposée à ${owner} (notifié)`, `Proposed to ${owner} (notified)`) : tr('Tâche ajoutée', 'Task added'))
      onDone(r.item)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'flex', alignItems: 'center' }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--ink)', flex: 1 }}>{tr('Nouvelle tâche', 'New task')}</div>
        <button style={{ ...btn(), padding: 3 }} onClick={onCancel}><X size={12} /></button>
      </div>
      <div><div style={lbl}>{tr('Quoi', 'What')}</div>
        <input autoFocus style={input} value={title} onChange={e => setTitle(e.target.value)} placeholder={tr('Ex. blocking SHOT020', 'E.g. blocking SHOT020')} /></div>
      <div><div style={lbl}>{tr('Pour qui', 'For whom')}</div>
        <select style={input} value={owner} onChange={e => setOwner(e.target.value)}>
          {[me, ...users.filter(u => !same(u, me))].map(u => <option key={u} value={u}>{same(u, me) ? `${u} (${tr('moi', 'me')})` : u}</option>)}
        </select>
        {forOther && <div style={{ fontSize: 11, color: 'var(--ink-3)', marginTop: 4 }}>
          {tr(`${owner} sera notifié et pourra accepter, décaler ou refuser.`, `${owner} is notified and can accept, postpone or decline.`)}</div>}
      </div>
      <DateRange start={start} end={end} onChange={(s, e) => { setStart(s); setEnd(e) }} />
      <div><div style={lbl}>{tr('Lien (optionnel)', 'Link (optional)')}</div>
        <LinkPicker project={project} value={link} onChange={setLink} /></div>
      <div><div style={lbl}>{tr('Note (optionnel)', 'Note (optional)')}</div>
        <textarea style={{ ...input, minHeight: 54, resize: 'vertical' }} value={note} onChange={e => setNote(e.target.value)} /></div>
      <button style={btn(true)} disabled={busy || !title.trim() || !start} onClick={() => { void submit() }}>
        <Plus size={11} /> {forOther ? tr(`Proposer à ${owner}`, `Propose to ${owner}`) : tr('Ajouter la tâche', 'Add the task')}
      </button>
    </div>
  )
}

// ── detail ───────────────────────────────────────────────────────────────────
function Detail({ project, me, it, onChanged, onDeleted, onClose }: {
  project: string; me: string; it: CalendarItem
  onChanged: (it: CalendarItem) => void; onDeleted: (id: string) => void; onClose: () => void
}) {
  const { l, tr } = useTr()
  const isOwner = same(it.owner, me)
  const isAuthor = same(it.created_by, me)
  const canEdit = true   // anyone edits any task (2026-10-14)
  const [start, setStart] = useState(it.start)
  const [end, setEnd] = useState(it.end)
  const [postponing, setPostponing] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  useEffect(() => { setStart(it.start); setEnd(it.end); setPostponing(false) }, [it.id, it.start, it.end])

  const run = async (fn: () => Promise<{ item: CalendarItem }>, ok: string) => {
    setBusy(true)
    try { const r = await fn(); onChanged(r.item); toast.success(ok) }
    catch (e) { toast.error(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }
  const remove = async () => {
    setConfirming(false)
    try { await api.deleteCalendarItem(project, it.id); onDeleted(it.id); toast.success(tr('Tâche supprimée', 'Task deleted')) }
    catch (e) { toast.error(e instanceof Error ? e.message : String(e)) }
  }
  const datesChanged = start !== it.start || end !== it.end
  const progress: CalendarStatus[] = ['accepted', 'in_progress', 'done']

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 6 }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)' }}>{it.title}</div>
          <div style={{ fontSize: 11.5, color: 'var(--ink-2)', marginTop: 2, display: 'flex', alignItems: 'center', gap: 5 }}>
            {it.owner} · {span(it, l)}
          </div>
        </div>
        <button style={{ ...btn(), padding: 3 }} onClick={onClose}><X size={12} /></button>
      </div>
      <div style={{ fontSize: 11.5, color: isLate(it) ? 'var(--err)' : 'var(--ink-2)', display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{ width: 8, height: 8, borderRadius: 2, background: STATE_COLOR[it.status], display: 'inline-block' }} />
        {STATUS_LABEL[l][it.status]}{isLate(it) ? tr(' · en retard', ' · late') : ''}
        {!same(it.created_by, it.owner) && ` · ${tr('proposée par', 'proposed by')} ${it.created_by}`}
      </div>
      {it.link && <div style={{ fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--ink-2)' }}>{it.link}</div>}
      {it.note && <div style={{ fontSize: 11, color: 'var(--ink-2)', whiteSpace: 'pre-wrap' }}>{it.note}</div>}

      {/* Answer a proposal made to me */}
      {isOwner && it.status === 'proposed' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, padding: 8, border: '1px dashed var(--rule-2)', borderRadius: 6 }}>
          <div style={lbl}>{tr(`${it.created_by} te propose cette tâche`, `${it.created_by} proposes this task to you`)}</div>
          {!postponing ? (
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              <button style={btn(true)} disabled={busy} onClick={() => { void run(() => api.respondCalendarItem(project, it.id, 'accept'), tr('Acceptée', 'Accepted')) }}>
                <Check size={11} /> {tr('Accepter', 'Accept')}</button>
              <button style={btn()} disabled={busy} onClick={() => setPostponing(true)}>{tr('Décaler', 'Postpone')}</button>
              <button style={btn(false, true)} disabled={busy} onClick={() => { void run(() => api.respondCalendarItem(project, it.id, 'decline'), tr('Refusée', 'Declined')) }}>{tr('Refuser', 'Decline')}</button>
            </div>
          ) : (
            <>
              <DateRange start={start} end={end} min={it.start} onChange={(s, e) => { setStart(s); setEnd(e) }} />
              <div style={{ display: 'flex', gap: 6 }}>
                <button style={btn(true)} disabled={busy || !datesChanged}
                        onClick={() => { void run(() => api.respondCalendarItem(project, it.id, 'postpone', start, end), tr('Décalée et acceptée', 'Postponed and accepted')) }}>
                  {tr('Décaler et accepter', 'Postpone and accept')}</button>
                <button style={btn()} onClick={() => { setPostponing(false); setStart(it.start); setEnd(it.end) }}>{tr('Annuler', 'Cancel')}</button>
              </div>
            </>
          )}
        </div>
      )}

      {/* Progress: not started (red) / in progress (orange) / done (green) */}
      {progress.includes(it.status) && (
        <div>
          <div style={lbl}>{tr('Avancement', 'Progress')}</div>
          <div style={{ display: 'flex', gap: 4 }}>
            {progress.map(s => (
              <button key={s} disabled={busy || s === it.status}
                      onClick={() => { void run(() => api.updateCalendarItem(project, it.id, { status: s }), STATUS_LABEL[l][s]) }}
                      style={{
                        ...btn(), flex: 1, padding: '5px 4px', fontSize: 11.5,
                        border: `1px solid ${s === it.status ? STATE_COLOR[s] : 'var(--rule-2)'}`,
                        background: s === it.status ? `color-mix(in oklch, ${STATE_COLOR[s]} 18%, transparent)` : 'var(--paper-2)',
                        cursor: s === it.status ? 'default' : 'pointer',
                      }}>
                <span style={{ width: 7, height: 7, borderRadius: 2, background: STATE_COLOR[s], display: 'inline-block' }} />
                {STATUS_LABEL[l][s]}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Owner / author of a pending proposal: move the dates */}
      {canEdit && !(isOwner && it.status === 'proposed') && it.status !== 'declined' && (
        <div>
          <DateRange start={start} end={end} onChange={(s, e) => { setStart(s); setEnd(e) }} />
          {datesChanged && (
            <button style={{ ...btn(true), marginTop: 6 }} disabled={busy}
                    onClick={() => { void run(() => api.updateCalendarItem(project, it.id, { start, end }), tr('Dates mises à jour', 'Dates updated')) }}>
              {tr('Enregistrer les dates', 'Save the dates')}</button>
          )}
        </div>
      )}

      {(isOwner || isAuthor) && (
        <div>
          <button style={btn(false, true)} onClick={() => setConfirming(true)}><Trash2 size={11} /> {tr('Supprimer', 'Delete')}</button>
        </div>
      )}

      {it.history?.length > 0 && (
        <div>
          <div style={lbl}>{tr('Historique', 'History')}</div>
          {[...it.history].reverse().map((h, i) => (
            <div key={i} style={{ fontSize: 11, color: 'var(--ink-3)', lineHeight: 1.6 }}>
              {h.at.slice(0, 10)} · {h.by} {ACTION_LABEL[l][h.action] ?? h.action}
              {h.start ? ` (${h.start === (h.end ?? h.start) ? shortDate(h.start, l) : `${shortDate(h.start, l)} ${l === 'en' ? 'to' : 'au'} ${shortDate(h.end ?? h.start, l)}`})` : ''}
            </div>
          ))}
        </div>
      )}
      {confirming && <ConfirmDelete title={it.title} onCancel={() => setConfirming(false)} onConfirm={() => { void remove() }} />}
    </div>
  )
}

// ── page ─────────────────────────────────────────────────────────────────────
export function Calendar() {
  const { l, tr } = useTr()
  const { project } = useProject()
  const [params, setParams] = useSearchParams()
  const sequence = params.get('seq') ?? ''
  const shot = params.get('shot') ?? ''
  const shotScope = Boolean(sequence && shot && params.get('project') === project)
  const [loadedProject, setLoadedProject] = useState('')
  const focusedLink = useRef('')
  const [items, setItems] = useState<CalendarItem[]>([])
  const [me, setMe] = useState('')
  const [users, setUsers] = useState<string[]>([])
  const [view, setView] = useState<'month' | 'week'>('month')
  const [cursor, setCursor] = useState(() => new Date())
  const [who, setWho] = useState('')                 // '' = everyone
  const [picked, setPicked] = useState<string | null>(null)
  const [creating, setCreating] = useState<{ start: string; end: string } | null>(null)   // span of the new task
  // Multi-day tasks unfolded from their thin line into full chips (month view).
  const [unfolded, setUnfolded] = useState<Set<string>>(() => new Set())
  const toggleUnfolded = (id: string) => setUnfolded(prev => {
    const next = new Set(prev)
    if (next.has(id)) next.delete(id); else next.add(id)
    return next
  })
  // Click-drag over the grid (2026-09-30): the span turns orange, release opens New task.
  const [drag, setDrag] = useState<{ a: string; b: string } | null>(null)
  // Publishes on the calendar: a checkbox (remembered on this machine), one band per day.
  const [showPub, setShowPub] = useState<boolean>(() => { try { return localStorage.getItem(PUB_KEY) === '1' } catch { return false } })
  // Dense mode (2026-10-14): thin bars without names, many more tasks per cell.
  const [dense, setDenseRaw] = useState<boolean>(() => { try { return localStorage.getItem(DENSE_KEY) === '1' } catch { return false } })
  const setDense = (on: boolean) => {
    setDenseRaw(on)
    try { localStorage.setItem(DENSE_KEY, on ? '1' : '0') } catch { /* private mode */ }
  }
  const [pubs, setPubs] = useState<CalendarPublish[]>([])
  const togglePub = (on: boolean) => {
    setShowPub(on)
    try { localStorage.setItem(PUB_KEY, on ? '1' : '0') } catch { /* private mode */ }
  }
  // Zoom (2026-10-09): Ctrl+wheel scales the rows; the more zoom, the more of each note shows.
  const [zoom, setZoomRaw] = useState<number>(() => {
    try { const z = Number(localStorage.getItem(ZOOM_KEY)); return Number.isFinite(z) && z > 0 ? clampZoom(z) : 1 } catch { return 1 }
  })
  const setZoom = (fn: (z: number) => number) => setZoomRaw(prev => {
    const next = clampZoom(fn(prev))
    try { localStorage.setItem(ZOOM_KEY, String(next)) } catch { /* private mode */ }
    return next
  })
  const rowH = Math.round(ROW_H * zoom)
  const noteLines = noteLinesFor(zoom)
  useEffect(() => {
    if (!drag) return
    const up = () => {
      const [start, end] = [drag.a, drag.b].sort()
      setPicked(null); setCreating({ start, end }); setDrag(null)
    }
    window.addEventListener('mouseup', up)
    return () => window.removeEventListener('mouseup', up)
  }, [drag])

  const load = useCallback(() => {
    if (!project) return
    api.getCalendar(project)
      .then(r => { setItems(r.items); setMe(r.me); setLoadedProject(project) })
      .catch(e => toast.error(`${tr('Calendrier indisponible', 'Calendar unavailable')} : ${e instanceof Error ? e.message : String(e)}`))
  }, [project]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    load()
    const t = setInterval(load, POLL_MS)
    window.addEventListener('flux:refresh', load)
    return () => { clearInterval(t); window.removeEventListener('flux:refresh', load) }
  }, [load])
  useEffect(() => { api.listUsers().then(r => setUsers(r.users)).catch(() => setUsers([])) }, [])

  const shown = useMemo(() => items.filter(it => (!who || same(it.owner, who)) && (!shotScope || calendarLinksShot(it.link, sequence, shot))), [items, who, shotScope, sequence, shot])
  useEffect(() => {
    if (!shotScope) { focusedLink.current = ''; return }
    if (loadedProject !== project) return
    const key = `${project}/${sequence}/${shot}`
    if (focusedLink.current === key) return
    focusedLink.current = key
    const linked = items.filter(it => it.status !== 'declined' && calendarLinksShot(it.link, sequence, shot))
      .sort((a, b) => Number(a.status === 'done') - Number(b.status === 'done') || a.end.localeCompare(b.end))
    setWho('')
    if (linked.length) {
      setView('week'); setCursor(fromIso(linked[0].start)); setPicked(linked[0].id); setCreating(null)
    } else {
      setPicked(null); setCreating({ start: todayIso(), end: todayIso() })
    }
  }, [shotScope, project, sequence, shot, items, loadedProject])
  // ?item=<id> (Home "Tes tâches"): open that commitment in the week view, then drop the param.
  const itemParam = params.get('item') ?? ''
  useEffect(() => {
    if (!itemParam || loadedProject !== project) return
    const it = items.find(x => x.id === itemParam)
    if (it) { setWho(''); setView('week'); setCursor(fromIso(it.start)); setCreating(null); setPicked(it.id) }
    setParams(prev => { const next = new URLSearchParams(prev); next.delete('item'); return next }, { replace: true })
  }, [itemParam, items, loadedProject, project]) // eslint-disable-line react-hooks/exhaustive-deps
  const toAnswer = useMemo(() => items.filter(it => it.status === 'proposed' && same(it.owner, me)), [items, me])
  const waiting = useMemo(() => items.filter(it => it.status === 'proposed' && same(it.created_by, me) && !same(it.owner, me)), [items, me])
  const pickedItem = items.find(it => it.id === picked) ?? null

  // Month view: every week from MONTHS_BACK before to MONTHS_AHEAD after this month, scrolled
  // continuously. Week view: the week of the cursor.
  const range = useMemo(() => {
    const now = new Date()
    const start = mondayOf(new Date(now.getFullYear(), now.getMonth() - MONTHS_BACK, 1))
    const lastOfEnd = new Date(now.getFullYear(), now.getMonth() + MONTHS_AHEAD + 1, 0)
    const end = addDays(mondayOf(lastOfEnd), 6)
    return { start, weeks: weeksBetween(start, end) + 1 }
  }, [])
  const days = useMemo(() => {
    if (view === 'month') return Array.from({ length: range.weeks * 7 }, (_, i) => addDays(range.start, i))
    return Array.from({ length: 7 }, (_, i) => addDays(mondayOf(cursor), i))
  }, [cursor, view, range])
  const scrollRef = useRef<HTMLDivElement>(null)
  const [visibleMonth, setVisibleMonth] = useState(() => { const n = new Date(); return new Date(n.getFullYear(), n.getMonth(), 1) })
  const scrollToRow = (row: number, smooth: boolean) => {
    const el = scrollRef.current
    if (!el) return
    el.scrollTo({ top: Math.max(0, Math.min(row, range.weeks - 1)) * rowH, behavior: smooth ? 'smooth' : 'auto' })
  }
  const scrollToMonth = (m: Date, smooth: boolean) => {
    const now = new Date()
    const lo = new Date(now.getFullYear(), now.getMonth() - MONTHS_BACK, 1)
    const hi = new Date(now.getFullYear(), now.getMonth() + MONTHS_AHEAD, 1)
    const target = m < lo ? lo : m > hi ? hi : m
    scrollToRow(weeksBetween(range.start, mondayOf(target)), smooth)
  }
  // Title follows the month shown at the top of the grid.
  const onGridScroll = () => {
    const el = scrollRef.current
    if (!el || view !== 'month') return
    const row = Math.min(range.weeks - 1, Math.floor(el.scrollTop / rowH + 0.5))
    const sunday = addDays(range.start, row * 7 + 6)
    const m = new Date(sunday.getFullYear(), sunday.getMonth(), 1)
    setVisibleMonth(v => (v.getTime() === m.getTime() ? v : m))
  }
  // Ctrl+wheel zoom (same gesture as Production tracking), passive: false to stop the page zoom.
  useEffect(() => {
    const node = scrollRef.current
    if (!node) return
    const wheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return
      e.preventDefault()
      setZoom(z => z + (e.deltaY < 0 ? ZOOM_STEP : -ZOOM_STEP))
    }
    node.addEventListener('wheel', wheel, { passive: false })
    return () => node.removeEventListener('wheel', wheel)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  // Keep the same week at the top of the grid when the rows grow or shrink.
  const prevRowH = useRef(rowH)
  useLayoutEffect(() => {
    const el = scrollRef.current
    const old = prevRowH.current
    prevRowH.current = rowH
    if (!el || old === rowH || view !== 'month') return
    el.scrollTop = el.scrollTop * rowH / old
  }, [rowH, view])
  // Entering the month view lands on the current month.
  useEffect(() => {
    if (view !== 'month') return
    const id = requestAnimationFrame(() => scrollToMonth(visibleMonth, false))
    return () => cancelAnimationFrame(id)
  }, [view]) // eslint-disable-line react-hooks/exhaustive-deps
  const firstDay = iso(days[0])
  const lastDay = iso(days[days.length - 1])
  useEffect(() => {
    if (!showPub || !project) { setPubs([]); return }
    let alive = true
    const fetchPubs = () => api.getCalendarPublishes(project, firstDay, lastDay)
      .then(r => { if (alive) setPubs(r.publishes) })
      .catch(() => { if (alive) setPubs([]) })
    void fetchPubs()
    const t = setInterval(() => { void fetchPubs() }, POLL_MS)
    return () => { alive = false; clearInterval(t) }
  }, [showPub, project, firstDay, lastDay])
  const pubsOn = (day: string) => pubs.filter(p => p.date === day && (!who || same(p.user, who)))

  const itemsOn = (day: string) => shown
    .filter(it => it.start <= day && day <= it.end)
    .sort((a, b) => a.start.localeCompare(b.start) || a.owner.localeCompare(b.owner))

  const move = (dir: number) => {
    if (view === 'month') scrollToMonth(new Date(visibleMonth.getFullYear(), visibleMonth.getMonth() + dir, 1), true)
    else setCursor(c => addDays(c, 7 * dir))
  }
  const goToday = () => {
    if (view === 'month') scrollToRow(weeksBetween(range.start, mondayOf(new Date())), true)
    else setCursor(new Date())
  }
  const title = view === 'month'
    ? `${MONTHS[l][visibleMonth.getMonth()]} ${visibleMonth.getFullYear()}`
    : tr(`Semaine du ${shortDate(iso(days[0]), l)} au ${shortDate(iso(days[6]), l)}`,
         `Week of ${shortDate(iso(days[0]), l)} to ${shortDate(iso(days[6]), l)}`)
  const today = todayIso()

  const upsert = (it: CalendarItem) => setItems(list => list.some(x => x.id === it.id) ? list.map(x => x.id === it.id ? it : x) : [...list, it])

  if (!project) {
    return <div style={{ padding: 24, fontSize: 12, color: 'var(--ink-3)' }}>
      {tr('Aucun projet actif : choisis-en un dans le Folder Manager.', 'No active project: pick one in the Folder Manager.')}</div>
  }

  return (
    <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        {/* header */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 14px', borderBottom: '1px solid var(--rule)', flexWrap: 'wrap' }}>
          {shotScope && <button style={btn(true)} onClick={() => { setParams({}); setPicked(null); setCreating(null) }} title={tr('Afficher tout le calendrier', 'Show the whole calendar')}>{sequence} · {shot}<X size={11} /></button>}
          <button style={{ ...btn(), padding: 4 }} onClick={() => move(-1)}><ChevronLeft size={13} /></button>
          <button style={btn()} onClick={goToday}>{tr("Aujourd'hui", 'Today')}</button>
          <button style={{ ...btn(), padding: 4 }} onClick={() => move(1)}><ChevronRight size={13} /></button>
          <div style={{ fontSize: 12, color: 'var(--ink-2)', minWidth: 150, textTransform: view === 'month' ? 'capitalize' : undefined }}>{title}</div>
          <ExpandPicker value={view} onChange={v => setView(v as typeof view)}
            options={[{ value: 'month', label: tr('Mois', 'Month') }, { value: 'week', label: tr('Semaine', 'Week') }]} />
          <select style={{ ...input, width: 150 }} value={who} onChange={e => setWho(e.target.value)}>
            <option value="">{tr('Tout le monde', 'Everyone')}</option>
            {[...new Set([me, ...users, ...items.map(i => i.owner)].filter(Boolean))].map(u => (
              <option key={u} value={u}>{same(u, me) ? `${u} (${tr('moi', 'me')})` : u}</option>
            ))}
          </select>
          <label style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, color: 'var(--ink-2)', cursor: 'pointer' }}>
            <input type="checkbox" checked={showPub} onChange={e => togglePub(e.target.checked)} style={{ accentColor: 'var(--accent)' }} />
            {tr('Publishs', 'Publishes')}
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, color: 'var(--ink-2)', cursor: 'pointer' }}
                 title={tr('Barres fines sans nom, plus de tâches par case', 'Thin bars without names, more tasks per cell')}>
            <input type="checkbox" checked={dense} onChange={e => setDense(e.target.checked)} style={{ accentColor: 'var(--accent)' }} />
            {tr('Dense', 'Dense')}
          </label>
          <div style={{ display: 'flex', alignItems: 'center', gap: 2 }} title={tr('Zoom (Ctrl + molette)', 'Zoom (Ctrl + wheel)')}>
            <button style={{ ...btn(), padding: 4 }} disabled={zoom <= ZOOM_MIN} onClick={() => setZoom(z => z - ZOOM_STEP)}
                    aria-label={tr('Dézoomer', 'Zoom out')}><ZoomOut size={12} /></button>
            <button style={{ ...btn(), padding: '3px 6px', fontFamily: 'var(--mono)', fontSize: 11, minWidth: 42 }}
                    onClick={() => setZoom(() => 1)} title={tr('Revenir à 100 %', 'Back to 100 %')}>{Math.round(zoom * 100)}%</button>
            <button style={{ ...btn(), padding: 4 }} disabled={zoom >= ZOOM_MAX} onClick={() => setZoom(z => z + ZOOM_STEP)}
                    aria-label={tr('Zoomer', 'Zoom in')}><ZoomIn size={12} /></button>
          </div>
          <button style={{ ...btn(true), marginLeft: 'auto' }} onClick={() => { setPicked(null); setCreating({ start: today, end: today }) }}>
            <Plus size={11} /> {tr('Ajouter une tâche', 'Add a task')}</button>
        </div>

        {/* grid */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, minmax(0, 1fr))', borderBottom: '1px solid var(--rule)' }}>
          {WEEKDAYS[l].map(d => <div key={d} style={{ ...lbl, padding: '6px 8px', marginBottom: 0 }}>{d}</div>)}
        </div>
        <div ref={scrollRef} onScroll={onGridScroll} style={{
          flex: 1, minHeight: 0, overflowY: 'auto', display: 'grid', gridTemplateColumns: 'repeat(7, minmax(0, 1fr))',
          gridAutoRows: view === 'month' ? `${rowH}px` : 'minmax(100%, auto)', alignContent: 'start',
        }}>
          {days.map((d, i) => {
            const day = iso(d)
            const list = itemsOn(day)
            const weekend = d.getDay() === 0 || d.getDay() === 6
            const past = day < today
            // 2026-09-30: weekends and past days dark, days to come light.
            const dark = weekend || past
            const selSpan = drag ? [drag.a, drag.b].sort() : creating ? [creating.start, creating.end] : null
            const inSpan = !!selSpan && day >= selSpan[0] && day <= selSpan[1]
            const cellBg = inSpan ? 'color-mix(in oklch, var(--accent) 22%, var(--paper))'
              : dark ? 'var(--bg-deep)'
              : 'color-mix(in oklch, var(--ink) 7%, var(--paper-2))'
            // Month view: as many marks as the cell height holds, keeping room for the "+N" line
            // so it is never pushed out of the cell (2026-10-09). Unfolded tasks get the
            // room first: opening a second task hides folded ones, never the open one.
            let visible = list
            // Month view: a task keeps the same lane on every day of the week, sized to its
            // tallest day there (the head day carries the label), so its line stays straight.
            const lanes = new Map<string, { top: number; h: number }>()
            if (view === 'month') {
              const GAP = 3, MORE_H = 14
              const room = rowH - 2 * CELL_PAD - 17   // cell padding + day number
              const weekStart = i - (i % 7)
              const weekDays = days.slice(weekStart, weekStart + 7).map(iso)
              const placed: { it: CalendarItem; top: number; h: number; a: string; b: string }[] = []
              const weekItems = shown.filter(it => it.start <= weekDays[6] && weekDays[0] <= it.end)
                .sort((a, b) => a.start.localeCompare(b.start) || a.owner.localeCompare(b.owner))
              for (const it of weekItems) {
                const a = it.start > weekDays[0] ? it.start : weekDays[0]
                const b = it.end < weekDays[6] ? it.end : weekDays[6]
                const h = Math.max(...weekDays.filter(x => a <= x && x <= b)
                  .map(x => spanMarkHeight(it, x, today, unfolded.has(it.id), noteLines, dense)))
                const top = placed.filter(p => p.a <= b && a <= p.b).reduce((m, p) => Math.max(m, p.top + p.h + GAP), 0)
                placed.push({ it, top, h, a, b })
                lanes.set(it.id, { top, h })
              }
              const bottom = (it: CalendarItem) => { const ln = lanes.get(it.id)!; return ln.top + ln.h }
              if (list.some(it => bottom(it) > room)) {
                visible = list.filter(it => bottom(it) + MORE_H <= room || unfolded.has(it.id))
              }
              visible = [...visible].sort((x, y) => lanes.get(x.id)!.top - lanes.get(y.id)!.top)
            }
            const hidden = list.length - visible.length
            let laneY = 0
            const dayPubs = showPub ? pubsOn(day) : []
            return (
              <div key={day}
                   onMouseDown={e => { if (e.button === 0) { e.preventDefault(); setDrag({ a: day, b: day }) } }}
                   onMouseEnter={() => { if (drag) setDrag(g => (g ? { ...g, b: day } : g)) }}
                   title={tr('Clic ou clic-glisser sur plusieurs jours pour ajouter une tâche', 'Click, or click and drag over several days, to add a task')}
                   style={{
                     userSelect: 'none',
                     
                     // Light cells sit almost on --rule, so their grid lines go dark grey (2026-10-09).
                     borderRight: `1px solid ${dark ? 'var(--rule)' : 'var(--bg-deep)'}`,
                     borderBottom: `1px solid ${dark ? 'var(--rule)' : 'var(--bg-deep)'}`, padding: 5,
                     display: 'flex', flexDirection: 'column', gap: 3, minWidth: 0, cursor: 'copy',
                     background: cellBg, overflow: 'hidden', position: 'relative',
                   }}>
                <div style={{ fontSize: 11.5, fontWeight: day === today ? 700 : 500, paddingRight: dayPubs.length ? 30 : 0,
                              whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', flexShrink: 0,
                              color: day === today || inSpan ? 'var(--accent-hi)' : dark ? 'var(--ink-2)' : 'var(--accent-hi)' }}>
                  <span style={day === today ? { background: 'var(--accent)', color: 'var(--bg-deep)', borderRadius: 4, padding: '0 5px' } : undefined}>
                    {view === 'week' ? shortDate(day, l) : d.getDate()}
                  </span>
                  {/* The 1st of each month carries its name: you see where a month starts while scrolling. */}
                  {view === 'month' && d.getDate() === 1 && (
                    <span style={{ marginLeft: 5, color: 'var(--accent-hi)', fontWeight: 700, textTransform: 'capitalize' }}>
                      {MONTHS[l][d.getMonth()]}{d.getMonth() === 0 ? ` ${d.getFullYear()}` : ''}
                    </span>
                  )}
                </div>
                {dayPubs.length > 0 && <PublishBand pubs={dayPubs} />}
                {visible.map(it => {
                  const pick = () => { setCreating(null); setPicked(it.id) }
                  // Month view: every task starts folded on its line (one day or several);
                  // its tab unfolds it into a band under the line, the tab does not move.
                  if (view === 'month') {
                    const ln = lanes.get(it.id)!
                    const marginTop = ln.top - laneY
                    laneY = ln.top + ln.h   // the cell flex gap adds the 3 px GAP
                    return <div key={it.id} style={{ marginTop, height: ln.h, flexShrink: 0 }}>
                      <SpanMark it={it} day={day} today={today} selected={it.id === picked}
                                open={unfolded.has(it.id)} noteLines={noteLines} dense={dense}
                                onClick={pick} onExpand={() => toggleUnfolded(it.id)} />
                    </div>
                  }
                  return <Chip key={it.id} it={it} full noteLines={noteLines} selected={it.id === picked} onClick={pick} />
                })}
                {hidden > 0 && (
                  // Opens the week of this day, where every task shows in full.
                  <button onMouseDown={e => e.stopPropagation()}
                          onClick={e => { e.stopPropagation(); setView('week'); setCursor(d) }}
                          title={tr('Voir toute la semaine de ce jour', 'Show the whole week of this day')}
                          style={{ alignSelf: 'flex-start', maxWidth: '100%', padding: '0 4px', border: 0, borderRadius: 3,
                                   background: 'transparent', cursor: 'pointer',
                                   fontSize: 11, lineHeight: '14px', height: 14, flexShrink: 0, color: 'var(--ink-2)',
                                   whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    +{hidden} {tr('(vue semaine)', '(week view)')}
                  </button>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* side panel */}
      <div style={{ width: 300, flexShrink: 0, borderLeft: '1px solid var(--rule)', background: 'var(--paper-2)', overflowY: 'auto', padding: 12, display: 'flex', flexDirection: 'column', gap: 14 }}>
        {creating && (
          <CreateForm key={`${project}:${shotScope ? sequence + shot : ''}`} project={project} me={me} users={users} range={creating} initialLink={shotScope ? `${sequence} ${shot}` : ''}
                      onCancel={() => setCreating(null)}
                      onDone={it => { upsert(it); setCreating(null); setPicked(it.id) }} />
        )}
        {!creating && pickedItem && (
          <Detail project={project} me={me} it={pickedItem} onChanged={upsert}
                  onDeleted={id => { setItems(list => list.filter(x => x.id !== id)); setPicked(null) }}
                  onClose={() => setPicked(null)} />
        )}
        <div>
          <div style={lbl}>{tr('À valider', 'To answer')} ({toAnswer.length})</div>
          {toAnswer.length === 0
            ? <div style={{ fontSize: 11.5, color: 'var(--ink-4)' }}>{tr('Aucune proposition pour toi.', 'No proposal for you.')}</div>
            : toAnswer.map(it => (
              <div key={it.id} style={{ marginBottom: 4 }}>
                <Chip it={it} full selected={it.id === picked} onClick={() => { setCreating(null); setPicked(it.id) }} />
                <div style={{ fontSize: 11, color: 'var(--ink-3)', margin: '2px 0 0 4px' }}>{span(it, l)} · {tr('de', 'from')} {it.created_by}</div>
              </div>
            ))}
        </div>
        {waiting.length > 0 && (
          <div>
            <div style={lbl}>{tr('En attente de réponse', 'Waiting for an answer')} ({waiting.length})</div>
            {waiting.map(it => (
              <div key={it.id} style={{ marginBottom: 4 }}>
                <Chip it={it} full selected={it.id === picked} onClick={() => { setCreating(null); setPicked(it.id) }} />
              </div>
            ))}
          </div>
        )}
        <div>
          <div style={lbl}>{tr('Légende', 'Legend')}</div>
          <Legend />
        </div>
      </div>
    </div>
  )
}
