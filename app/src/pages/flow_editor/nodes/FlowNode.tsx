// FlowNode.tsx — a node of the Flows editor (03_EDITEUR §3): name band in the family colour
// (2026-10-22), icon, DCC prefix badge, exec row on top, one 20 px row per data port
// (port names only, 2026-10-23). Hover shows a small toolbar like Houdini: bypass, info.
// P2: run state of the node (03_EDITEUR §7): running = accent border + spinning loader, ok =
// check + count, error = --err border + message (values received in the tooltip),
// error_handled = --warn border, skipped / cancelled = dashed border.
// P4: issue badge (count, --err or --warn) in the header, red ring on the faulty ports,
// one blink when zoomed from the Problems panel.
// (i) shows the node's section of docs/flows/03_INDEX_NODES.md (nodeDoc.tsx), else the registry doc,
// then every current value (2026-10-23): Inputs (literal value or "<- node.port", plus the
// value received in the run when known) and Outputs (last value of the run when known).
// P6a: a DCC node shipped as a locked subflow shows a lock (shipped) or a team tag (its team
// copy); double click enters it (NetworkPane), like a Houdini HDA (03_EDITEUR §8).

import { memo, useRef, useState } from 'react'
import { NodeToolbar, Position, type Node, type NodeProps } from '@xyflow/react'
import { Ban, CircleCheck, CircleX, Info, LoaderCircle, Lock, Users } from 'lucide-react'
import { FAMILY_INFO } from '../families'
import { NodeDocText, nodeDocSection } from '../nodeDoc'
import { iconFor } from '../icons'
import type { FlowViewNode, NodeRunInfo, PortSpec } from '../types'
import { formatValue, useTr } from '../useTr'
import { PortHandle, handleId } from './PortHandle'
import '../flow_editor.css'

export const NODE_W = 240
const HEADER_H = 28
const ROW_H = 20
const VALUE_MAX = 80
const HIDE_MS = 250   // time to reach the toolbar before it hides

export interface NodeIssues { errors: number; warnings: number; ports: string[] }
// Run values per port (RunRecord.links / link_value, else NodeRunInfo.values), for the info card.
export interface PortRunValues { in: Record<string, string>; out: Record<string, string> }
export type FlowNodeData = { node: FlowViewNode; linked: string[]; dim: boolean; run?: NodeRunInfo; issues?: NodeIssues; flash?: number; io?: PortRunValues }
export type FlowRfNode = Node<FlowNodeData, 'flow'>

const EXEC_IN: PortSpec = { name: 'exec', type: 'exec' }
const EXEC_OUT: PortSpec = { name: 'then', type: 'exec' }

