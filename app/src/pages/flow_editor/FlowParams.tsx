// FlowParams.tsx — Params pane when no node is selected (03_EDITEUR §1): the flow itself.
// P4: label, description, run policy, interface (inputs asked at run time: form, event
// payload; outputs returned by a sub-flow) and variables (read with GetVariable / ${name},
// written by SetVariable). Each edit = one undo entry (typing coalesced per field).
// Ids are checked by the backend validation (model.py FIELD_ID_RE); here only typed.

import type { ReactNode } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { ParamWidget } from '../../components/shared/ParamWidget'
import { Row, kindOf, storedValue } from './ParamsPane'
import { INTERFACE_TYPES, type FlowDoc, type FlowInterface, type FlowVariable, type InterfaceInput, type InterfaceOutput } from './types'
import { useTr } from './useTr'

const VARIABLE_TYPES = ['str', 'int', 'float', 'bool', 'path', 'dir', 'list[str]', 'list[path]', 'dict', 'any']
const OUTPUT_TYPES = [...VARIABLE_TYPES, 'publish', 'pattern']

const cap = (text: string) => <span style={{ fontSize: 11.5, color: 'var(--ink-3)' }}>{text}</span>
const small: React.CSSProperties = { fontSize: 11.5, height: 24, padding: '0 6px', minWidth: 0, background: 'var(--bg-deep)', border: '1px solid var(--rule-2)', borderRadius: 5, color: 'var(--ink)' }

