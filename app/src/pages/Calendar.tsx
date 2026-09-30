// Calendar.tsx — team calendar of the active project (2026-09-30).
//
// Each artist puts his commitments on it (what, when, optional link to an asset / shot /
// task) and everyone sees them: you commit in front of the team. A commitment for
// someone else is a proposal: it pings them, they accept, push it later then accept, or
// decline, and the author is pinged back. Month and week views, filter by person.
// Backend: features/calendar/calendar_store.py, routers/team_calendar.py.

import { useCallback, useEffect, useMemo, useState } from 'react'
import type { CSSProperties } from 'react'
import { toast } from 'sonner'
import { Check, ChevronLeft, ChevronRight, Plus, Trash2, X } from 'lucide-react'
import { api } from '../api/client'
import { useProject } from '../ProjectContext'
import type { CalendarItem } from '../types'

const POLL_MS = 30_000
const MONTH_CHIPS = 4
const WEEKDAYS = ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam', 'Dim']
const MONTHS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août',
  'septembre', 'octobre', 'novembre', 'décembre']
const STATUS_LABEL: Record<CalendarItem['status'], string> = {
  proposed: 'Proposé, en attente', accepted: 'Engagé', declined: 'Refusé', done: 'Fait',
}
const ACTION_LABEL: Record<string, string> = {
  create: 'a créé', propose: 'a proposé', accept: 'a accepté', postpone: 'a décalé et accepté',
  decline: 'a refusé', move: 'a déplacé', done: 'a marqué fait', reopen: 'a rouvert',
}

// ── dates (local, YYYY-MM-DD) ─────────────────────────────────────────────────
const pad = (n: number) => String(n).padStart(2, '0')
const iso = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
const fromIso = (s: string) => { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d) }
const addDays = (d: Date, n: number) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n)
const mondayOf = (d: Date) => addDays(d, -((d.getDay() + 6) % 7))
const todayIso = () => iso(new Date())
const same = (a: string, b: string) => a.trim().toLowerCase() === b.trim().toLowerCase()
const shortDate = (s: string) => { const d = fromIso(s); return `${d.getDate()} ${MONTHS[d.getMonth()].slice(0, 4)}.` }
const span = (it: CalendarItem) => it.start === it.end ? shortDate(it.start) : `${shortDate(it.start)} au ${shortDate(it.end)}`

// One flat color per person (hash of the name), never neon.
function userColor(name: string): string {
  let h = 0
  for (const ch of name.toLowerCase()) h = (h * 31 + ch.charCodeAt(0)) % 360
  return `oklch(66% 0.09 ${h})`
}

const isOverdue = (it: CalendarItem) => it.status === 'accepted' && it.end < todayIso()