function Row({ left, right, linked, faulty }: { left?: PortSpec; right?: PortSpec; linked: Set<string>; faulty: Set<string> }) {
  return (
    <div style={{ position: 'relative', height: ROW_H, display: 'flex', alignItems: 'center', gap: 6, padding: '0 10px', fontSize: 11 }}>
      {left && <PortHandle port={left} side="in" linked={linked.has(handleId('in', left.name))} faulty={faulty.has(left.name)} />}
      {left && <span style={{ color: 'var(--ink-2)', minWidth: 0, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{left.name}</span>}
      {!left && <span style={{ flex: 1 }} />}
      {right && <span style={{ color: 'var(--ink-2)', whiteSpace: 'nowrap' }}>{right.name}</span>}
      {right && <PortHandle port={right} side="out" linked={linked.has(handleId('out', right.name))} faulty={faulty.has(right.name)} />}
    </div>
  )
}

function ValueLine({ port, value, run }: { port: PortSpec; value?: string; run?: string }) {
  const { tr } = useTr()
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '92px 1fr', columnGap: 6, fontSize: 11, marginTop: 3 }}>
      <span style={{ color: 'var(--ink-2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={port.name}>{port.name}</span>
      <span style={{ minWidth: 0, wordBreak: 'break-all', whiteSpace: 'pre-wrap' }}>
        <span style={{ color: 'var(--ink-4)' }}>{port.type}</span>
        {value !== undefined && <span style={{ color: value ? 'var(--ink)' : 'var(--ink-4)' }}>{'  '}{value || tr('(vide)', '(empty)')}</span>}
        {run !== undefined && <span style={{ display: 'block', color: 'var(--ink-3)' }}>run : {run}</span>}
      </span>
    </div>
  )
}

function InfoCard({ node, io, run }: { node: FlowViewNode; io?: PortRunValues; run?: NodeRunInfo }) {
  const { tr, lang } = useTr()
  const fam = FAMILY_INFO[node.family]
  const section = nodeDocSection(node.type)
  const doc = lang === 'en' ? node.doc_en || node.doc_fr : node.doc_fr || node.doc_en
  const ins = [...node.inputs, ...(node.constants ?? [])].filter(p => p.type !== 'exec')
  const outs = node.outputs.filter(p => p.type !== 'exec')
  const head: React.CSSProperties = { fontSize: 10.5, fontWeight: 600, color: 'var(--ink-4)', textTransform: 'uppercase', letterSpacing: 0.4,
                                      marginTop: 8, paddingTop: 6, borderTop: '1px solid var(--rule)' }
  return (
    <div className="nowheel" style={{
      width: 340, maxHeight: 560, overflowY: 'auto', marginTop: 4, padding: '8px 10px', background: 'var(--paper)', border: '1px solid var(--rule-2)',
      borderRadius: 6, boxShadow: 'var(--shadow)', fontSize: 11.5, color: 'var(--ink-2)',
    }}>
      <div style={{ fontWeight: 600, color: 'var(--ink)' }}>{node.label}</div>
      <div style={{ fontSize: 11, color: 'var(--ink-4)', marginBottom: 6 }}>{node.type} · {lang === 'en' ? fam.en : fam.fr}</div>
      {section
        ? <div style={{ maxHeight: 320, overflowY: 'auto' }}><NodeDocText text={section} /></div>
        : <div style={{ whiteSpace: 'pre-wrap', maxHeight: 220, overflowY: 'auto' }}>{doc || tr('Pas de documentation.', 'No documentation.')}</div>}
      {Object.entries(node.meta ?? {}).map(([k, v]) => (
        <div key={k} style={{ display: 'flex', gap: 6, fontSize: 11, marginTop: 3 }}>
          <span style={{ color: 'var(--ink-4)', width: 56, flexShrink: 0 }}>{k}</span>
          <span style={{ wordBreak: 'break-all', whiteSpace: 'pre-wrap' }}>{v}</span>
        </div>
      ))}
      {ins.length > 0 && <div style={head}>{tr('Entrees', 'Inputs')}</div>}
      {ins.map(p => (
        <ValueLine key={p.name} port={p}
                   value={p.wiredFrom ? `<- ${p.wiredFrom}` : formatValue(p.value, VALUE_MAX)}
                   run={io?.in[p.name] ?? run?.values?.[p.name]} />
      ))}
      {outs.length > 0 && <div style={head}>{tr('Sorties', 'Outputs')}</div>}
      {outs.map(p => <ValueLine key={p.name} port={p} run={io?.out[p.name]} />)}
    </div>
  )
}

function runBorder(run: NodeRunInfo | undefined, selected: boolean): { color: string; style: string } {
  switch (run?.state) {
    case 'running':       return { color: 'var(--accent)', style: 'solid' }
    case 'error':         return { color: 'var(--err)', style: 'solid' }
    case 'error_handled': return { color: 'var(--warn)', style: 'solid' }
    case 'skipped':
    case 'cancelled':     return { color: 'var(--ink-4)', style: 'dashed' }
    default:              return { color: selected ? 'var(--ink-3)' : 'var(--rule-2)', style: 'solid' }
  }
}

function RunBadge({ run }: { run?: NodeRunInfo }) {
  if (!run || run.state === 'idle') return null
  const count = run.count && run.count > 1 ? <span style={{ fontSize: 10 }}>x{run.count}</span> : null
  if (run.state === 'running') return <LoaderCircle size={13} strokeWidth={2} style={{ animation: 'spin 1s linear infinite', flexShrink: 0 }} />
  if (run.state === 'ok') return <>{count}<CircleCheck size={13} strokeWidth={2} style={{ flexShrink: 0 }} /></>
  if (run.state === 'error' || run.state === 'error_handled') return <>{count}<CircleX size={13} strokeWidth={2} style={{ flexShrink: 0 }} /></>
  return null
}

function FlowNodeView({ data, selected }: NodeProps<FlowRfNode>) {
  const { tr } = useTr()
  const { node, dim, run, issues } = data
  const faulty = new Set(issues?.ports ?? [])
  const border = runBorder(run, !!selected)
  const failed = run && (run.state === 'error' || run.state === 'error_handled') && run.error
  const received = run?.values && Object.keys(run.values).length
    ? Object.entries(run.values).map(([k, v]) => `${k} = ${v}`).join('\n') : undefined
  const [hover, setHover] = useState(false)
  const [info, setInfo] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout>>()
  const enter = () => { clearTimeout(timer.current); setHover(true) }
  const leave = () => { timer.current = setTimeout(() => { setHover(false); setInfo(false) }, HIDE_MS) }

  const linked = new Set(data.linked)
  const fam = FAMILY_INFO[node.family]
  const Icon = iconFor(node.icon, node.family)
  const left = [...(node.hasExec ? [EXEC_IN] : []), ...node.inputs]
  const right = [...(node.hasExec ? [EXEC_OUT] : []), ...node.outputs]
  const rows = Math.max(left.length, right.length)
  const isEvent = node.family === 'event'
  const radius = isEvent ? '12px 6px 6px 12px' : '6px'
  return (
    <div onMouseEnter={enter} onMouseLeave={leave} key={data.flash} className={data.flash ? 'flow-flash' : undefined}>
      <NodeToolbar isVisible={hover || info} position={Position.Top} align="start" offset={6}>
        <div onMouseEnter={enter} onMouseLeave={leave}>
          <div className="flow-node-toolbar">
            <button type="button" disabled title={tr('Bypass : case dans Params', 'Bypass: box in Params')}>
              <Ban size={13} strokeWidth={1.75} />
            </button>
            <button type="button" className={info ? 'on' : ''} title={tr('Infos du node', 'Node info')} onClick={() => setInfo(v => !v)}>
              <Info size={13} strokeWidth={1.75} />
            </button>
          </div>
        </div>
      </NodeToolbar>
      <NodeToolbar isVisible={info} position={Position.Bottom} align="start" offset={4}>
        <div onMouseEnter={enter} onMouseLeave={leave}><InfoCard node={node} io={data.io} run={run} /></div>
      </NodeToolbar>
      <div style={{
        width: NODE_W, background: 'var(--paper-2)',
        border: `1px ${border.style} ${border.color}`,
        borderRadius: radius,
        boxShadow: selected
          ? '0 0 0 3px color-mix(in oklch, var(--accent) 22%, transparent), var(--shadow-sm)'
          : 'var(--shadow-sm)',
        opacity: dim ? 0.35 : node.meta?.bypass === 'true' ? 0.55 : 1,
        paddingBottom: 4,
      }}>
        <div style={{
          height: HEADER_H, display: 'flex', alignItems: 'center', gap: 6, padding: '0 8px',
          background: fam.color, color: 'var(--on-accent)',
          borderRadius: isEvent ? '11px 5px 0 0' : '5px 5px 0 0',
        }}>
          <Icon size={14} strokeWidth={2} style={{ flexShrink: 0 }} />
          <span style={{ fontSize: 12, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
            {node.label}
          </span>
          {node.prefix && (
            <span style={{ fontSize: 10, fontWeight: 600, padding: '1px 5px', borderRadius: 4, background: 'color-mix(in oklch, var(--on-accent) 18%, transparent)' }}>
              {node.prefix}
            </span>
          )}
          {node.spec?.subflow && (
            <span title={node.spec.subflow.scope === 'shipped'
                    ? tr('Node livre verrouille : double clic pour voir dedans', 'Locked shipped node: double click to look inside')
                    : tr('Copie d\'equipe du node livre : double clic pour l\'editer', 'Team copy of the shipped node: double click to edit it')}
                  style={{ display: 'inline-flex', flexShrink: 0 }}>
              {node.spec.subflow.scope === 'shipped' ? <Lock size={12} /> : <Users size={12} />}
            </span>
          )}
          {node.destructive && (
            <span title={tr('Node destructif : efface, ecrase ou deplace des fichiers (validation au curseur a l\'enregistrement)', 'Destructive node: erases, overwrites or moves files (slider confirmation on save)')}
                  className="flow-issue-badge" style={{ background: 'var(--err)' }}>!</span>
          )}
          <RunBadge run={run} />
          {issues && issues.errors + issues.warnings > 0 && (
            <span className="flow-issue-badge" style={{ background: issues.errors ? 'var(--err)' : 'var(--warn)' }}
                  title={tr(`${issues.errors} erreur(s), ${issues.warnings} avertissement(s)`, `${issues.errors} error(s), ${issues.warnings} warning(s)`)}>
              {issues.errors + issues.warnings}
            </span>
          )}
        </div>
        {failed && (
          <div
            title={received ? tr(`Valeurs recues :\n${received}`, `Values received:\n${received}`) : undefined}
            style={{ padding: '4px 10px', fontSize: 11, lineHeight: 1.35, color: run?.state === 'error' ? 'var(--err)' : 'var(--warn)', borderBottom: '1px solid var(--rule)', wordBreak: 'break-word' }}
          >
            {run?.error}
          </div>
        )}
        {Array.from({ length: rows }, (_, i) => (
          <Row key={i} left={left[i]} right={right[i]} linked={linked} faulty={faulty} />
        ))}
      </div>
    </div>
  )
}

export const FlowNode = memo(FlowNodeView)
