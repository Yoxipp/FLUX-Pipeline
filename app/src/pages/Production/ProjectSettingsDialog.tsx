// ProjectSettingsDialog - advanced settings of a project, shown right after its creation.
// The form is generated from project.json and its schema (backend PROJECT_SCHEMA): every
// property shows up with its "title", except those flagged "x-flux-hidden". A key present
// in project.json but missing from the schema still shows up, its field inferred from the
// value. The values start on the project defaults; "Passer" keeps them untouched.

import { useEffect, useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { api } from '../../api/client'

type Schema = {
  type?: string
  enum?: unknown[]
  title?: string
  properties?: Record<string, Schema>
  items?: Schema
  minItems?: number
  maxItems?: number
  additionalProperties?: Schema | boolean
  'x-flux-hidden'?: boolean
}
type Json = Record<string, unknown>

const isObject = (v: unknown): v is Json => typeof v === 'object' && v !== null && !Array.isArray(v)

// Schema of a value the backend schema does not describe yet.
function inferSchema(value: unknown): Schema {
  if (typeof value === 'number') return { type: 'number' }
  if (typeof value === 'boolean') return { type: 'boolean' }
  if (typeof value === 'string') return { type: 'string' }
  if (Array.isArray(value)) return { type: 'array', items: value.length && typeof value[0] === 'number' ? { type: 'number' } : { type: 'string' } }
  if (isObject(value)) return { type: 'object', properties: Object.fromEntries(Object.entries(value).map(([k, v]) => [k, inferSchema(v)])) }
  return {}
}

// Visible keys of an object: the schema ones first (in their order), then the unknown ones.
function visibleKeys(schema: Schema, value: Json): string[] {
  const props = schema.properties ?? {}
  const keys = [...Object.keys(props), ...Object.keys(value).filter(k => !(k in props))]
  return keys.filter(k => !props[k]?.['x-flux-hidden'])
}

const label = (key: string, schema: Schema) => schema.title ?? key.replace(/_/g, ' ')

// Text field committed on blur (lists and KEY=VALUE maps would lose a half-typed entry otherwise).
function BlurText({ value, onCommit, multiline, placeholder }: { value: string; onCommit: (text: string) => void; multiline?: boolean; placeholder?: string }) {
  const [text, setText] = useState(value)
  useEffect(() => setText(value), [value])
  return multiline
    ? <textarea value={text} placeholder={placeholder} rows={3} onChange={e => setText(e.target.value)} onBlur={() => onCommit(text)} />
    : <input value={text} placeholder={placeholder} onChange={e => setText(e.target.value)} onBlur={() => onCommit(text)} />
}

function Field({ name, schema, value, onChange }: { name: string; schema: Schema; value: unknown; onChange: (v: unknown) => void }) {
  const s = Object.keys(schema).length ? schema : inferSchema(value)
  const title = label(name, s)
  if (s.enum) {
    return <label>{title}<select value={String(value ?? '')} onChange={e => onChange(s.enum!.find(o => String(o) === e.target.value))}>
      {s.enum.map(o => <option key={String(o)} value={String(o)}>{String(o)}</option>)}
    </select></label>
  }
  if (s.type === 'boolean') {
    return <label className="project-settings-check"><input type="checkbox" checked={Boolean(value)} onChange={e => onChange(e.target.checked)} />{title}</label>
  }
  if (s.type === 'number' || s.type === 'integer') {
    return <label>{title}<input type="number" step={s.type === 'integer' ? 1 : 'any'} value={value === undefined || value === null ? '' : String(value)}
      onChange={e => onChange(e.target.value === '' ? null : Number(e.target.value))} /></label>
  }
  if (s.type === 'string') {
    return <label>{title}<input value={String(value ?? '')} onChange={e => onChange(e.target.value)} /></label>
  }
  if (s.type === 'array') {
    const list = Array.isArray(value) ? value : []
    const numeric = s.items?.type === 'number' || s.items?.type === 'integer'
    // Fixed size numeric tuple (resolution): one field per item.
    if (numeric && s.minItems && s.minItems === s.maxItems) {
      return <label>{title}<div className="project-settings-tuple">{Array.from({ length: s.minItems }, (_, i) =>
        <input key={i} type="number" step={s.items?.type === 'integer' ? 1 : 'any'} value={list[i] === undefined || list[i] === null ? '' : String(list[i])}
          onChange={e => { const next = [...list]; next[i] = e.target.value === '' ? null : Number(e.target.value); onChange(next) }} />)}
      </div></label>
    }
    if (!s.items || ['string', 'number', 'integer'].includes(s.items.type ?? '')) {
      return <label>{title}<BlurText value={list.join(', ')} placeholder="valeur, valeur" onCommit={text => {
        const items = text.split(',').map(t => t.trim()).filter(Boolean)
        onChange(numeric ? items.map(Number) : items)
      }} /></label>
    }
  }
  if (s.type === 'object' && s.properties) {
    const obj = isObject(value) ? value : {}
    const keys = visibleKeys(s, obj)
    if (!keys.length) return null
    return <fieldset className="project-settings-group"><legend>{title}</legend>
      {keys.map(k => <Field key={k} name={k} schema={s.properties?.[k] ?? {}} value={obj[k]} onChange={v => onChange({ ...obj, [k]: v })} />)}
    </fieldset>
  }
  if (s.type === 'object' && isObject(s.additionalProperties) && s.additionalProperties.type === 'string') {
    const obj = isObject(value) ? value : {}
    return <label>{title}<BlurText multiline placeholder="CLE=valeur (une par ligne)" value={Object.entries(obj).map(([k, v]) => `${k}=${String(v)}`).join('\n')}
      onCommit={text => onChange(Object.fromEntries(text.split('\n').map(l => l.trim()).filter(l => l.includes('=')).map(l => {
        const at = l.indexOf('='); return [l.slice(0, at).trim(), l.slice(at + 1).trim()]
      }).filter(([k]) => k)))} /></label>
  }
  // Any other shape: raw JSON, so a future option is never invisible.
  return <label>{title}<BlurText multiline value={JSON.stringify(value ?? null, null, 2)} onCommit={text => {
    try { onChange(JSON.parse(text)) } catch { /* invalid JSON: keep the previous value */ }
  }} /></label>
}

// onClose: settings kept (Enregistrer / Passer). onCancel: the cross or Escape, the caller
// cancels the creation.
export function ProjectSettingsDialog({ project, onClose, onCancel }: { project: string; onClose: () => void; onCancel: () => Promise<void> }) {
  const [schema, setSchema] = useState<Schema | null>(null)
  const [draft, setDraft] = useState<Json>({})
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    api.getProjectConfig(project)
      .then(r => { setSchema(r.schema as Schema); setDraft(r.config) })
      .catch(e => setError(e instanceof Error ? e.message : String(e)))
  }, [project])
  const keys = schema ? visibleKeys(schema, draft) : []
  const save = async () => {
    setBusy(true); setError('')
    try {
      await api.putProjectConfig(project, Object.fromEntries(keys.map(k => [k, draft[k]])))
      onClose()
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) }
  }
  const cancel = async () => {
    setBusy(true); setError('')
    try { await onCancel() } catch (e) { setError(e instanceof Error ? e.message : String(e)); setBusy(false) }
  }
  return (
    <Dialog.Root open onOpenChange={open => { if (!open && !busy) void cancel() }}><Dialog.Portal><Dialog.Overlay className="production-dialog-overlay" /><Dialog.Content className="production-dialog project-settings-dialog"
      onPointerDownOutside={e => e.preventDefault()}>
      <div className="production-dialog-heading"><Dialog.Title>Paramètres avancés · {project}</Dialog.Title><Dialog.Close disabled={busy} aria-label="Annuler la création du projet" title="Annuler la création du projet"><X size={16} /></Dialog.Close></div>
      <Dialog.Description>Valeurs par défaut du projet. Modifiez ce qui doit changer ou passez pour les garder.</Dialog.Description>
      <div className="project-settings-form">
        {!schema && !error && <span style={{ color: 'var(--ink-3)' }}>Chargement...</span>}
        {keys.map(k => <Field key={k} name={k} schema={schema?.properties?.[k] ?? {}} value={draft[k]} onChange={v => setDraft(prev => ({ ...prev, [k]: v }))} />)}
      </div>
      {error && <div role="alert" style={{ marginTop: 10 }}>{error}</div>}
      <div className="project-settings-actions">
        <button className="btn primary" disabled={busy || !schema} onClick={() => void save()}>Enregistrer</button>
        <button disabled={busy} onClick={onClose}>Passer</button>
      </div>
    </Dialog.Content></Dialog.Portal></Dialog.Root>
  )
}
