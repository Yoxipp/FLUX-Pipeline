// DataWidgets.tsx — the widgets that SHOW records (ADR 0066 n°2): feed, table, cards,
// calendar, members; the board lives in BoardWidget.tsx. Each one reads its source
// (a collection of the page, the last run of a flow, or the FLUX users) and writes
// through usePageData (one journal per author, ADR 0066 n°3). Official widgets only:
// an extension composes them in YAML, it never ships code (ADR 0066 n°5).
// Flat surfaces, theme variables, no glow.

import { useEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent, type ReactNode } from 'react'
import { ChevronLeft, ChevronRight, Plus, Send, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '../../api/client'
import { flowsApi } from '../../api/flows'
import { Avatar } from '../../components/shared/ui'
import { usePageData, type PageData } from '../../hooks/usePages'
import type { PageDataField, PageDataSpec, PageDoc, PageRecord, PageWidget, RunSummary } from '../flow_editor/types'
import { useTr } from '../flow_editor/useTr'
import { ago } from './links'
import { BoardWidget } from './BoardWidget'
import { ChatWidget } from './ChatWidget'
import './tool_pages.css'

export interface DataWidgetProps { page: PageDoc; widget: PageWidget; project?: string; preview?: boolean }

const box: CSSProperties = { border: '1px solid var(--rule)', borderRadius: 8, background: 'var(--paper)', minWidth: 0 }
const input: CSSProperties = { height: 26, padding: '0 8px', border: '1px solid var(--rule-2)', background: 'var(--bg-deep)', borderRadius: 5, fontSize: 12, color: 'var(--ink)', minWidth: 0 }

const fail = (err: unknown) => toast.error((err as Error).message)

function specOf(page: PageDoc, w: PageWidget): PageDataSpec | undefined {
  return page.data.find(d => d.id === w.source?.data)
}

export function fieldText(rec: PageRecord, f: PageDataField | undefined): string {
  if (!f) return ''
  const v = rec[f.id]
  if (v === undefined || v === null) return ''
  if (f.type === 'bool') return v ? 'oui' : 'non'
  if (f.type === 'select') return f.options?.find(o => o.value === v)?.label || String(v)
  return String(v)
}

// One input per field type (table, cards, calendar forms).
export function FieldInput({ field, value, onChange, autoFocus }: { field: PageDataField; value: unknown; onChange: (v: unknown) => void; autoFocus?: boolean }) {
  const s = value === undefined || value === null ? '' : String(value)
  switch (field.type) {
    case 'bool':
      return <input type="checkbox" checked={Boolean(value)} onChange={e => onChange(e.target.checked)} />
    case 'int':
    case 'float':
      return <input type="number" value={s} autoFocus={autoFocus} style={input}
                    onChange={e => onChange(e.target.value === '' ? null : field.type === 'int' ? parseInt(e.target.value, 10) : parseFloat(e.target.value))} />
    case 'date':
      return <input type="date" value={s} autoFocus={autoFocus} style={input} onChange={e => onChange(e.target.value || null)} />
    case 'datetime':
      return <input type="datetime-local" value={s.slice(0, 16)} autoFocus={autoFocus} style={input} onChange={e => onChange(e.target.value || null)} />
    case 'select':
      return (
        <select value={s} style={input} onChange={e => onChange(e.target.value || null)}>
          <option value="" />
          {(field.options ?? []).map(o => <option key={o.value} value={o.value}>{o.label || o.value}</option>)}
        </select>
      )
    case 'text':
      return <textarea value={s} autoFocus={autoFocus} style={{ ...input, height: 54, padding: '6px 8px', resize: 'vertical' }} onChange={e => onChange(e.target.value)} />
    default:
      return <input value={s} autoFocus={autoFocus} style={input} onChange={e => onChange(e.target.value)} />
  }
}

function State({ data, empty, preview }: { data: PageData; empty: string; preview?: boolean }) {
  const { tr } = useTr()
  // Editor preview of a collection not saved yet: the backend does not know it.
  if (data.error && preview) return <div className="tp-note" style={{ padding: 10 }}>{tr('Apercu : enregistre la page pour lire ses donnees.', 'Preview: save the page to read its data.')}</div>
  if (data.error) return <div className="tp-note" style={{ color: 'var(--err)', padding: 10 }}>{data.error}</div>
  if (!data.loaded) return <div className="tp-note" style={{ color: 'var(--ink-4)', padding: 10 }}>{tr('Chargement...', 'Loading...')}</div>
  if (!data.records.length) return <div className="tp-note" style={{ color: 'var(--ink-4)', padding: 10 }}>{empty}</div>
  return null
}

function Title({ w, right }: { w: PageWidget; right?: ReactNode }) {
  if (!w.label && !right) return null
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 10px', borderBottom: '1px solid var(--rule)' }}>
      <span style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--ink)', flex: 1 }}>{w.label}</span>
      {right}
    </div>
  )
}

