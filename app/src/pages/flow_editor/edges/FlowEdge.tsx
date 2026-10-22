// FlowEdge.tsx — a link of the Flows editor: exec = 2 px ink, data = 1.5 px in the colour
// of the port type (dashed for `pattern`). Flat, no glow.

import { memo } from 'react'
import { BaseEdge, getBezierPath, type Edge, type EdgeProps } from '@xyflow/react'
import { baseType, portColor } from '../portTypes'
import type { PortType } from '../types'

export type FlowEdgeData = { kind: 'exec' | 'data'; type: PortType; dim: boolean }
export type FlowRfEdge = Edge<FlowEdgeData, 'flow'>

function FlowEdgeView({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, selected }: EdgeProps<FlowRfEdge>) {
  const [path] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition })
  const exec = data?.kind === 'exec'
  return (
    <BaseEdge
      id={id}
      path={path}
      style={{
        stroke: exec ? 'var(--port-exec)' : portColor(data?.type ?? 'any'),
        strokeWidth: (exec ? 2 : 1.5) + (selected ? 1 : 0),
        strokeDasharray: data && baseType(data.type) === 'pattern' ? '5 4' : undefined,
        opacity: data?.dim ? 0.25 : exec ? 0.85 : 0.9,
      }}
    />
  )
}

export const FlowEdge = memo(FlowEdgeView)
