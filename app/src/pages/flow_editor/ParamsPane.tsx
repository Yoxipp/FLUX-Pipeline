// ParamsPane.tsx — right panel (03_EDITEUR §1): the parameters of the selected node only
// (2026-10-22: doc and infos moved to the node hover toolbar). Nothing selected: the flow.
// Read-only in P0.

import { FAMILY_INFO } from './families'
import { portColor } from './portTypes'
import type { FlowView, FlowViewNode, PortSpec } from './types'
import { formatValue, useTr } from './useTr'

export const PARAMS_W = 320

function ParamRow({ p }: { p: PortSpec }) {
  const { tr } = useTr()
  const value = p.wiredFrom ? `<- ${p.wiredFrom}` : formatValue(p.value, 400)
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '110px 1fr', columnGap: 8, alignItems: 'start', padding: '5px 0', borderBottom: '1px solid var(--rule)' }}>
      <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11.5, color: 'var(--ink-2)', minWidth: 0 }}>
        <span style={{ width: 7, height: 7, borderRadius: 2, background: portColor(p.type), flexShrink: 0 }} />
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={`${p.name} : ${p.type}`}>{p.name}</span>
      </span>
      <span style={{
        fontSize: 11.5, padding: '3px 6px', borderRadius: 4, minHeight: 22, wordBreak: 'break-all',
        background: p.wiredFrom ? 'transparent' : 'var(--paper-2)', border: '1px solid var(--rule-2)',
        color: p.wiredFrom ? 'var(--ink-4)' : 'var(--ink)',
      }}>
        {value || <span style={{ color: 'var(--ink-4)' }}>{tr('(vide)', '(empty)')}</span>}
      </span>
    </div>
  )
}

function NodeParams({ node }: { node: FlowViewNode }) {
  const { tr } = useTr()
  const fam = FAMILY_INFO[node.family]
  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span style={{ width: 10, height: 10, borderRadius: 3, background: fam.color }} />
        <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)' }}>{node.label}</span>
      </div>
      {node.inputs.length === 0
        ? <div style={{ fontSize: 11, color: 'var(--ink-4)' }}>{tr('Ce node n\'a pas de parametre.', 'This node has no parameter.')}</div>
        : node.inputs.map(p => <ParamRow key={p.name} p={p} />)}
    </>
  )
}

function FlowParams({ view }: { view: FlowView }) {
  const { tr } = useTr()
  return (
    <>
      <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)' }}>{view.name}</div>
      {view.description && <div style={{ fontSize: 11.5, color: 'var(--ink-2)', marginTop: 8, whiteSpace: 'pre-wrap' }}>{view.description}</div>}
      <div style={{ fontSize: 11, color: 'var(--ink-4)', marginTop: 12 }}>
        {tr('Clique un node pour ses parametres. Survole un node pour ses infos, un port pour son type.', 'Click a node for its parameters. Hover a node for its info, a port for its type.')}
      </div>
    </>
  )
}

export function ParamsPane({ view, selected }: { view: FlowView | null; selected: FlowViewNode | null }) {
  const { tr } = useTr()
  return (
    <aside style={{ width: PARAMS_W, flexShrink: 0, borderLeft: '1px solid var(--rule)', background: 'var(--paper)', overflowY: 'auto', padding: '10px 12px' }}>
      {selected ? <NodeParams node={selected} />
        : view ? <FlowParams view={view} />
        : <div style={{ fontSize: 11, color: 'var(--ink-4)' }}>{tr('Aucun flow ouvert', 'No flow open')}</div>}
    </aside>
  )
}