// -- feed (Teams-like) -------------------------------------------------------------------------

function Feed({ page, widget: w, project, preview }: DataWidgetProps) {
  const { tr, lang } = useTr()
  const spec = specOf(page, w)
  const data = usePageData(page.id, spec?.id ?? '', project, !!spec)
  const textField = w.field ?? 'text'
  const group = w.group_by ? spec?.fields?.find(f => f.id === w.group_by) : undefined
  const groups = useMemo(() => {
    if (!group) return []
    if (group.type === 'select') return (group.options ?? []).map(o => ({ value: o.value, label: o.label || o.value }))
    return [...new Set(data.records.map(r => String(r[group.id] ?? '')).filter(Boolean))].map(v => ({ value: v, label: v }))
  }, [group, data.records])
  const [channel, setChannel] = useState<string>('')
  const current = channel || groups[0]?.value || ''
  const [draft, setDraft] = useState('')
  const end = useRef<HTMLDivElement>(null)
  const shown = data.records.filter(r => !group || String(r[group.id] ?? '') === current)
  useEffect(() => { end.current?.scrollIntoView({ block: 'end' }) }, [shown.length])

  const send = () => {
    const text = draft.trim()
    if (!text || !spec) return
    setDraft('')
    data.put({ [textField]: text, ...(group && current ? { [group.id]: current } : {}) }).catch(err => { setDraft(text); fail(err) })
  }
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
  }
  return (
    <div style={{ ...box, display: 'flex', flexDirection: 'column', height: w.height ?? 380 }}>
      <Title w={w} />
      {groups.length > 0 && (
        <div style={{ display: 'flex', gap: 4, padding: '6px 8px', borderBottom: '1px solid var(--rule)', flexWrap: 'wrap' }}>
          {groups.map(g => (
            <button type="button" key={g.value} className="btn ghost sm" onClick={() => setChannel(g.value)}
                    style={{ background: g.value === current ? 'var(--paper-2)' : 'transparent', color: g.value === current ? 'var(--ink)' : 'var(--ink-3)' }}>
              # {g.label}
            </button>
          ))}
        </div>
      )}
      <div style={{ flex: 1, overflowY: 'auto', padding: '8px 10px', display: 'flex', flexDirection: 'column', gap: 8 }}>
        <State data={data} preview={preview} empty={tr('Aucun message pour le moment.', 'No message yet.')} />
        {shown.map(r => (
          <div key={r.rid} style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
            <span style={{ position: 'relative', display: 'inline-flex', flexShrink: 0 }}>
              <Avatar ch={(r._created_by || '?').slice(0, 1)} size={22} />
            </span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: 'flex', gap: 6, alignItems: 'baseline' }}>
                <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--ink)' }}>{r._created_by}</span>
                <span className="tp-note" style={{ color: 'var(--ink-4)' }}>{ago(r._created_at, lang)}</span>
                {data.canWrite && r._created_by === data.me && (
                  <button type="button" className="btn ghost sm" title={tr('Supprimer', 'Delete')} style={{ marginLeft: 'auto', padding: '0 4px' }}
                          onClick={() => { data.del(r.rid).catch(fail) }}><Trash2 size={11} /></button>
                )}
              </div>
              <div style={{ fontSize: 12.5, color: 'var(--ink-2)', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{String(r[textField] ?? '')}</div>
            </div>
          </div>
        ))}
        <div ref={end} />
      </div>
      {data.canWrite && !preview && (
        <div style={{ display: 'flex', gap: 6, padding: 8, borderTop: '1px solid var(--rule)' }}>
          <textarea value={draft} onChange={e => setDraft(e.target.value)} onKeyDown={onKey} rows={1}
                    placeholder={group && current ? tr(`Message dans #${current}`, `Message in #${current}`) : tr('Ecrire un message', 'Write a message')}
                    style={{ ...input, flex: 1, height: 32, padding: '6px 8px', resize: 'none' }} />
          <button type="button" className="btn primary" onClick={send} disabled={!draft.trim()} title={tr('Envoyer (Entree)', 'Send (Enter)')}><Send size={13} /></button>
        </div>
      )}
    </div>
  )
}