const btn = (primary = false, danger = false): CSSProperties => ({
  display: 'inline-flex', alignItems: 'center', gap: 5, padding: '5px 10px', fontSize: 11, borderRadius: 6,
  cursor: 'pointer', fontFamily: 'var(--sans)',
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

// ── chip ─────────────────────────────────────────────────────────────────────
function Chip({ it, selected, onClick, full }: { it: CalendarItem; selected: boolean; onClick: () => void; full?: boolean }) {
  const c = userColor(it.owner)
  const overdue = isOverdue(it)
  return (
    <div
      onClick={e => { e.stopPropagation(); onClick() }}
      title={`${it.title} · ${it.owner} · ${span(it)} · ${STATUS_LABEL[it.status]}${overdue ? ' · en retard' : ''}`}
      style={{
        fontSize: 10.5, lineHeight: 1.3, padding: full ? '5px 7px' : '2px 5px', borderRadius: 4, cursor: 'pointer',
        background: `color-mix(in oklch, ${c} 20%, transparent)`,
        border: it.status === 'proposed' ? `1px dashed ${c}` : '1px solid transparent',
        borderLeft: `3px solid ${overdue ? 'var(--err)' : c}`,
        outline: selected ? '1px solid var(--accent)' : undefined,
        opacity: it.status === 'declined' ? 0.45 : it.status === 'done' ? 0.6 : 1,
        textDecoration: it.status === 'declined' ? 'line-through' : undefined,
        color: 'var(--ink)', overflow: 'hidden', whiteSpace: full ? 'normal' : 'nowrap', textOverflow: 'ellipsis',
      }}
    >
      {it.status === 'done' && <Check size={9} strokeWidth={2.4} style={{ marginRight: 3, verticalAlign: -1 }} />}
      {it.title}
      {full && <div style={{ fontSize: 9.5, color: 'var(--ink-2)' }}>{it.owner}{it.link ? ` · ${it.link}` : ''}</div>}
    </div>
  )
}

// ── create form ──────────────────────────────────────────────────────────────
function CreateForm({ project, me, users, day, onDone, onCancel }: {
  project: string; me: string; users: string[]; day: string
  onDone: (it: CalendarItem) => void; onCancel: () => void
}) {
  const [title, setTitle] = useState('')
  const [owner, setOwner] = useState(me)
  const [start, setStart] = useState(day)
  const [end, setEnd] = useState(day)
  const [link, setLink] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { setStart(day); setEnd(day) }, [day])
  const forOther = !!owner && !same(owner, me)
  const submit = async () => {
    setBusy(true)
    try {
      const r = await api.createCalendarItem(project, { title, owner, start, end: end < start ? start : end, note, link })
      toast.success(forOther ? `Proposé à ${owner} (notifié)` : 'Engagement ajouté')
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
        <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--ink)', flex: 1 }}>Nouvel engagement</div>
        <button style={{ ...btn(), padding: 3 }} onClick={onCancel}><X size={12} /></button>
      </div>
      <div><div style={lbl}>Quoi</div>
        <input autoFocus style={input} value={title} onChange={e => setTitle(e.target.value)} placeholder="Ex. blocking SHOT020" /></div>
      <div><div style={lbl}>Qui s'engage</div>
        <select style={input} value={owner} onChange={e => setOwner(e.target.value)}>
          {[me, ...users.filter(u => !same(u, me))].map(u => <option key={u} value={u}>{same(u, me) ? `${u} (moi)` : u}</option>)}
        </select>
        {forOther && <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 4 }}>{owner} sera notifié et pourra accepter, décaler ou refuser.</div>}
      </div>
      <div style={{ display: 'flex', gap: 6 }}>
        <div style={{ flex: 1 }}><div style={lbl}>Début</div><input type="date" style={input} value={start} onChange={e => setStart(e.target.value)} /></div>
        <div style={{ flex: 1 }}><div style={lbl}>Fin</div><input type="date" style={input} value={end} min={start} onChange={e => setEnd(e.target.value)} /></div>
      </div>
      <div><div style={lbl}>Lien (optionnel)</div>
        <input style={input} value={link} onChange={e => setLink(e.target.value)} placeholder="SEQ010 SHOT020 ANIM, CHAR_HORSE RIG…" /></div>
      <div><div style={lbl}>Note (optionnel)</div>
        <textarea style={{ ...input, minHeight: 54, resize: 'vertical' }} value={note} onChange={e => setNote(e.target.value)} /></div>
      <button style={btn(true)} disabled={busy || !title.trim() || !start} onClick={() => { void submit() }}>
        <Plus size={11} /> {forOther ? `Proposer à ${owner}` : 'Ajouter'}
      </button>
    </div>
  )
}

