// PageRunDialog.tsx — Run / Essai of a flow started by a TOOL page (T1, ADR 0068): pick the
// button whose branch runs and the values of the page fields (the page defaults, editable).
// POST /flows/{name}/run {button, values, event: the InputsPageReader node}. A flow without
// an InputsPageReader with buttons never opens it: Run / Essai launch at once.

import { useEffect, useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { FlaskConical, Play, X } from 'lucide-react'
import { flowsApi } from '../../api/flows'
import { Btn } from '../../components/shared/ui'
import type { FlowDoc } from './types'
import { useTr } from './useTr'

const PAGE_NODE = 'event.page_inputs'

export interface PageStart {
  node: string
  page: string
  buttons: { id: string; label: string }[]
  fields: { id: string; label: string; type: string }[]
}

export interface PageClick { event: string; button: string; values: Record<string, unknown> }

/** InputsPageReader nodes of the document that have at least one button (params.ports). */
export function pageStarts(doc: FlowDoc | null): PageStart[] {
  if (!doc) return []
  const out: PageStart[] = []
  for (const [node, n] of Object.entries(doc.nodes ?? {})) {
    if (n.type !== PAGE_NODE || n.bypass) continue
    const ports = (n.params?.ports ?? {}) as { outputs?: Record<string, string>; labels?: Record<string, string> }
    const outputs = ports.outputs ?? {}
    const label = (id: string) => ports.labels?.[id] || id
    const buttons = Object.entries(outputs).filter(([, t]) => t === 'exec').map(([id]) => ({ id, label: label(id) }))
    const fields = Object.entries(outputs).filter(([, t]) => t !== 'exec').map(([id, type]) => ({ id, label: label(id), type }))
    if (buttons.length) out.push({ node, page: String(n.params?.page ?? ''), buttons, fields })
  }
  return out
}

/** A field text typed in the dialog, as the type of its port (the page sends typed values). */
function typed(type: string, raw: unknown): unknown {
  if (type === 'bool') return !!raw
  if (typeof raw !== 'string') return raw
  if (type === 'int' || type === 'float') return raw.trim() === '' ? null : Number(raw)
  if (type.startsWith('list[')) return raw.split(',').map(s => s.trim()).filter(Boolean)
  return raw
}

function shown(raw: unknown): string {
  if (raw === null || raw === undefined) return ''
  return Array.isArray(raw) ? raw.join(', ') : String(raw)
}

export function PageRunDialog({ request, starts, project, onLaunch, onClose }: {
  request: { dry: boolean } | null
  starts: PageStart[]
  project?: string
  onLaunch: (dry: boolean, click: PageClick) => void
  onClose: () => void
}) {
  const { tr } = useTr()
  const [pick, setPick] = useState('')                 // `${node}|${button}`
  const [values, setValues] = useState<Record<string, unknown>>({})
  const [note, setNote] = useState<string | null>(null)
  const [node, button] = pick.split('|')
  const start = starts.find(s => s.node === node)

  // Opened: first button of the first page node.
  useEffect(() => {
    if (!request) return
    const first = starts[0]
    setPick(first ? `${first.node}|${first.buttons[0].id}` : '')
  }, [request, starts])

  // The page defaults of the node picked (read from the page file, as a click would get them).
  useEffect(() => {
    if (!request || !start) return
    let alive = true
    setNote(null)
    flowsApi.pagePorts(start.page, project)
      .then(p => { if (alive) setValues(Object.fromEntries(start.fields.map(f => [f.id, p.defaults[f.id] ?? '']))) })
      .catch((e: Error) => {
        if (!alive) return
        setValues(Object.fromEntries(start.fields.map(f => [f.id, ''])))
        setNote(e.message)
      })
    return () => { alive = false }
  }, [request, start, project])

  const launch = () => {
    if (!request || !start || !button) return
    const sent = Object.fromEntries(start.fields.map(f => [f.id, typed(f.type, values[f.id])]))
    onLaunch(request.dry, { event: start.node, button, values: sent })
    onClose()
  }

  return (
    <Dialog.Root open={!!request} onOpenChange={o => { if (!o) onClose() }}>
      <Dialog.Portal>
        <Dialog.Overlay className="flow-dialog-overlay" />
        <Dialog.Content className="flow-dialog" aria-describedby={undefined} style={{ width: 420 }}
                        onKeyDown={e => { if (e.key === 'Enter' && !(e.target instanceof HTMLTextAreaElement)) { e.preventDefault(); launch() } }}>
          <div className="flow-dialog-heading">
            <Dialog.Title>{request?.dry ? tr('Essai a blanc : quel bouton ?', 'Dry run: which button?') : tr('Run : quel bouton ?', 'Run: which button?')}</Dialog.Title>
            <Dialog.Close aria-label={tr('Fermer', 'Close')}><X size={15} /></Dialog.Close>
          </div>
          <div className="flow-dialog-hint">
            {tr('Le flow part comme si on cliquait ce bouton de la page, avec ces valeurs.',
                'The flow starts as if this page button were clicked, with these values.')}
          </div>

          <div className="flow-dialog-label">{tr('Bouton', 'Button')}</div>
          <select className="flow-dialog-input" value={pick} onChange={e => setPick(e.target.value)}>
            {starts.map(s => s.buttons.map(b => (
              <option key={`${s.node}|${b.id}`} value={`${s.node}|${b.id}`}>
                {starts.length > 1 ? `${s.page} > ` : ''}{b.label}
              </option>
            )))}
          </select>

          {start && start.fields.length > 0 && <div className="flow-dialog-label">{tr(`Champs de la page ${start.page}`, `Fields of the page ${start.page}`)}</div>}
          {start?.fields.map(f => (
            <label key={f.id} style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4, fontSize: 12, color: 'var(--ink-2)' }}>
              <span style={{ width: 130, flexShrink: 0, overflow: 'hidden', textOverflow: 'ellipsis' }} title={f.id}>{f.label}</span>
              {f.type === 'bool'
                ? <input type="checkbox" checked={!!values[f.id]} onChange={e => setValues(v => ({ ...v, [f.id]: e.target.checked }))} />
                : <input className="flow-dialog-input" style={{ flex: 1, marginTop: 0 }}
                         type={f.type === 'int' || f.type === 'float' ? 'number' : 'text'}
                         value={shown(values[f.id])} placeholder={f.type.startsWith('list[') ? tr('a, b, c', 'a, b, c') : f.type}
                         onChange={e => setValues(v => ({ ...v, [f.id]: e.target.value }))} />}
            </label>
          ))}
          {note && <div style={{ color: 'var(--warn)', fontSize: 11, marginTop: 6 }}>{tr('Defauts de la page illisibles : ', 'Page defaults unreadable: ')}{note}</div>}

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 6, marginTop: 12 }}>
            <Btn sm ghost onClick={onClose}>{tr('Annuler', 'Cancel')}</Btn>
            <Btn sm primary disabled={!start || !button} onClick={launch}>
              {request?.dry ? <FlaskConical size={12} /> : <Play size={12} />} {request?.dry ? tr('Lancer l\'essai', 'Run the dry run') : tr('Lancer', 'Run')}
            </Btn>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
