// Calendar.tsx — team calendar of the active project (2026-09-30).
//
// Each artist puts his tasks on it (what, when, optional link to an asset / shot / task)
// and everyone sees them: you commit in front of the team. A task for someone else is a
// proposal: it pings them, they accept, push it later then accept, or decline, and the
// author is pinged back. State colors: dashed = proposed, red = not started, orange = in
// progress, green = done. Month and week views, filter by person, FR / EN.
// Backend: features/calendar/calendar_store.py, routers/team_calendar.py.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { toast } from 'sonner'
import { CalendarDays, Check, ChevronDown, ChevronLeft, ChevronRight, Plus, Trash2, Upload, X } from 'lucide-react'
import { api } from '../api/client'
import { useProject } from '../ProjectContext'
import { useI18n } from '../i18n'
import type { CalendarItem, CalendarPublish, CalendarStatus } from '../types'

const POLL_MS = 30_000
const MONTH_CHIPS = 4
// Month view = one continuous scroll of weeks (2026-09-30), 6 months back to 12 ahead.
const ROW_H = 128
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
const STATUS_LABEL: Record<Lang, Record<CalendarStatus, string>> = {
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
const STATE_COLOR: Record<CalendarStatus, string> = {
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
  border: `1px solid ${danger ? 'var(--err)' : primary ? 'var(--accent)' : 'var(--rule-2)'}`,
  background: primary ? 'var(--accent-soft)' : 'var(--paper-2)',
  color: danger ? 'var(--err)' : primary ? 'var(--accent-hi)' : 'var(--ink)',
})
const input: CSSProperties = {
  width: '100%', boxSizing: 'border-box', padding: '5px 8px', fontSize: 11.5, borderRadius: 6,
  border: '1px solid var(--rule-2)', background: 'var(--paper-2)', color: 'var(--ink)', outline: 'none',
  fontFamily: 'var(--sans)',
}
const lbl: CSSProperties = { fontSize: 9.5, letterSpacing: 0.6, textTransform: 'uppercase', color: 'var(--ink-3)', marginBottom: 4 }

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
                       borderColor: open ? 'var(--accent)' : 'var(--rule-2)' }}>
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
            {WEEKDAYS[l].map(d => <div key={d} style={{ fontSize: 8.5, color: 'var(--ink-4)', textAlign: 'center', paddingBottom: 2 }}>{d.slice(0, 2)}</div>)}
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
                       fontSize: 10, padding: '4px 0', textAlign: 'center', cursor: off ? 'default' : 'pointer',
                       background: inSpan ? (edge ? 'color-mix(in oklch, var(--accent) 45%, transparent)' : 'var(--accent-soft)') : 'transparent',
                       borderRadius: edge ? 4 : 0,
                       outline: day === today && !inSpan ? '1px solid var(--rule-2)' : undefined, outlineOffset: -1,
                       color: off ? 'var(--ink-4)' : inSpan ? 'var(--accent-hi)' : d.getMonth() === month.getMonth() ? 'var(--ink)' : 'var(--ink-3)',
                       opacity: off ? 0.5 : 1, fontWeight: edge && inSpan ? 700 : 400,
                     }}>
                  {d.getDate()}
                </div>
              )
            })}
          </div>
          <div style={{ fontSize: 9.5, color: 'var(--ink-4)', marginTop: 6 }}>
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

// ── chip ─────────────────────────────────────────────────────────────────────
function Chip({ it, selected, onClick, full }: { it: CalendarItem; selected: boolean; onClick: () => void; full?: boolean }) {
  const { l, tr } = useTr()
  const c = STATE_COLOR[it.status]
  const late = isLate(it)
  const proposed = it.status === 'proposed'
  return (
    <div
      onMouseDown={e => e.stopPropagation()}
      onClick={e => { e.stopPropagation(); onClick() }}
      title={`${it.title} · ${it.owner} · ${span(it, l)} · ${STATUS_LABEL[l][it.status]}${late ? tr(' · en retard', ' · late') : ''}`}
      style={{
        display: 'flex', alignItems: full ? 'flex-start' : 'center', gap: 5,
        fontSize: 10.5, lineHeight: 1.3, padding: full ? '5px 7px' : '2px 5px', borderRadius: 4, cursor: 'pointer',
        background: proposed ? 'transparent' : `color-mix(in oklch, ${c} 18%, transparent)`,
        border: proposed ? '1px dashed var(--ink-3)' : '1px solid transparent',
        borderLeft: proposed ? '1px dashed var(--ink-3)' : `3px solid ${c}`,
        outline: selected ? '1px solid var(--accent)' : undefined,
        opacity: it.status === 'declined' ? 0.45 : 1,
        textDecoration: it.status === 'declined' ? 'line-through' : undefined,
        color: 'var(--ink)', minWidth: 0,
      }}
    >
      <div style={{ minWidth: 0, overflow: 'hidden', whiteSpace: full ? 'normal' : 'nowrap', textOverflow: 'ellipsis' }}>
        {it.status === 'done' && <Check size={9} strokeWidth={2.4} style={{ marginRight: 3, verticalAlign: -1 }} />}
        {it.title}
        {full && <div style={{ fontSize: 9.5, color: 'var(--ink-2)' }}>{it.owner}{it.link ? ` · ${it.link}` : ''}</div>}
      </div>
    </div>
  )
}

