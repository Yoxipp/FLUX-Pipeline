// FlowNode.tsx — a node of the Flows editor (03_EDITEUR §3): name band in the family colour
// (2026-10-22), icon, DCC prefix badge, exec row on top, one 20 px row per data port
// (value greyed or "<- n.port"). Hover shows a small toolbar like Houdini: bypass, info (doc).
// P2: run state of the node (03_EDITEUR §7): running = accent border + spinning loader, ok =
// check + count, error = --err border + message (values received in the tooltip),
// error_handled = --warn border, skipped / cancelled = dashed border.
// P4: issue badge (count, --err or --warn) in the header, red ring on the faulty ports,
// one blink when zoomed from the Problems panel.

import { memo, useRef, useState } from 'react'
import { NodeToolbar, Position, type Node, type NodeProps } from '@xyflow/react'
import { Ban, CircleCheck, CircleX, Info, LoaderCircle } from 'lucide-react'
import { FAMILY_INFO } from '../families'
import { iconFor } from '../icons'
import type { FlowViewNode, NodeRunInfo, PortSpec } from '../types'
import { formatValue, useTr } from '../useTr'
import { PortHandle, handleId } from './PortHandle'
import '../flow_editor.css'

export const NODE_W = 240
const HEADER_H = 28
const ROW_H = 20
const VALUE_MAX = 24
const HIDE_MS = 250   // time to reach the toolbar before it hides

export interface NodeIssues { errors: number; warnings: number; ports: string[] }
export type FlowNodeData = { node: FlowViewNode; linked: string[]; dim: boolean; run?: NodeRunInfo; issues?: NodeIssues; flash?: number }
export type FlowRfNode = Node<FlowNodeData, 'flow'>

const EXEC_IN: PortSpec = { name: 'exec', type: 'exec' }
const EXEC_OUT: PortSpec = { name: 'then', type: 'exec' }

function Row({ left, right, linked, faulty }: { left?: PortSpec; right?: PortSpec; linked: Set<string>; faulty: Set<string> }) {
  const value = left && left.type !== 'exec'
    ? left.wiredFrom ? `<- ${left.wiredFrom}` : formatValue(left.value, VALUE_MAX)
    : ''
  return (
    <div style={{ position: 'relative', height: ROW_H, display: 'flex', alignItems: 'center', gap: 6, padding: '0 10px', fontSize: 11 }}>
      {left && <PortHandle port={left} side="in" linked={linked.has(handleId('in', left.name))} faulty={faulty.has(left.name)} />}
      {left && (
        <span style={{ display: 'flex', gap: 5, minWidth: 0, flex: 1, overflow: 'hidden', whiteSpace: 'nowrap' }}>
          <span style={{ color: 'var(--ink-2)' }}>{left.name}</span>
          {value && <span style={{ color: 'var(--ink-4)', overflow: 'hidden', textOverflow: 'ellipsis' }}>{value}</span>}
        </span>
      )}
      {!left && <span style={{ flex: 1 }} />}
      {right && <span style={{ color: 'var(--ink-2)', whiteSpace: 'nowrap' }}>{right.name}</span>}
      {right && <PortHandle port={right} side="out" linked={linked.has(handleId('out', right.name))} faulty={faulty.has(right.name)} />}
    </div>
  )
}

function InfoCard({ node }: { node: FlowViewNode }) {
  const { tr, lang } = useTr()
  const fam = FAMILY_INFO[node.family]
  const doc = lang === 'en' ? node.doc_en || node.doc_fr : node.doc_fr || node.doc_en
  return (
    <div style={{
      width: 300, marginTop: 4, padding: '8px 10px', background: 'var(--paper)', border: '1px solid var(--rule-2)',
      borderRadius: 6, boxShadow: 'var(--shadow)', fontSize: 11.5, color: 'var(--ink-2)',
    }}>
      <div style={{ fontWeight: 600, color: 'var(--ink)' }}>{node.label}</div>
      <div style={{ fontSize: 11, color: 'var(--ink-4)', marginBottom: 6 }}>{node.type} · {lang === 'en' ? fam.en : fam.fr}</div>
      <div style={{ whiteSpace: 'pre-wrap', maxHeight: 220, overflowY: 'auto' }}>{doc || tr('Pas de documentation.', 'No documentation.')}</div>
      {Object.entries(node.meta ?? {}).map(([k, v]) => (
        <div key={k} style={{ display: 'flex', gap: 6, fontSize: 11, marginTop: 3 }}>
          <span style={{ color: 'var(--ink-4)', width: 56, flexShrink: 0 }}>{k}</span>
          <span style={{ wordBreak: 'break-all', whiteSpace: 'pre-wrap' }}>{v}</span>
        </div>
      ))}
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
        <div onMouseEnter={enter} onMouseLeave={leave}><InfoCard node={node} /></div>
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