function Section({ title, onAdd, disabled, children }: { title: string; onAdd: () => void; disabled: boolean; children: ReactNode }) {
  const { tr } = useTr()
  return (
    <div style={{ marginTop: 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
        <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--ink-2)', textTransform: 'uppercase', letterSpacing: 0.4, flex: 1 }}>{title}</span>
        <button type="button" className="flow-tool" disabled={disabled} onClick={onAdd} title={tr('Ajouter', 'Add')}><Plus size={12} /></button>
      </div>
      {children}
    </div>
  )
}

function Item({ id, type, types, disabled, onId, onType, onRemove, children }: {
  id: string; type: string; types: readonly string[]; disabled: boolean
  onId: (v: string) => void; onType: (v: string) => void; onRemove: () => void; children?: ReactNode
}) {
  const { tr } = useTr()
  return (
    <div style={{ padding: '5px 0', borderBottom: '1px solid var(--rule)', display: 'flex', flexDirection: 'column', gap: 4 }}>
      <div style={{ display: 'flex', gap: 4 }}>
        <input value={id} disabled={disabled} onChange={e => onId(e.target.value)} style={{ ...small, flex: 1, fontFamily: 'var(--mono)' }} placeholder="id" />
        <select value={type} disabled={disabled} onChange={e => onType(e.target.value)} style={{ ...small, width: 96 }}>
          {!types.includes(type) && <option value={type}>{type}</option>}
          {types.map(t => <option key={t} value={t}>{t}</option>)}
        </select>
        <button type="button" className="flow-tool" disabled={disabled} onClick={onRemove} title={tr('Supprimer', 'Remove')}><Trash2 size={12} /></button>
      </div>
      {children}
    </div>
  )
}

const freeId = (taken: string[], base: string) => {
  for (let i = 1; ; i++) if (!taken.includes(`${base}${i}`)) return `${base}${i}`
}

export function FlowParams({ doc, editable, onFields }: {
  doc: FlowDoc | null
  editable: boolean
  onFields: (patch: Partial<FlowDoc>, key: string) => void
}) {
  const { tr } = useTr()
  if (!doc) return <div style={{ fontSize: 11, color: 'var(--ink-4)' }}>{tr('Aucun flow ouvert', 'No flow open')}</div>
  const off = !editable
  const iface: FlowInterface = { inputs: doc.interface?.inputs ?? [], outputs: doc.interface?.outputs ?? [] }
  const vars = doc.variables ?? []

  const setIface = (next: FlowInterface, key: string) =>
    onFields({ interface: next.inputs.length || next.outputs.length ? next : undefined }, key)
  const setInput = (i: number, patch: Partial<InterfaceInput>, key: string) => {
    const cur = { ...iface.inputs[i], ...patch }
    if (patch.type !== undefined) {
      if (patch.type === 'select') cur.options = cur.options ?? []
      else delete cur.options
      delete cur.default
    }
    setIface({ ...iface, inputs: iface.inputs.map((x, k) => k === i ? cur : x) }, key)
  }
  const setOutput = (i: number, patch: Partial<InterfaceOutput>, key: string) =>
    setIface({ ...iface, outputs: iface.outputs.map((x, k) => k === i ? { ...x, ...patch } : x) }, key)
  const setVar = (i: number, patch: Partial<FlowVariable>, key: string) => {
    const next = vars.map((x, k) => k === i ? { ...x, ...patch, ...(patch.type ? { default: undefined } : {}) } : x)
    onFields({ variables: next.length ? next : undefined }, key)
  }

  return (
    <>
      <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)', marginBottom: 8 }}>{doc.name}</div>
      <Row label={cap(tr('Libelle', 'Label'))}>
        <ParamWidget kind="str" value={doc.label ?? ''} disabled={off}
                     onChange={v => onFields({ label: String(v) || undefined }, 'flow:label')} />
      </Row>
      <Row label={cap('Description')}>
        <ParamWidget kind="text" value={doc.description ?? ''} disabled={off}
                     onChange={v => onFields({ description: String(v) || undefined }, 'flow:description')} />
      </Row>
      <Row label={cap(tr('Si deja en cours', 'If already running'))}>
        <ParamWidget kind="select" value={doc.run_policy ?? 'skip_if_running'} options={['skip_if_running', 'queue']} disabled={off}
                     onChange={v => onFields({ run_policy: v as FlowDoc['run_policy'] }, 'flow:run_policy')} />
      </Row>

      <Section title={tr('Entrees (interface)', 'Inputs (interface)')} disabled={off}
               onAdd={() => setIface({ ...iface, inputs: [...iface.inputs, { id: freeId(iface.inputs.map(x => x.id), 'input'), type: 'str' }] }, 'iface:add')}>
        {iface.inputs.length === 0 && <div style={{ fontSize: 11, color: 'var(--ink-4)' }}>{tr('Aucune : le Run ne demande rien.', 'None: Run asks for nothing.')}</div>}
        {iface.inputs.map((inp, i) => (
          <Item key={i} id={inp.id} type={inp.type} types={INTERFACE_TYPES} disabled={off}
                onId={v => setInput(i, { id: v }, `iface:in:${i}:id`)} onType={v => setInput(i, { type: v }, `iface:in:${i}:type`)}
                onRemove={() => setIface({ ...iface, inputs: iface.inputs.filter((_, k) => k !== i) }, `iface:in:${i}:rm`)}>
            <div style={{ display: 'flex', gap: 4 }}>
              <input value={inp.label ?? ''} disabled={off} placeholder={tr('Libelle', 'Label')} style={{ ...small, flex: 1 }}
                     onChange={e => setInput(i, { label: e.target.value || undefined }, `iface:in:${i}:label`)} />
            </div>
            {inp.type === 'select' && (
              <input value={(inp.options ?? []).join(', ')} disabled={off} placeholder={tr('Choix, separes par des virgules', 'Choices, comma separated')} style={small}
                     onChange={e => setInput(i, { options: e.target.value.split(',').map(s => s.trim()).filter(Boolean) }, `iface:in:${i}:options`)} />
            )}
            <div style={{ display: 'flex' }}>
              <ParamWidget kind={inp.type === 'select' ? 'select' : kindOf(inp.type)} options={(inp.options ?? []).map(String)}
                           value={inp.default} disabled={off} placeholder={tr('Defaut', 'Default')}
                           onChange={v => setInput(i, { default: storedValue(inp.type, v) }, `iface:in:${i}:default`)} />
            </div>
          </Item>
        ))}
      </Section>

      <Section title={tr('Sorties (sous-flow)', 'Outputs (sub-flow)')} disabled={off}
               onAdd={() => setIface({ ...iface, outputs: [...iface.outputs, { id: freeId(iface.outputs.map(x => x.id), 'output'), type: 'str' }] }, 'iface:addout')}>
        {iface.outputs.length === 0 && <div style={{ fontSize: 11, color: 'var(--ink-4)' }}>{tr('Aucune.', 'None.')}</div>}
        {iface.outputs.map((out, i) => (
          <Item key={i} id={out.id} type={out.type} types={OUTPUT_TYPES} disabled={off}
                onId={v => setOutput(i, { id: v }, `iface:out:${i}:id`)} onType={v => setOutput(i, { type: v }, `iface:out:${i}:type`)}
                onRemove={() => setIface({ ...iface, outputs: iface.outputs.filter((_, k) => k !== i) }, `iface:out:${i}:rm`)}>
            <input value={out.label ?? ''} disabled={off} placeholder={tr('Libelle', 'Label')} style={small}
                   onChange={e => setOutput(i, { label: e.target.value || undefined }, `iface:out:${i}:label`)} />
          </Item>
        ))}
      </Section>

      <Section title={tr('Variables', 'Variables')} disabled={off}
               onAdd={() => onFields({ variables: [...vars, { name: freeId(vars.map(v => v.name), 'var'), type: 'str' }] }, 'vars:add')}>
        {vars.length === 0 && <div style={{ fontSize: 11, color: 'var(--ink-4)' }}>{tr('Aucune. Lues par GetVariable ou ${nom}, ecrites par SetVariable.', 'None. Read by GetVariable or ${name}, written by SetVariable.')}</div>}
        {vars.map((v, i) => (
          <Item key={i} id={v.name} type={v.type} types={VARIABLE_TYPES} disabled={off}
                onId={x => setVar(i, { name: x }, `vars:${i}:name`)} onType={x => setVar(i, { type: x }, `vars:${i}:type`)}
                onRemove={() => { const next = vars.filter((_, k) => k !== i); onFields({ variables: next.length ? next : undefined }, `vars:${i}:rm`) }}>
            <div style={{ display: 'flex' }}>
              <ParamWidget kind={kindOf(v.type)} value={v.default} disabled={off} placeholder={tr('Valeur initiale', 'Initial value')}
                           onChange={x => setVar(i, { default: storedValue(v.type, x) }, `vars:${i}:default`)} />
            </div>
          </Item>
        ))}
      </Section>
    </>
  )
}