// ── detail ───────────────────────────────────────────────────────────────────
function Detail({ project, me, it, onChanged, onDeleted, onClose }: {
  project: string; me: string; it: CalendarItem
  onChanged: (it: CalendarItem) => void; onDeleted: (id: string) => void; onClose: () => void
}) {
  const isOwner = same(it.owner, me)
  const isAuthor = same(it.created_by, me)
  const canEdit = isOwner || (isAuthor && it.status === 'proposed')
  const [start, setStart] = useState(it.start)
  const [end, setEnd] = useState(it.end)
  const [postponing, setPostponing] = useState(false)
  const [busy, setBusy] = useState(false)
  useEffect(() => { setStart(it.start); setEnd(it.end); setPostponing(false) }, [it.id, it.start, it.end])

  const run = async (fn: () => Promise<{ item: CalendarItem }>, ok: string) => {
    setBusy(true)
    try { const r = await fn(); onChanged(r.item); toast.success(ok) }
    catch (e) { toast.error(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }
  const remove = async () => {
    if (!window.confirm(`Supprimer « ${it.title} » ?`)) return
    try { await api.deleteCalendarItem(project, it.id); onDeleted(it.id); toast.success('Supprimé') }
    catch (e) { toast.error(e instanceof Error ? e.message : String(e)) }
  }
  const datesChanged = start !== it.start || end !== it.end

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 6 }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)' }}>{it.title}</div>
          <div style={{ fontSize: 10.5, color: 'var(--ink-2)', marginTop: 2, display: 'flex', alignItems: 'center', gap: 5 }}>
            <span style={{ width: 8, height: 8, borderRadius: 2, background: userColor(it.owner), display: 'inline-block' }} />
            {it.owner} · {span(it)}
          </div>
        </div>
        <button style={{ ...btn(), padding: 3 }} onClick={onClose}><X size={12} /></button>
      </div>
      <div style={{ fontSize: 10.5, color: isOverdue(it) ? 'var(--err)' : 'var(--ink-2)' }}>
        {STATUS_LABEL[it.status]}{isOverdue(it) ? ' · en retard' : ''}
        {!same(it.created_by, it.owner) && ` · proposé par ${it.created_by}`}
      </div>
      {it.link && <div style={{ fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--ink-2)' }}>{it.link}</div>}
      {it.note && <div style={{ fontSize: 11, color: 'var(--ink-2)', whiteSpace: 'pre-wrap' }}>{it.note}</div>}

      {/* Answer a proposal made to me */}
      {isOwner && it.status === 'proposed' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, padding: 8, border: '1px solid var(--rule-2)', borderRadius: 6 }}>
          <div style={lbl}>{it.created_by} te propose ceci</div>
          {!postponing ? (
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              <button style={btn(true)} disabled={busy} onClick={() => { void run(() => api.respondCalendarItem(project, it.id, 'accept'), 'Accepté') }}>
                <Check size={11} /> Accepter</button>
              <button style={btn()} disabled={busy} onClick={() => setPostponing(true)}>Décaler</button>
              <button style={btn(false, true)} disabled={busy} onClick={() => { void run(() => api.respondCalendarItem(project, it.id, 'decline'), 'Refusé') }}>Refuser</button>
            </div>
          ) : (
            <>
              <div style={{ display: 'flex', gap: 6 }}>
                <input type="date" style={input} value={start} min={it.start} onChange={e => { setStart(e.target.value); if (end < e.target.value) setEnd(e.target.value) }} />
                <input type="date" style={input} value={end} min={start} onChange={e => setEnd(e.target.value)} />
              </div>
              <div style={{ display: 'flex', gap: 6 }}>
                <button style={btn(true)} disabled={busy || !datesChanged}
                        onClick={() => { void run(() => api.respondCalendarItem(project, it.id, 'postpone', start, end), 'Décalé et accepté') }}>
                  Décaler et accepter</button>
                <button style={btn()} onClick={() => { setPostponing(false); setStart(it.start); setEnd(it.end) }}>Annuler</button>
              </div>
            </>
          )}
        </div>
      )}

      {/* Owner / author of a pending proposal: move the dates */}
      {canEdit && !(isOwner && it.status === 'proposed') && it.status !== 'declined' && (
        <div>
          <div style={lbl}>Dates</div>
          <div style={{ display: 'flex', gap: 6 }}>
            <input type="date" style={input} value={start} onChange={e => { setStart(e.target.value); if (end < e.target.value) setEnd(e.target.value) }} />
            <input type="date" style={input} value={end} min={start} onChange={e => setEnd(e.target.value)} />
          </div>
          {datesChanged && (
            <button style={{ ...btn(true), marginTop: 6 }} disabled={busy}
                    onClick={() => { void run(() => api.updateCalendarItem(project, it.id, { start, end }), 'Dates mises à jour') }}>
              Enregistrer les dates</button>
          )}
        </div>
      )}

      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {isOwner && it.status === 'accepted' && (
          <button style={btn(true)} disabled={busy} onClick={() => { void run(() => api.updateCalendarItem(project, it.id, { status: 'done' }), 'Marqué fait') }}>
            <Check size={11} /> Fait</button>
        )}
        {isOwner && it.status === 'done' && (
          <button style={btn()} disabled={busy} onClick={() => { void run(() => api.updateCalendarItem(project, it.id, { status: 'accepted' }), 'Rouvert') }}>Rouvrir</button>
        )}
        {(isOwner || isAuthor) && (
          <button style={btn(false, true)} onClick={() => { void remove() }}><Trash2 size={11} /> Supprimer</button>
        )}
      </div>

      {it.history?.length > 0 && (
        <div>
          <div style={lbl}>Historique</div>
          {[...it.history].reverse().map((h, i) => (
            <div key={i} style={{ fontSize: 10, color: 'var(--ink-3)', lineHeight: 1.6 }}>
              {h.at.slice(0, 10)} · {h.by} {ACTION_LABEL[h.action] ?? h.action}
              {h.start ? ` (${h.start === h.end ? shortDate(h.start) : `${shortDate(h.start)} au ${shortDate(h.end ?? h.start)}`})` : ''}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── page ─────────────────────────────────────────────────────────────────────
export function Calendar() {
  const { project } = useProject()
  const [items, setItems] = useState<CalendarItem[]>([])
  const [me, setMe] = useState('')
  const [users, setUsers] = useState<string[]>([])
  const [view, setView] = useState<'month' | 'week'>('month')
  const [cursor, setCursor] = useState(() => new Date())
  const [who, setWho] = useState('')                 // '' = everyone
  const [picked, setPicked] = useState<string | null>(null)
  const [creating, setCreating] = useState<string | null>(null)   // day of the new item

  const load = useCallback(() => {
    if (!project) return
    api.getCalendar(project)
      .then(r => { setItems(r.items); setMe(r.me) })
      .catch(e => toast.error(`Calendrier indisponible : ${e instanceof Error ? e.message : String(e)}`))
  }, [project])
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

  // Visible days: 6 weeks from the Monday before the 1st, or the week of the cursor.
  const days = useMemo(() => {
    const first = view === 'month' ? mondayOf(new Date(cursor.getFullYear(), cursor.getMonth(), 1)) : mondayOf(cursor)
    return Array.from({ length: view === 'month' ? 42 : 7 }, (_, i) => addDays(first, i))
  }, [cursor, view])
  const itemsOn = (day: string) => shown
    .filter(it => it.start <= day && day <= it.end)
    .sort((a, b) => a.start.localeCompare(b.start) || a.owner.localeCompare(b.owner))

  const move = (dir: number) => setCursor(c => view === 'month'
    ? new Date(c.getFullYear(), c.getMonth() + dir, 1)
    : addDays(c, 7 * dir))
  const title = view === 'month'
    ? `${MONTHS[cursor.getMonth()]} ${cursor.getFullYear()}`
    : `Semaine du ${shortDate(iso(days[0]))} au ${shortDate(iso(days[6]))}`
  const today = todayIso()

  const upsert = (it: CalendarItem) => setItems(list => list.some(x => x.id === it.id) ? list.map(x => x.id === it.id ? it : x) : [...list, it])

  if (!project) {
    return <div style={{ padding: 24, fontSize: 12, color: 'var(--ink-3)' }}>Aucun projet actif : choisis-en un dans le Folder Manager.</div>
  }

  return (
    <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        {/* header */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 14px', borderBottom: '1px solid var(--rule)', flexWrap: 'wrap' }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)' }}>Calendrier</div>
          <button style={{ ...btn(), padding: 4 }} onClick={() => move(-1)}><ChevronLeft size={13} /></button>
          <button style={btn()} onClick={() => setCursor(new Date())}>Aujourd'hui</button>
          <button style={{ ...btn(), padding: 4 }} onClick={() => move(1)}><ChevronRight size={13} /></button>
          <div style={{ fontSize: 12, color: 'var(--ink-2)', minWidth: 150, textTransform: view === 'month' ? 'capitalize' : undefined }}>{title}</div>
          <div style={{ display: 'flex', gap: 4 }}>
            <button style={btn(view === 'month')} onClick={() => setView('month')}>Mois</button>
            <button style={btn(view === 'week')} onClick={() => setView('week')}>Semaine</button>
          </div>
          <select style={{ ...input, width: 150 }} value={who} onChange={e => setWho(e.target.value)}>
            <option value="">Tout le monde</option>
            {[...new Set([me, ...users, ...items.map(i => i.owner)].filter(Boolean))].map(u => (
              <option key={u} value={u}>{same(u, me) ? `${u} (moi)` : u}</option>
            ))}
          </select>
          <button style={{ ...btn(true), marginLeft: 'auto' }} onClick={() => { setPicked(null); setCreating(today) }}>
            <Plus size={11} /> Engagement</button>
        </div>

        {/* grid */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, minmax(0, 1fr))', borderBottom: '1px solid var(--rule)' }}>
          {WEEKDAYS.map(d => <div key={d} style={{ ...lbl, padding: '6px 8px', marginBottom: 0 }}>{d}</div>)}
        </div>
        <div style={{
          flex: 1, minHeight: 0, overflowY: 'auto', display: 'grid', gridTemplateColumns: 'repeat(7, minmax(0, 1fr))',
          gridAutoRows: view === 'month' ? 'minmax(96px, 1fr)' : 'minmax(100%, auto)',
        }}>
          {days.map(d => {
            const day = iso(d)
            const list = itemsOn(day)
            const outside = view === 'month' && d.getMonth() !== cursor.getMonth()
            const weekend = d.getDay() === 0 || d.getDay() === 6
            const max = view === 'month' ? MONTH_CHIPS : list.length
            return (
              <div key={day} onClick={() => { setPicked(null); setCreating(day) }}
                   title="Cliquer pour ajouter un engagement ce jour-là"
                   style={{
                     borderRight: '1px solid var(--rule)', borderBottom: '1px solid var(--rule)', padding: 5,
                     display: 'flex', flexDirection: 'column', gap: 3, minWidth: 0, cursor: 'copy',
                     background: weekend ? 'var(--paper-2)' : 'var(--paper)', opacity: outside ? 0.45 : 1,
                   }}>
                <div style={{ fontSize: 10.5, fontWeight: day === today ? 700 : 400, color: day === today ? 'var(--accent-hi)' : 'var(--ink-3)' }}>
                  {view === 'week' ? `${d.getDate()} ${MONTHS[d.getMonth()].slice(0, 4)}.` : d.getDate()}
                </div>
                {list.slice(0, max).map(it => (
                  <Chip key={it.id} it={it} full={view === 'week'} selected={it.id === picked}
                        onClick={() => { setCreating(null); setPicked(it.id) }} />
                ))}
                {list.length > max && <div style={{ fontSize: 9.5, color: 'var(--ink-3)' }}>+{list.length - max} (vue semaine)</div>}
              </div>
            )
          })}
        </div>
      </div>

      {/* side panel */}
      <div style={{ width: 300, flexShrink: 0, borderLeft: '1px solid var(--rule)', background: 'var(--paper-2)', overflowY: 'auto', padding: 12, display: 'flex', flexDirection: 'column', gap: 14 }}>
        {creating && (
          <CreateForm project={project} me={me} users={users} day={creating}
                      onCancel={() => setCreating(null)}
                      onDone={it => { upsert(it); setCreating(null); setPicked(it.id) }} />
        )}
        {!creating && pickedItem && (
          <Detail project={project} me={me} it={pickedItem} onChanged={upsert}
                  onDeleted={id => { setItems(l => l.filter(x => x.id !== id)); setPicked(null) }}
                  onClose={() => setPicked(null)} />
        )}
        <div>
          <div style={lbl}>À valider ({toAnswer.length})</div>
          {toAnswer.length === 0
            ? <div style={{ fontSize: 10.5, color: 'var(--ink-4)' }}>Aucune proposition pour toi.</div>
            : toAnswer.map(it => (
              <div key={it.id} style={{ marginBottom: 4 }}>
                <Chip it={it} full selected={it.id === picked} onClick={() => { setCreating(null); setPicked(it.id) }} />
                <div style={{ fontSize: 9.5, color: 'var(--ink-3)', margin: '2px 0 0 4px' }}>{span(it)} · de {it.created_by}</div>
              </div>
            ))}
        </div>
        {waiting.length > 0 && (
          <div>
            <div style={lbl}>En attente de réponse ({waiting.length})</div>
            {waiting.map(it => (
              <div key={it.id} style={{ marginBottom: 4 }}>
                <Chip it={it} full selected={it.id === picked} onClick={() => { setCreating(null); setPicked(it.id) }} />
              </div>
            ))}
          </div>
        )}
        <div style={{ fontSize: 9.5, color: 'var(--ink-4)', lineHeight: 1.5 }}>
          Pointillés : proposé, en attente. Bord rouge : en retard. Barré : refusé.
        </div>
      </div>
    </div>
  )
}
