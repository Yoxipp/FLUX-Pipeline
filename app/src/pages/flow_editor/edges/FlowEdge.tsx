// FlowEdge.tsx — a link of the Flows editor. The main flow stands out (2026-10-22):
// exec = 3 px near-white, data = 1.5 px in the colour of the port type, softer (dashed for
// `pattern`). Curved or straight (Shift+S). Flat, no glow.

import { memo } from 'react'
import { BaseEdge, getBezierPath, getStraightPath, type Edge, type EdgeProps } from '@xyflow/react'
import { baseType, portColor } from '../portTypes'
import type { PortType } from '../types'

export type FlowEdgeData = { kind: 'exec' | 'data'; type: PortType; dim: boolean; straight: boolean }
export type FlowRfEdge = Edge<FlowEdgeData, 'flow'>

function FlowEdgeView({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, selected }: EdgeProps<FlowRfEdge>) {
  const [path] = data?.straight
    ? getStraightPath({ sourceX, sourceY, targetX, targetY })
    : getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition })
  const exec = data?.kind === 'exec'
  return (
    <BaseEdge
      id={id}
      path={path}
      style={{
        stroke: exec ? 'var(--port-exec)' : portColor(data?.type ?? 'any'),
        strokeWidth: (exec ? 3 : 1.5) + (selected ? 1 : 0),
        strokeDasharray: data && baseType(data.type) === 'pattern' ? '5 4' : undefined,
        opacity: data?.dim ? 0.2 : exec ? 1 : 0.6,
      }}
    />
  )
}

export const FlowEdge = memo(FlowEdgeView)
