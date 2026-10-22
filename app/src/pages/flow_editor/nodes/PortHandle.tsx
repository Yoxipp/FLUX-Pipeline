// PortHandle.tsx — a typed port (03_EDITEUR §3): shape by type family, colour --port-<type>,
// filled when linked, ring when not. Hover shows the shared PortTooltip.

import { Handle, Position } from '@xyflow/react'
import { portColor, portShape } from '../portTypes'
import type { PortSpec } from '../types'
import { usePortTooltip } from './PortTooltip'

const SIZE = 10

export const handleId = (side: 'in' | 'out', name: string) => `${side}:${name}`

export function PortHandle({ port, side, linked }: { port: PortSpec; side: 'in' | 'out'; linked: boolean }) {
  const { show, hide } = usePortTooltip()
  const color = port.type === 'exec' ? 'var(--port-exec)' : portColor(port.type)
  const shape = portShape(port.type)
  const clipped = shape === 'triangle' || shape === 'diamond'
  const style: React.CSSProperties = {
    width: SIZE, height: SIZE, minWidth: SIZE, minHeight: SIZE,
    [side === 'in' ? 'left' : 'right']: -SIZE / 2 - 1,
    borderRadius: shape === 'square' ? 2 : clipped ? 0 : '50%',
    clipPath: shape === 'triangle' ? 'polygon(0 0, 100% 50%, 0 100%)'
      : shape === 'diamond' ? 'polygon(50% 0, 100% 50%, 50% 100%, 0 50%)' : undefined,
    // Clipped shapes cannot show a ring: dimmed when not linked instead.
    background: shape === 'hollow' ? 'var(--paper-2)' : linked || clipped ? color : 'var(--paper-2)',
    border: clipped ? 'none' : `${shape === 'ring' && linked ? 3 : 2}px solid ${color}`,
    opacity: clipped && !linked ? 0.55 : 1,
    cursor: 'default',
  }
  return (
    <Handle
      type={side === 'in' ? 'target' : 'source'}
      position={side === 'in' ? Position.Left : Position.Right}
      id={handleId(side, port.name)}
      isConnectable={false}
      style={style}
      onMouseEnter={e => show({ port, side, rect: e.currentTarget.getBoundingClientRect() })}
      onMouseLeave={hide}
    />
  )
}
