// PortHandle.tsx — a typed port (03_EDITEUR §3): shape by type family, colour --port-<type>,
// filled when linked, ring when not. Hover shows the shared PortTooltip.
// P4 (03 §5): connectable when the graph is editable. While a link is dragged, compatible
// ports get an accent ring, the others drop to 35 % and their tooltip gives the reason in red.
// Hit area (2026-10-23): the Handle stays 10 px (xyflow measures it for the link ends) but
// is transparent; the visible dot is a child, and a transparent ::before (flow_editor.css
// .flow-port-in / .flow-port-out) widens the grab zone, more on outputs.
// Pressing a linked input picks its link up from the source (ConnectState.grabLinked):
// no new link starts from a linked input.

import { Handle, Position, useNodeId } from '@xyflow/react'
import { portColor, portShape } from '../portTypes'
import type { PortSpec } from '../types'
import { useConnectState } from './connectState'
import { usePortTooltip } from './PortTooltip'

const SIZE = 10

export const handleId = (side: 'in' | 'out', name: string) => `${side}:${name}`
export const portOfHandle = (id: string | null | undefined) => (id ?? '').replace(/^(in|out):/, '')

export function PortHandle({ port, side, linked, faulty }: { port: PortSpec; side: 'in' | 'out'; linked: boolean; faulty?: boolean }) {
  const { show, hide } = usePortTooltip()
  const nodeId = useNodeId() ?? ''
  const { editable, verdict, grabLinked } = useConnectState()
  const v = verdict({ node: nodeId, port: port.name, side })
  const refused = v?.status === 'incompatible'
  const color = port.type === 'exec' ? 'var(--port-exec)' : portColor(port.type)
  const shape = portShape(port.type)
  const clipped = shape === 'triangle' || shape === 'diamond'
  const style: React.CSSProperties = {
    width: SIZE, height: SIZE, minWidth: SIZE, minHeight: SIZE,
    [side === 'in' ? 'left' : 'right']: -SIZE / 2 - 1,
    background: 'transparent', border: 'none', borderRadius: 0,
    cursor: editable ? 'crosshair' : 'default',
  }
  const dot: React.CSSProperties = {
    position: 'absolute', inset: 0, pointerEvents: 'none', boxSizing: 'border-box',
    borderRadius: shape === 'square' ? 2 : clipped ? 0 : '50%',
    clipPath: shape === 'triangle' ? 'polygon(0 0, 100% 50%, 0 100%)'
      : shape === 'diamond' ? 'polygon(50% 0, 100% 50%, 50% 100%, 0 50%)' : undefined,
    // Clipped shapes cannot show a ring: dimmed when not linked instead.
    background: shape === 'hollow' ? 'var(--paper-2)' : linked || clipped ? color : 'var(--paper-2)',
    border: clipped ? 'none' : `${shape === 'ring' && linked ? 3 : 2}px solid ${color}`,
    opacity: refused ? 0.35 : clipped && !linked ? 0.55 : 1,
    outline: v && !refused ? '2px solid var(--accent)' : faulty ? '2px solid var(--err)' : undefined,
    outlineOffset: 2,
  }
  return (
    <Handle
      type={side === 'in' ? 'target' : 'source'}
      position={side === 'in' ? Position.Left : Position.Right}
      id={handleId(side, port.name)}
      isConnectable={editable}
      className={side === 'in' ? 'flow-port-in' : 'flow-port-out'}
      style={style}
      onMouseDownCapture={e => {
        // Runs before xyflow's own mousedown: a linked input lends its link instead.
        if (e.button !== 0 || side !== 'in' || !linked || !editable) return
        if (grabLinked({ node: nodeId, port: port.name, side }, e.clientX, e.clientY)) { e.stopPropagation(); e.preventDefault() }
      }}
      onMouseEnter={e => show({ port, side, rect: e.currentTarget.getBoundingClientRect(), refusal: refused ? v : undefined })}
      onMouseLeave={hide}
    >
      <span style={dot} />
    </Handle>
  )
}
