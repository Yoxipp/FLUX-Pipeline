// FlowNode.tsx — a node of the Flows editor (03_EDITEUR §3): 3 px family bar, icon, label,
// DCC prefix badge, exec row on top, one 20 px row per data port (value greyed or "<- n.port").

import { memo } from 'react'
import type { Node, NodeProps } from '@xyflow/react'
import { FAMILY_INFO, familyHeaderBg } from '../families'
import { iconFor } from '../icons'
import type { FlowViewNode, PortSpec } from '../types'
import { formatValue } from '../useTr'
import { PortHandle, handleId } from './PortHandle'

export const NODE_W = 240
const HEADER_H = 28
const ROW_H = 20
const VALUE_MAX = 24

export type FlowNodeData = { node: FlowViewNode; linked: string[]; dim: boolean }
export type FlowRfNode = Node<FlowNodeData, 'flow'>

const EXEC_IN: PortSpec = { name: 'exec', type: 'exec' }
const EXEC_OUT: PortSpec = { name: 'then', type: 'exec' }

function Row({ left, right, linked }: { left?: PortSpec; right?: PortSpec; linked: Set<string> }) {
  const value = left && left.type !== 'exec'
    ? left.wiredFrom ? `<- ${left.wiredFrom}` : formatValue(left.value, VALUE_MAX)
    : ''
  return (
    <div style={{ position: 'relative', height: ROW_H, display: 'flex', alignItems: 'center', gap: 6, padding: '0 10px', fontSize: 11 }}>
      {left && <PortHandle port={left} side="in" linked={linked.has(handleId('in', left.name))} />}
      {left && (
        <span style={{ display: 'flex', gap: 5, minWidth: 0, flex: 1, overflow: 'hidden', whiteSpace: 'nowrap' }}>
          <span style={{ color: 'var(--ink-2)' }}>{left.name}</span>
          {value && <span style={{ color: 'var(--ink-4)', overflow: 'hidden', textOverflow: 'ellipsis' }}>{value}</span>}
        </span>
      )}
      {!left && <span style={{ flex: 1 }} />}
      {right && <span style={{ color: 'var(--ink-2)', whiteSpace: 'nowrap' }}>{right.name}</span>}
      {right && <PortHandle port={right} side="out" linked={linked.has(handleId('out', right.name))} />}
    </div>
  )
}

function FlowNodeView({ data, selected }: NodeProps<FlowRfNode>) {
  const { node, dim } = data
  const linked = new Set(data.linked)
  const fam = FAMILY_INFO[node.family]
  const Icon = iconFor(node.icon, node.family)
  const left = [...(node.hasExec ? [EXEC_IN] : []), ...node.inputs]
  const right = [...(node.hasExec ? [EXEC_OUT] : []), ...node.outputs]
  const rows = Math.max(left.length, right.length)
  const isEvent = node.family === 'event'
  return (
    <div style={{
      width: NODE_W, background: 'var(--paper-2)',
      border: `1px solid ${selected ? 'var(--rule-3)' : 'var(--rule-2)'}`,
      borderLeft: `3px solid ${fam.color}`,
      borderRadius: isEvent ? '12px 6px 6px 12px' : 6,
      boxShadow: selected
        ? '0 0 0 3px color-mix(in oklch, var(--accent) 22%, transparent), var(--shadow-sm)'
        : 'var(--shadow-sm)',
      opacity: dim ? 0.35 : 1,
      paddingBottom: 4,
    }}>
      <div style={{
        height: HEADER_H, display: 'flex', alignItems: 'center', gap: 6, padding: '0 8px',
        background: familyHeaderBg(node.family), borderRadius: isEvent ? '10px 5px 0 0' : '5px 5px 0 0',
        borderBottom: '1px solid var(--rule)',
      }}>
        <Icon size={14} strokeWidth={1.75} color={fam.color} style={{ flexShrink: 0 }} />
        <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--ink)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
          {node.label}
        </span>
        {node.prefix && <span className="tag" style={{ fontSize: 10 }}>{node.prefix}</span>}
      </div>
      {Array.from({ length: rows }, (_, i) => (
        <Row key={i} left={left[i]} right={right[i]} linked={linked} />
      ))}
    </div>
  )
}

export const FlowNode = memo(FlowNodeView)
