// FlowEdge.tsx — a link of the Flows editor. The main flow stands out (2026-10-22):
// exec = 3 px near-white, data = 1.5 px in the colour of the port type, softer (dashed for
// `pattern`). Curved or straight (Shift+S). Flat, no glow.
// P4: an implicit conversion (int -> float...) shows a small "~" mark in the middle; a link
// between incompatible types (kept, reported by the validation) or named by an issue is --err.

import { memo } from 'react'
import { BaseEdge, EdgeLabelRenderer, getBezierPath, getStraightPath, type Edge, type EdgeProps } from '@xyflow/react'
import { baseType, portColor } from '../portTypes'
import type { PortType } from '../types'

export type FlowEdgeData = { kind: 'exec' | 'data'; type: PortType; dim: boolean; straight: boolean; conversion?: boolean; bad?: boolean }
export type FlowRfEdge = Edge<FlowEdgeData, 'flow'>

function FlowEdgeView({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, selected }: EdgeProps<FlowRfEdge>) {
  const [path, lx, ly] = data?.straight
    ? getStraightPath({ sourceX, sourceY, targetX, targetY })
    : getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition })
  const exec = data?.kind === 'exec'
  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        style={{
          stroke: data?.bad ? 'var(--err)' : exec ? 'var(--port-exec)' : portColor(data?.type ?? 'any'),
          strokeWidth: (exec ? 3 : 1.5) + (selected ? 1 : 0),
          strokeDasharray: data && baseType(data.type) === 'pattern' ? '5 4' : undefined,
          opacity: data?.dim ? 0.2 : exec || data?.bad ? 1 : 0.6,
        }}
      />
      {data?.conversion && !data.dim && (
        <EdgeLabelRenderer>
          <div
            title="Conversion implicite"
            style={{
              position: 'absolute', transform: `translate(-50%, -50%) translate(${lx}px, ${ly}px)`, pointerEvents: 'all',
              fontSize: 10, lineHeight: '12px', padding: '0 4px', borderRadius: 4, color: 'var(--ink-2)',
              background: 'var(--paper-2)', border: '1px solid var(--rule-2)',
            }}
          >~</div>
        </EdgeLabelRenderer>
      )}
    </>
  )
}

export const FlowEdge = memo(FlowEdgeView)