// -- record form (table / cards / calendar) ---------------------------------------------------------

function RecordForm({ fields, initial, onSave, onCancel }: {
  fields: PageDataField[]; initial: Record<string, unknown>; onSave: (v: Record<string, unknown>) => void; onCancel: () => void
}) {
  const { tr } = useTr()
  const [v, setV] = useState<Record<string, unknown>>(initial)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, padding: 8, background: 'var(--paper-2)', borderRadius: 6 }}>
      {fields.map((f, k) => (
        <label key={f.id} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span className="cap" style={{ width: 110, flexShrink: 0 }}>{f.label || f.id}{f.required ? ' *' : ''}</span>
          <FieldInput field={f} value={v[f.id]} autoFocus={k === 0} onChange={x => setV(o => ({ ...o, [f.id]: x }))} />
        </label>
      ))}
      <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
        <button type="button" className="btn ghost sm" onClick={onCancel}>{tr('Annuler', 'Cancel')}</button>
        <button type="button" className="btn primary sm" onClick={() => onSave(v)}>{tr('Enregistrer', 'Save')}</button>
      </div>
    </div>
  )
}

function writable(fields: PageDataField[]): PageDataField[] {
  return fields.filter(f => f.type !== 'image')
}

// -- table ---------------------------------------------------------------------------------------

function Table({ page, widget: w, project, preview }: DataWidgetProps) {
  const { tr } = useTr()
  const spec = specOf(page, w)
  const data = usePageData(page.id, spec?.id ?? '', project, !!spec)
  const fields = spec?.fields ?? []
  const cols = w.columns?.length ? fields.filter(f => w.columns!.includes(f.id)) : fields
  const [editing, setEditing] = useState<string | 'new' | null>(null)
  const canEdit = !!w.editable && data.canWrite && !preview
  const save = (rid: string | undefined) => (v: Record<string, unknown>) => {
    setEditing(null)
    data.put(v, rid).catch(fail)
  }
  return (
    <div style={box}>
      <Title w={w} right={canEdit && <button type="button" className="btn ghost sm" onClick={() => setEditing('new')}><Plus size={12} /> {tr('Ligne', 'Row')}</button>} />
      {editing === 'new' && <div style={{ padding: 8 }}><RecordForm fields={writable(fields)} initial={{}} onSave={save(undefined)} onCancel={() => setEditing(null)} /></div>}
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr>{cols.map(c => <th key={c.id} className="cap" style={{ textAlign: 'left', padding: '6px 10px', borderBottom: '1px solid var(--rule)' }}>{c.label || c.id}</th>)}
              <th className="cap" style={{ textAlign: 'left', padding: '6px 10px', borderBottom: '1px solid var(--rule)' }}>{tr('Par', 'By')}</th>
              {canEdit && <th style={{ borderBottom: '1px solid var(--rule)' }} />}</tr>
          </thead>
          <tbody>
            {data.records.map(r => editing === r.rid
              ? <tr key={r.rid}><td colSpan={cols.length + 2} style={{ padding: 6 }}>
                  <RecordForm fields={writable(fields)} initial={r} onSave={save(r.rid)} onCancel={() => setEditing(null)} /></td></tr>
              : <tr key={r.rid} onDoubleClick={() => canEdit && setEditing(r.rid)} style={{ cursor: canEdit ? 'pointer' : 'default' }}>
                  {cols.map(c => <td key={c.id} style={{ padding: '5px 10px', borderBottom: '1px solid var(--rule)', color: 'var(--ink-2)' }}>{fieldText(r, c)}</td>)}
                  <td className="tp-note" style={{ padding: '5px 10px', borderBottom: '1px solid var(--rule)', color: 'var(--ink-4)' }}>{r._by}</td>
                  {canEdit && <td style={{ borderBottom: '1px solid var(--rule)', width: 28 }}>
                    <button type="button" className="btn ghost sm" title={tr('Supprimer', 'Delete')} onClick={() => { data.del(r.rid).catch(fail) }}><Trash2 size={11} /></button></td>}
                </tr>)}
          </tbody>
        </table>
      </div>
      <State data={data} preview={preview} empty={tr('Aucune ligne.', 'No row.')} />
    </div>
  )
}

// -- cards (kanban when grouped) ---------------------------------------------------------------------

