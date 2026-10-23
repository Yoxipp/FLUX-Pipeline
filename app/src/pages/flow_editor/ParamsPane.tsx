// ParamsPane.tsx — right panel (03_EDITEUR §1): the parameters of the selected node only
// (2026-10-22: doc and infos moved to the node hover toolbar). Nothing selected: the flow.
// P4: editable through the store (one undo entry per field, typing coalesced): label,
// bypass, every input / param of the spec with a ParamWidget by port type. A linked input
// shows its source, read-only. Nodes without a spec (legacy v1, unknown type) stay read-only.
// The flow part (interface, variables) is FlowSettings (FlowParams.tsx).

import type { ReactNode } from 'react'
import { ParamWidget, type ParamKind } from '../../components/shared/ParamWidget'
import { FAMILY_INFO } from './families'
import { portColor } from './portTypes'
import type { FlowViewNode, PortSpec } from './types'
import { formatValue, useTr } from './useTr'

export const PARAMS_W = 320

export function kindOf(type: string): ParamKind {
  if (type === 'bool' || type === 'int' || type === 'float' || type === 'path' || type === 'dir') return type
  if (type.startsWith('list[')) return 'list'
  if (type === 'dict') return 'text'
  return 'str'
}

// Widget value -> stored value: numbers parsed, empty = unset (the default applies).
export function storedValue(type: string, raw: unknown): unknown {
  if (raw === '' || (Array.isArray(raw) && raw.length === 0)) return undefined
  if ((type === 'int' || type === 'float') && typeof raw === 'string') {
    const n = Number(raw)
    return Number.isFinite(n) ? (type === 'int' ? Math.trunc(n) : n) : raw
  }
  if (type === 'dict' && typeof raw === 'string') {
    try { return JSON.parse(raw) } catch { return raw }
  }
  return raw
}

function Label({ p }: { p: PortSpec }) {
  return (
    <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11.5, color: 'var(--ink-2)', minWidth: 0 }}>
      <span style={{ width: 7, height: 7, borderRadius: 2, background: portColor(p.type), flexShrink: 0 }} />
      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={`${p.name} : ${p.type}`}>{p.name}</span>
      {p.required && <span style={{ color: 'var(--accent)' }}>*</span>}
    </span>
  )
}

export function Row({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '110px 1fr', columnGap: 8, alignItems: 'center', padding: '4px 0', borderBottom: '1px solid var(--rule)' }}>
      {label}
      <div style={{ display: 'flex', minWidth: 0 }}>{children}</div>
    </div>
  )
}

function ParamRow({ p, editable, raw, onChange }: { p: PortSpec; editable: boolean; raw: unknown; onChange: (v: unknown) => void }) {
  const { tr, lang } = useTr()
  const doc = lang === 'en' ? p.doc_en || p.doc_fr : p.doc_fr || p.doc_en
  if (p.wiredFrom || !editable) {
    const value = p.wiredFrom ? `<- ${p.wiredFrom}` : formatValue(p.value, 400)
    return (
      <Row label={<Label p={p} />}>
        <span style={{
          flex: 1, fontSize: 11.5, padding: '3px 6px', borderRadius: 4, minHeight: 22, wordBreak: 'break-all',
          background: p.wiredFrom ? 'transparent' : 'var(--paper-2)', border: '1px solid var(--rule-2)',
          color: p.wiredFrom ? 'var(--ink-4)' : 'var(--ink)',
        }}>
          {value || <span style={{ color: 'var(--ink-4)' }}>{tr('(vide)', '(empty)')}</span>}
        </span>
      </Row>
    )
  }
  const kind = kindOf(p.type)
  const shown = p.type === 'dict' && raw !== undefined && typeof raw !== 'string' ? JSON.stringify(raw) : raw
  return (
    <Row label={<Label p={p} />}>
      <ParamWidget kind={kind} value={shown} tip={doc} placeholder={p.example ?? (raw === undefined && p.value !== undefined ? formatValue(p.value, 60) : undefined)}
                   onChange={v => onChange(storedValue(p.type, v))} />
    </Row>
  )
}

export interface NodeEdits {
  onParam: (id: string, name: string, value: unknown) => void
  onFields: (id: string, patch: { label?: string; bypass?: boolean }) => void
}

function NodeParams({ node, params, editable, edits }: { node: FlowViewNode; params: Record<string, unknown>; editable: boolean; edits: NodeEdits }) {
  const { tr } = useTr()
  const fam = FAMILY_INFO[node.family]
  const canEdit = editable && !!node.spec
  const ports = node.inputs.filter(p => p.type !== 'exec')
  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span style={{ width: 10, height: 10, borderRadius: 3, background: fam.color }} />
        <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)' }}>{node.spec?.label ?? node.label}</span>
        <span className="tag">{node.id}</span>
      </div>
      {canEdit && (
        <>
          <Row label={<span style={{ fontSize: 11.5, color: 'var(--ink-3)' }}>{tr('Libelle', 'Label')}</span>}>
            <ParamWidget kind="str" value={node.meta?.step ?? ''} placeholder={node.spec?.label}
                         onChange={v => edits.onFields(node.id, { label: String(v) })} />
          </Row>
          <Row label={<span style={{ fontSize: 11.5, color: 'var(--ink-3)' }}>Bypass</span>}>
            <ParamWidget kind="bool" value={node.meta?.bypass === 'true'} tip={tr('Le node est saute au run', 'The node is skipped at run time')}
                         onChange={v => edits.onFields(node.id, { bypass: Boolean(v) })} />
          </Row>
        </>
      )}
      {!node.spec && (
        <div style={{ fontSize: 11, color: 'var(--ink-4)', margin: '4px 0 8px' }}>
          {tr('Node sans entree au catalogue (v1 migre ou type inconnu) : lecture seule.', 'Node without a catalogue entry (migrated v1 or unknown type): read-only.')}
        </div>
      )}
      {ports.length === 0
        ? <div style={{ fontSize: 11, color: 'var(--ink-4)', marginTop: 6 }}>{tr('Ce node n\'a pas de parametre.', 'This node has no parameter.')}</div>
        : ports.map(p => (
            <ParamRow key={p.name} p={p} editable={canEdit} raw={params[p.name]}
                      onChange={v => edits.onParam(node.id, p.name, v)} />
          ))}
    </>
  )
}

export function ParamsPane({ selected, params, editable, edits, flowPart }: {
  selected: FlowViewNode | null
  params: Record<string, unknown>          // params of the selected node in the document
  editable: boolean
  edits: NodeEdits
  flowPart: ReactNode                      // shown when no node is selected
}) {
  return (
    <aside style={{ width: PARAMS_W, flexShrink: 0, borderLeft: '1px solid var(--rule)', background: 'var(--paper)', overflowY: 'auto', padding: '10px 12px' }}>
      {selected ? <NodeParams node={selected} params={params} editable={editable} edits={edits} /> : flowPart}
    </aside>
  )
}