// ── publishes of a day (2026-09-30): one band, unfolded into time / person / file ──
const PUB_COLOR = 'var(--prod-shot)'
const PUB_KEY = 'flux.calendar.publishes'

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
    const x = Math.max(8, Math.min(r.left, window.innerWidth - width - 8))
    setAt({ x, y: r.bottom + 4 })
  }
  return (
    <>
      <div ref={bandRef} onMouseDown={e => e.stopPropagation()} onClick={e => { e.stopPropagation(); toggle() }}
           style={{
             fontSize: 10, borderRadius: 4, cursor: 'pointer', color: 'var(--ink)',
             background: `color-mix(in oklch, ${PUB_COLOR} 30%, var(--paper-2))`, borderLeft: `3px solid ${PUB_COLOR}`,
             padding: '2px 5px', minWidth: 0, display: 'flex', alignItems: 'center', gap: 4,
           }}>
        <Upload size={9} strokeWidth={2} color="var(--ink)" />
        <span style={{ flex: 1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {pubs.length} {pubs.length > 1 ? tr('publishs', 'publishes') : 'publish'}
        </span>
        <ChevronDown size={9} style={{ transform: at ? 'rotate(180deg)' : undefined, flexShrink: 0 }} />
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
                 style={{ fontSize: 10, color: 'var(--ink-2)', lineHeight: 1.35, minWidth: 0,
                          borderLeft: `2px solid ${PUB_COLOR}`, paddingLeft: 6 }}>
              <span style={{ fontFamily: 'var(--mono)', color: 'var(--ink)' }}>{p.time}</span> · {p.user}
              <div style={{ fontFamily: 'var(--mono)', fontSize: 9, color: 'var(--ink-3)', overflowWrap: 'anywhere' }}>{p.file}</div>
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
    <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 10, color: 'var(--ink-2)' }}>
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

// ── create form ──────────────────────────────────────────────────────────────
function CreateForm({ project, me, users, range, onDone, onCancel }: {
  project: string; me: string; users: string[]; range: { start: string; end: string }
  onDone: (it: CalendarItem) => void; onCancel: () => void
}) {
  const { tr } = useTr()
  const [title, setTitle] = useState('')
  const [owner, setOwner] = useState(me)
  const [start, setStart] = useState(range.start)
  const [end, setEnd] = useState(range.end)
  const [link, setLink] = useState('')
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
        {forOther && <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 4 }}>
          {tr(`${owner} sera notifié et pourra accepter, décaler ou refuser.`, `${owner} is notified and can accept, postpone or decline.`)}</div>}
      </div>
      <DateRange start={start} end={end} onChange={(s, e) => { setStart(s); setEnd(e) }} />
      <div><div style={lbl}>{tr('Lien (optionnel)', 'Link (optional)')}</div>
        <input style={input} value={link} onChange={e => setLink(e.target.value)} placeholder="SEQ010 SHOT020 ANIM, CHAR_HORSE RIG…" /></div>
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
  const canEdit = isOwner || (isAuthor && it.status === 'proposed')
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
          <div style={{ fontSize: 10.5, color: 'var(--ink-2)', marginTop: 2, display: 'flex', alignItems: 'center', gap: 5 }}>
            {it.owner} · {span(it, l)}
          </div>
        </div>
        <button style={{ ...btn(), padding: 3 }} onClick={onClose}><X size={12} /></button>
      </div>
      <div style={{ fontSize: 10.5, color: isLate(it) ? 'var(--err)' : 'var(--ink-2)', display: 'flex', alignItems: 'center', gap: 6 }}>
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
      {isOwner && progress.includes(it.status) && (
        <div>
          <div style={lbl}>{tr('Avancement', 'Progress')}</div>
          <div style={{ display: 'flex', gap: 4 }}>
            {progress.map(s => (
              <button key={s} disabled={busy || s === it.status}
                      onClick={() => { void run(() => api.updateCalendarItem(project, it.id, { status: s }), STATUS_LABEL[l][s]) }}
                      style={{
                        ...btn(), flex: 1, padding: '5px 4px', fontSize: 10.5,
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
            <div key={i} style={{ fontSize: 10, color: 'var(--ink-3)', lineHeight: 1.6 }}>
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
  const [items, setItems] = useState<CalendarItem[]>([])
  const [me, setMe] = useState('')
  const [users, setUsers] = useState<string[]>([])
  const [view, setView] = useState<'month' | 'week'>('month')
  const [cursor, setCursor] = useState(() => new Date())
  const [who, setWho] = useState('')                 // '' = everyone
  const [picked, setPicked] = useState<string | null>(null)
  const [creating, setCreating] = useState<{ start: string; end: string } | null>(null)   // span of the new task
  // Click-drag over the grid (2026-09-30): the span turns orange, release opens New task.
  const [drag, setDrag] = useState<{ a: string; b: string } | null>(null)
  // Publishes on the calendar: a checkbox (remembered on this machine), one band per day.
  const [showPub, setShowPub] = useState<boolean>(() => { try { return localStorage.getItem(PUB_KEY) === '1' } catch { return false } })
  const [pubs, setPubs] = useState<CalendarPublish[]>([])
  const togglePub = (on: boolean) => {
    setShowPub(on)
    try { localStorage.setItem(PUB_KEY, on ? '1' : '0') } catch { /* private mode */ }
  }
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
      .then(r => { setItems(r.items); setMe(r.me) })
      .catch(e => toast.error(`${tr('Calendrier indisponible', 'Calendar unavailable')} : ${e instanceof Error ? e.message : String(e)}`))
  }, [project]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    load()
    const t = setInterval(load, POLL_MS)
    window.addEventListener('flux:refresh', load)
    return () => { clearInterval(t); window.removeEventListener('flux:refresh', load) }
  }, [load])
  useEffect(() => { api.listUsers().then(r => setUsers(r.users)).catch(() => setUsers([])) }, [])

  const shown = useMemo(() => items.filter(it => !who || same(it.owner, who)), [items, who])
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
    el.scrollTo({ top: Math.max(0, Math.min(row, range.weeks - 1)) * ROW_H, behavior: smooth ? 'smooth' : 'auto' })
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
    const row = Math.min(range.weeks - 1, Math.floor(el.scrollTop / ROW_H + 0.5))
    const sunday = addDays(range.start, row * 7 + 6)
    const m = new Date(sunday.getFullYear(), sunday.getMonth(), 1)
    setVisibleMonth(v => (v.getTime() === m.getTime() ? v : m))
  }
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
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)' }}>{tr('Calendrier', 'Calendar')}</div>
          <button style={{ ...btn(), padding: 4 }} onClick={() => move(-1)}><ChevronLeft size={13} /></button>
          <button style={btn()} onClick={goToday}>{tr("Aujourd'hui", 'Today')}</button>
          <button style={{ ...btn(), padding: 4 }} onClick={() => move(1)}><ChevronRight size={13} /></button>
          <div style={{ fontSize: 12, color: 'var(--ink-2)', minWidth: 150, textTransform: view === 'month' ? 'capitalize' : undefined }}>{title}</div>
          <div style={{ display: 'flex', gap: 4 }}>
            <button style={btn(view === 'month')} onClick={() => setView('month')}>{tr('Mois', 'Month')}</button>
            <button style={btn(view === 'week')} onClick={() => setView('week')}>{tr('Semaine', 'Week')}</button>
          </div>
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
          <button style={{ ...btn(true), marginLeft: 'auto' }} onClick={() => { setPicked(null); setCreating({ start: today, end: today }) }}>
            <Plus size={11} /> {tr('Ajouter une tâche', 'Add a task')}</button>
        </div>

        {/* grid */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, minmax(0, 1fr))', borderBottom: '1px solid var(--rule)' }}>
          {WEEKDAYS[l].map(d => <div key={d} style={{ ...lbl, padding: '6px 8px', marginBottom: 0 }}>{d}</div>)}
        </div>
        <div ref={scrollRef} onScroll={onGridScroll} style={{
          flex: 1, minHeight: 0, overflowY: 'auto', display: 'grid', gridTemplateColumns: 'repeat(7, minmax(0, 1fr))',
          gridAutoRows: view === 'month' ? `${ROW_H}px` : 'minmax(100%, auto)', alignContent: 'start',
        }}>
          {days.map((d, i) => {
            const day = iso(d)
            const list = itemsOn(day)
            // 2026-10-01: an accent stair line follows "today" in the grid, between
            // the past and today / the days to come (top of today's week, left of today).
            const weekBefore = iso(new Date(d.getFullYear(), d.getMonth(), d.getDate() - 7))
            const lineTop = view === 'month' && day >= today && weekBefore < today
            const lineLeft = view === 'month' && day === today && i % 7 !== 0
            const weekend = d.getDay() === 0 || d.getDay() === 6
            const past = day < today
            // 2026-09-30: weekends and past days dark, days to come light.
            const dark = weekend || past
            const selSpan = drag ? [drag.a, drag.b].sort() : creating ? [creating.start, creating.end] : null
            const inSpan = !!selSpan && day >= selSpan[0] && day <= selSpan[1]
            const cellBg = inSpan ? 'color-mix(in oklch, var(--accent) 22%, var(--paper))'
              : dark ? 'var(--bg-deep)'
              : 'color-mix(in oklch, var(--ink) 7%, var(--paper-2))'
            const max = view === 'month' ? MONTH_CHIPS : list.length
            return (
              <div key={day}
                   onMouseDown={e => { if (e.button === 0) { e.preventDefault(); setDrag({ a: day, b: day }) } }}
                   onMouseEnter={() => { if (drag) setDrag(g => (g ? { ...g, b: day } : g)) }}
                   title={tr('Clic ou clic-glisser sur plusieurs jours pour ajouter une tâche', 'Click, or click and drag over several days, to add a task')}
                   style={{
                     userSelect: 'none',
                     boxShadow: inSpan ? 'inset 0 0 0 1px var(--accent)' : undefined,
                     borderRight: '1px solid var(--rule)', borderBottom: '1px solid var(--rule)', padding: 5,
                     display: 'flex', flexDirection: 'column', gap: 3, minWidth: 0, cursor: 'copy',
                     background: cellBg, overflow: 'hidden', position: 'relative',
                   }}>
                {lineTop && <span style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 2, background: 'var(--accent)', pointerEvents: 'none' }} />}
                {lineLeft && <span style={{ position: 'absolute', top: 0, left: 0, bottom: 0, width: 2, background: 'var(--accent)', pointerEvents: 'none' }} />}
                <div style={{ fontSize: 10.5, fontWeight: day === today ? 700 : 500,
                              color: day === today || inSpan ? 'var(--accent-hi)' : dark ? 'var(--ink-2)' : 'var(--ink)' }}>
                  {view === 'week' ? shortDate(day, l) : d.getDate()}
                  {/* The 1st of each month carries its name: you see where a month starts while scrolling. */}
                  {view === 'month' && d.getDate() === 1 && (
                    <span style={{ marginLeft: 5, color: 'var(--accent-hi)', fontWeight: 700, textTransform: 'capitalize' }}>
                      {MONTHS[l][d.getMonth()]}{d.getMonth() === 0 ? ` ${d.getFullYear()}` : ''}
                    </span>
                  )}
                </div>
                {showPub && pubsOn(day).length > 0 && (
                  <PublishBand pubs={pubsOn(day)} />
                )}
                {list.slice(0, max).map(it => (
                  <Chip key={it.id} it={it} full={view === 'week'} selected={it.id === picked}
                        onClick={() => { setCreating(null); setPicked(it.id) }} />
                ))}
                {list.length > max && <div style={{ fontSize: 9.5, color: 'var(--ink-3)' }}>+{list.length - max} {tr('(vue semaine)', '(week view)')}</div>}
              </div>
            )
          })}
        </div>
      </div>

      {/* side panel */}
      <div style={{ width: 300, flexShrink: 0, borderLeft: '1px solid var(--rule)', background: 'var(--paper-2)', overflowY: 'auto', padding: 12, display: 'flex', flexDirection: 'column', gap: 14 }}>
        {creating && (
          <CreateForm project={project} me={me} users={users} range={creating}
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
            ? <div style={{ fontSize: 10.5, color: 'var(--ink-4)' }}>{tr('Aucune proposition pour toi.', 'No proposal for you.')}</div>
            : toAnswer.map(it => (
              <div key={it.id} style={{ marginBottom: 4 }}>
                <Chip it={it} full selected={it.id === picked} onClick={() => { setCreating(null); setPicked(it.id) }} />
                <div style={{ fontSize: 9.5, color: 'var(--ink-3)', margin: '2px 0 0 4px' }}>{span(it, l)} · {tr('de', 'from')} {it.created_by}</div>
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