function Cards({ page, widget: w, project, preview }: DataWidgetProps) {
  const { tr } = useTr()
  const spec = specOf(page, w)
  const data = usePageData(page.id, spec?.id ?? '', project, !!spec)
  const fields = spec?.fields ?? []
  const title = fields.find(f => f.id === w.title) ?? fields.find(f => f.type === 'str' || f.type === 'text')
  const group = w.group_by ? fields.find(f => f.id === w.group_by) : undefined
  const columns = useMemo(() => {
    if (!group) return [{ value: '', label: '' }]
    if (group.type === 'select') return [...(group.options ?? []).map(o => ({ value: o.value, label: o.label || o.value }))]
    if (group.type === 'bool') return [{ value: 'false', label: tr('Non', 'No') }, { value: 'true', label: tr('Oui', 'Yes') }]
    return [...new Set(data.records.map(r => String(r[group.id] ?? '')))].map(v => ({ value: v, label: v || '-' }))
  }, [group, data.records, tr])
  const canEdit = !!w.editable && data.canWrite && !preview
  const [adding, setAdding] = useState<string | null>(null)
  const [editing, setEditing] = useState<string | null>(null)
  const groupValue = (v: string): unknown => group?.type === 'bool' ? v === 'true' : v
  const others = fields.filter(f => f !== title && f !== group).slice(0, 3)

  return (
    <div style={box}>
      <Title w={w} />
      <div style={{ display: 'grid', gridTemplateColumns: `repeat(${columns.length}, minmax(180px, 1fr))`, gap: 10, padding: 10, overflowX: 'auto' }}>
        {columns.map(col => (
          <div key={col.value} onDragOver={e => { if (canEdit && group) e.preventDefault() }}
               onDrop={e => { const rid = e.dataTransfer.getData('text/flux-rid'); if (rid && group) data.put({ [group.id]: groupValue(col.value) }, rid).catch(fail) }}
               style={{ display: 'flex', flexDirection: 'column', gap: 6, minHeight: 60 }}>
            {group && <div className="cap" style={{ display: 'flex', alignItems: 'center' }}>
              <span style={{ flex: 1 }}>{col.label}</span>
              {canEdit && <button type="button" className="btn ghost sm" onClick={() => setAdding(col.value)}><Plus size={11} /></button>}
            </div>}
            {!group && canEdit && <button type="button" className="btn ghost sm" style={{ alignSelf: 'flex-start' }} onClick={() => setAdding('')}><Plus size={11} /> {tr('Carte', 'Card')}</button>}
            {adding === col.value && <RecordForm fields={writable(fields)} initial={group ? { [group.id]: groupValue(col.value) } : {}}
                                                 onSave={v => { setAdding(null); data.put(v).catch(fail) }} onCancel={() => setAdding(null)} />}
            {data.records.filter(r => !group || String(r[group.id] ?? (group.type === 'bool' ? 'false' : '')) === col.value).map(r => editing === r.rid
              ? <RecordForm key={r.rid} fields={writable(fields)} initial={r} onSave={v => { setEditing(null); data.put(v, r.rid).catch(fail) }} onCancel={() => setEditing(null)} />
              : <div key={r.rid} draggable={canEdit && !!group} onDragStart={e => e.dataTransfer.setData('text/flux-rid', r.rid)}
                     onDoubleClick={() => canEdit && setEditing(r.rid)}
                     style={{ padding: '8px 10px', borderRadius: 6, background: 'var(--paper-2)', border: '1px solid var(--rule)', cursor: canEdit ? 'grab' : 'default' }}>
                  <div style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--ink)', wordBreak: 'break-word' }}>{fieldText(r, title) || r.rid}</div>
                  {others.map(f => fieldText(r, f) && <div key={f.id} className="tp-note" style={{ color: 'var(--ink-3)' }}>{f.label || f.id} : {fieldText(r, f)}</div>)}
                  <div className="tp-note" style={{ color: 'var(--ink-4)', display: 'flex' }}>
                    <span style={{ flex: 1 }}>{r._by}</span>
                    {canEdit && <button type="button" className="btn ghost sm" style={{ padding: '0 4px' }} onClick={() => { data.del(r.rid).catch(fail) }}><Trash2 size={11} /></button>}
                  </div>
                </div>)}
          </div>
        ))}
      </div>
      <State data={data} preview={preview} empty={tr('Aucune carte.', 'No card.')} />
    </div>
  )
}

// -- calendar -----------------------------------------------------------------------------------------

const DAYS_FR = ['lun', 'mar', 'mer', 'jeu', 'ven', 'sam', 'dim']
const DAYS_EN = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

