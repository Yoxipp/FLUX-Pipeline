// ParamsPane.tsx — right panel (03_EDITEUR §1): the selected node (header, doc, inputs with
// value or link, outputs), or the flow itself when nothing is selected. Read-only in P0.

import { FAMILY_INFO, familyHeaderBg } from './families'
import { iconFor } from './icons'
import { portColor } from './portTypes'
import type { FlowView, FlowViewNode, PortSpec } from './types'
import { formatValue, useTr } from './useTr'

export const PARAMS_W = 320

const title: React.CSSProperties = {
  fontSize: 10.5, fontWeight: 600, color: 'var(--ink-4)', textTransform: 'uppercase', letterSpacing: 0.4, margin: '12px 0 4px',
}

function PortLine({ p, input }: { p: PortSpec; input: boolean }) {
  const value = p.wiredFrom ? `<- ${p.wiredFrom}` : formatValue(p.value, 200)
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '10px 1fr', columnGap: 6, padding: '3px 0', borderBottom: '1px solid var(--rule)' }}>
      <span style={{ width: 8, height: 8, marginTop: 4, borderRadius: 2, background: portColor(p.type) }} />
      <div style={{ minWidth: 0 }}>
        <div style={{ display: 'flex', gap: 6, fontSize: 11.5 }}>
          <span style={{ color: 'var(--ink)' }}>{p.name}</span>
          <span style={{ color: 'var(--ink-4)' }}>{p.type}</span>
        </div>
        {input && value && (
          <div style={{ fontSize: 11, color: p.wiredFrom ? 'var(--ink-3)' : 'var(--ink-2)', wordBreak: 'break-all' }}>{value}</div>
        )}
      </div>
    </div>
  )
}

function NodeParams({ node }: { node: FlowViewNode }) {
  const { tr, lang } = useTr()
  const fam = FAMILY_INFO[node.family]
  const Icon = iconFor(node.icon, node.family)
  const doc = lang === 'en' ? node.doc_en || node.doc_fr : node.doc_fr || node.doc_en
  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 10px', margin: '-10px -12px 0', background: familyHeaderBg(node.family), borderBottom: '1px solid var(--rule)' }}>
        <Icon size={14} strokeWidth={1.75} color={fam.color} />
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)' }}>{node.label}</div>
          <div style={{ fontSize: 11, color: 'var(--ink-3)' }}>{node.type} · {lang === 'en' ? fam.en : fam.fr}</div>
        </div>
        {node.prefix && <span className="tag">{node.prefix}</span>}
      </div>
      {doc && <div style={{ fontSize: 11.5, color: 'var(--ink-2)', marginTop: 10, whiteSpace: 'pre-wrap' }}>{doc}</div>}
      {node.inputs.length > 0 && <div style={title}>{tr('Entrees', 'Inputs')}</div>}
      {node.inputs.map(p => <PortLine key={p.name} p={p} input />)}
      {node.outputs.length > 0 && <div style={title}>{tr('Sorties', 'Outputs')}</div>}
      {node.outputs.map(p => <PortLine key={p.name} p={p} input={false} />)}
      {node.meta && Object.keys(node.meta).length > 0 && <div style={title}>{tr('Origine v1', 'v1 origin')}</div>}
      {Object.entries(node.meta ?? {}).map(([k, v]) => (
        <div key={k} style={{ display: 'flex', gap: 6, fontSize: 11, padding: '2px 0' }}>
          <span style={{ color: 'var(--ink-4)', width: 64, flexShrink: 0 }}>{k}</span>
          <span style={{ color: 'var(--ink-2)', wordBreak: 'break-all', whiteSpace: 'pre-wrap' }}>{v}</span>
        </div>
      ))}
    </>
  )
}

function FlowParams({ view }: { view: FlowView }) {
  const { tr } = useTr()
  return (
    <>
      <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)' }}>{view.name}</div>
      <div style={{ fontSize: 11, color: 'var(--ink-3)', marginTop: 2 }}>
        {tr('Action v1, lecture seule', 'v1 action, read-only')}{view.origin === 'equipe' ? tr(' · copie equipe', ' · team copy') : ''}
      </div>
      {view.description && <div style={{ fontSize: 11.5, color: 'var(--ink-2)', marginTop: 10, whiteSpace: 'pre-wrap' }}>{view.description}</div>}
      <div style={title}>{tr('Contenu', 'Content')}</div>
      <div style={{ fontSize: 11.5, color: 'var(--ink-2)' }}>
        {view.nodes.length} nodes · {view.edges.filter(e => e.kind === 'exec').length} {tr('liens exec', 'exec links')} · {view.edges.filter(e => e.kind === 'data').length} {tr('liens data', 'data links')}
      </div>
      <div style={{ fontSize: 11, color: 'var(--ink-4)', marginTop: 12 }}>
        {tr('Clique un node pour voir ses parametres. Survole un port pour son type.', 'Click a node to see its parameters. Hover a port for its type.')}
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
        : <div style={{ fontSize: 11, color: 'var(--ink-4)' }}>{tr('Aucun flow charge', 'No flow loaded')}</div>}
    </aside>
  )
}