function ymd(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function Calendar({ page, widget: w, project, preview }: DataWidgetProps) {
  const { tr, lang } = useTr()
  const spec = specOf(page, w)
  const data = usePageData(page.id, spec?.id ?? '', project, !!spec)
  const fields = spec?.fields ?? []
  const dateField = fields.find(f => f.id === w.date) ?? fields.find(f => f.type === 'date' || f.type === 'datetime')
  const endField = w.end ? fields.find(f => f.id === w.end) : undefined
  const title = fields.find(f => f.id === w.title) ?? fields.find(f => f.type === 'str' || f.type === 'text')
  const [month, setMonth] = useState(() => { const d = new Date(); return new Date(d.getFullYear(), d.getMonth(), 1) })
  const [adding, setAdding] = useState<string | null>(null)
  const [editing, setEditing] = useState<string | null>(null)
  const canEdit = data.canWrite && !preview
  const first = (month.getDay() + 6) % 7
  const days = Array.from({ length: 42 }, (_, k) => new Date(month.getFullYear(), month.getMonth(), k - first + 1))
  const byDay = useMemo(() => {
    const out: Record<string, PageRecord[]> = {}
    if (!dateField) return out
    for (const r of data.records) {
      const start = String(r[dateField.id] ?? '').slice(0, 10)
      if (!start) continue
      const stop = endField ? String(r[endField.id] ?? '').slice(0, 10) || start : start
      for (let d = new Date(`${start}T00:00:00`); ymd(d) <= stop && d.getTime() - Date.parse(`${start}T00:00:00`) < 62 * 86400000; d.setDate(d.getDate() + 1)) {
        (out[ymd(d)] ??= []).push(r)
      }
    }
    return out
  }, [data.records, dateField, endField])
  const label = month.toLocaleDateString(lang === 'en' ? 'en-GB' : 'fr-FR', { month: 'long', year: 'numeric' })
  const editingRec = data.records.find(r => r.rid === editing)
  const today = ymd(new Date())
  return (
    <div style={box}>
      <Title w={w} right={<div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
        <button type="button" className="btn ghost sm" onClick={() => setMonth(m => new Date(m.getFullYear(), m.getMonth() - 1, 1))}><ChevronLeft size={13} /></button>
        <span style={{ fontSize: 12, minWidth: 120, textAlign: 'center' }}>{label}</span>
        <button type="button" className="btn ghost sm" onClick={() => setMonth(m => new Date(m.getFullYear(), m.getMonth() + 1, 1))}><ChevronRight size={13} /></button>
      </div>} />
      {(adding || editingRec) && dateField && <div style={{ padding: 8 }}>
        <RecordForm fields={writable(fields)}
                    initial={editingRec ?? { [dateField.id]: dateField.type === 'datetime' ? `${adding}T09:00` : adding }}
                    onSave={v => { setAdding(null); setEditing(null); data.put(v, editingRec?.rid).catch(fail) }}
                    onCancel={() => { setAdding(null); setEditing(null) }} />
      </div>}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, minmax(0, 1fr))' }}>
        {(lang === 'en' ? DAYS_EN : DAYS_FR).map(d => <div key={d} className="cap" style={{ padding: '4px 6px', borderBottom: '1px solid var(--rule)' }}>{d}</div>)}
        {days.map(d => {
          const key = ymd(d)
          const items = byDay[key] ?? []
          const inMonth = d.getMonth() === month.getMonth()
          return (
            <div key={key} onDoubleClick={() => canEdit && setAdding(key)}
                 style={{ minHeight: 64, padding: 4, borderRight: '1px solid var(--rule)', borderBottom: '1px solid var(--rule)', opacity: inMonth ? 1 : 0.45, cursor: canEdit ? 'cell' : 'default' }}>
              <div className="cap" style={{ color: key === today ? 'var(--accent)' : 'var(--ink-4)', fontWeight: key === today ? 700 : 400 }}>{d.getDate()}</div>
              {items.slice(0, 3).map(r => (
                <div key={r.rid} onClick={() => canEdit && setEditing(r.rid)} title={`${fieldText(r, title)} (${r._by})`}
                     style={{ fontSize: 11, padding: '1px 4px', marginTop: 2, borderRadius: 3, background: 'var(--paper-2)', color: 'var(--ink-2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', cursor: 'pointer' }}>
                  {dateField?.type === 'datetime' && String(r[dateField.id] ?? '').slice(11, 16)} {fieldText(r, title)}
                </div>
              ))}
              {items.length > 3 && <div className="cap" style={{ color: 'var(--ink-4)' }}>+{items.length - 3}</div>}
            </div>
          )
        })}
      </div>
      {canEdit && <div className="tp-note" style={{ padding: '4px 8px', color: 'var(--ink-4)' }}>{tr('Double clic sur un jour : ajouter', 'Double click a day: add')}</div>}
      {data.error && <State data={data} preview={preview} empty="" />}
    </div>
  )
}

// -- members ------------------------------------------------------------------------------------------

// The artists of the pipeline (USER/ folders), alphabetical. Presence is gone (ADR 0091).

function Members({ widget: w }: DataWidgetProps) {
  const { tr } = useTr()
  const [users, setUsers] = useState<string[] | null>(null)
  const [me, setMe] = useState<string | null>(null)
  useEffect(() => {
    api.listUsers().then(r => setUsers(r.users)).catch(() => setUsers([]))
    flowsApi.getRights().then(r => setMe(r.user)).catch(() => setMe(null))
  }, [])
  const sorted = users ? [...users].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base', numeric: true })) : null
  return (
    // Capped like the feed: a big team scrolls inside the widget instead of stretching the page.
    <div style={{ ...box, display: 'flex', flexDirection: 'column', maxHeight: w.height ?? 380 }}>
      <Title w={w} right={users && <span className="cap">{users.length} {tr('artistes', 'artists')}</span>} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, padding: 8, flex: 1, minHeight: 0, overflowY: 'auto' }}>
        {users === null && <span className="tp-note" style={{ color: 'var(--ink-4)' }}>{tr('Chargement...', 'Loading...')}</span>}
        {sorted?.map(u => (
          <div key={u} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Avatar ch={u.slice(0, 1)} size={20} />
            <span style={{ fontSize: 12, color: 'var(--ink-2)', fontWeight: u === me ? 600 : undefined }}>{u}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// -- flow output source -----------------------------------------------------------------------------

// A table / cards / feed fed by the last run of a flow: shows the output as rows (read only).
function FlowOutput({ widget: w, project }: DataWidgetProps) {
  const { tr, lang } = useTr()
  const [run, setRun] = useState<{ summary: RunSummary; value: unknown } | null | undefined>(undefined)
  useEffect(() => {
    const src = w.source!
    let alive = true
    // Real runs only (T1): a dry run's outputs are simulated.
    flowsApi.listRuns({ flow: src.flow, status: 'ok', mode: 'real', limit: 1, project }).then(async list => {
      if (!list[0]) { if (alive) setRun(null); return }
      const rec = await flowsApi.getRun(list[0].run_id, project)
      const outputs = rec.outputs ?? {}
      if (alive) setRun({ summary: list[0], value: outputs[src.output ?? ''] })
    }).catch(() => { if (alive) setRun(null) })
    return () => { alive = false }
  }, [w.source, project])
  const rows = run?.value === undefined || run?.value === null ? [] : Array.isArray(run.value) ? run.value : [run.value]
  return (
    <div style={box}>
      <Title w={w} right={run && <span className="tp-note">{w.source?.flow} {ago(run.summary.ended, lang)}</span>} />
      <div style={{ padding: 8, display: 'flex', flexDirection: 'column', gap: 3 }}>
        {run === undefined && <span className="tp-note" style={{ color: 'var(--ink-4)' }}>{tr('Chargement...', 'Loading...')}</span>}
        {run === null && <span className="tp-note" style={{ color: 'var(--ink-4)' }}>{tr('Le flow n\'a pas encore tourne.', 'The flow has not run yet.')}</span>}
        {rows.map((v, k) => <div key={k} style={{ fontSize: 12, color: 'var(--ink-2)', wordBreak: 'break-all' }}>{typeof v === 'string' ? v : JSON.stringify(v)}</div>)}
      </div>
    </div>
  )
}

// -- entry ---------------------------------------------------------------------------------------------

export function DataWidget(props: DataWidgetProps) {
  const { widget: w } = props
  if (w.source?.flow) return <FlowOutput {...props} />
  switch (w.kind) {
    case 'feed': return <Feed {...props} />
    case 'table': return <Table {...props} />
    case 'cards': return <Cards {...props} />
    case 'calendar': return <Calendar {...props} />
    case 'members': return <Members {...props} />
    case 'chat': return <ChatWidget {...props} />
    case 'board': return <BoardWidget {...props} />
    default: return null
  }
}
