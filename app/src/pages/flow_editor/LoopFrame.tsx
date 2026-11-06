// LoopFrame.tsx — the frame drawn behind a loop block, like Houdini (2026-10-23):
// ForEach / For / While Begin, its End (End.params.begin = id of the Begin, else the first End
// of the kind on the exec chain) and the body (every node on the exec chain from the Begin's
// `loop` output up to the End, plus the data nodes whose links all go into the body).
// Derived from the view, never saved; not selectable nor draggable, the mouse goes through
// (flow_editor.css). Nested loops = nested frames (the outer one wider and further behind).

import { memo } from 'react'
import type { Node, NodeProps } from '@xyflow/react'
import { FAMILY_INFO } from './families'
import { NODE_W } from './nodes/FlowNode'
import { nodeHeight } from './v1_adapter'
import type { FlowView, FlowViewNode } from './types'

export const LOOP_PREFIX = 'loop:'
const LOOP_PAD = 14    // inner frame margin around its nodes
const LOOP_STEP = 12   // more per nesting level, so an outer frame stays visible
const LOOP_HEAD = 20   // label band on top

const LOOP_KINDS: Record<string, { end: string; label: string }> = {
  'operator.foreach_begin': { end: 'operator.foreach_end', label: 'ForEach' },
  'operator.for_begin':     { end: 'operator.for_end',     label: 'For' },
  'operator.while_begin':   { end: 'operator.while_end',   label: 'While' },
}

export type LoopData = { label: string; width: number; height: number; level: number }
export type LoopRfNode = Node<LoopData, 'loop'>

export interface LoopBlock { id: string; label: string; members: Set<string>; level: number; x: number; y: number; width: number; height: number }

export function loopBlocks(view: FlowView): LoopBlock[] {
  const byId: Record<string, FlowViewNode> = Object.fromEntries(view.nodes.map(n => [n.id, n]))
  const execOut: Record<string, { port: string; target: string }[]> = {}
  const dataOut: Record<string, string[]> = {}
  const inExec = new Set<string>()
  for (const e of view.edges) {
    if (e.kind === 'exec') {
      ;(execOut[e.source] ??= []).push({ port: e.sourcePort, target: e.target })
      inExec.add(e.source); inExec.add(e.target)
    } else (dataOut[e.source] ??= []).push(e.target)
  }
  const blocks: Omit<LoopBlock, 'level' | 'x' | 'y' | 'width' | 'height'>[] = []
  for (const begin of view.nodes) {
    const kind = LOOP_KINDS[begin.type]
    if (!kind) continue
    const paired = view.nodes.find(n => n.type === kind.end && [...n.inputs, ...(n.constants ?? [])].find(p => p.name === 'begin')?.value === begin.id)
    // Exec walk from the `loop` output, stopped at the End (or the first End of the kind).
    const body = new Set<string>()
    let end = paired?.id ?? null
    const queue = (execOut[begin.id] ?? []).filter(o => o.port === 'loop').map(o => o.target)
    while (queue.length && body.size < 1000) {
      const id = queue.shift()!
      if (id === begin.id || body.has(id) || !byId[id]) continue
      if (id === end || (!end && byId[id].type === kind.end)) { end = id; continue }
      body.add(id)
      for (const o of execOut[id] ?? []) queue.push(o.target)
    }
    // Pure data nodes feeding only the block (a few passes for short chains).
    const inside = new Set([...body, ...(end ? [end] : [])])
    for (let pass = 0; pass < 3; pass++) {
      let grew = false
      for (const n of view.nodes) {
        if (inside.has(n.id) || n.id === begin.id || inExec.has(n.id) || LOOP_KINDS[n.type]) continue
        const outs = dataOut[n.id]
        if (outs?.length && outs.every(t => inside.has(t))) { body.add(n.id); inside.add(n.id); grew = true }
      }
      if (!grew) break
    }
    blocks.push({ id: begin.id, label: kind.label, members: new Set([begin.id, ...inside]) })
  }
  // Nesting level: 1 + the deepest loop it contains.
  const level = (b: typeof blocks[number], seen: Set<string>): number => {
    let deepest = 0
    for (const o of blocks) if (o !== b && b.members.has(o.id) && !seen.has(o.id)) deepest = Math.max(deepest, level(o, new Set([...seen, o.id])))
    return deepest + 1
  }
  return blocks.map(b => {
    const lv = level(b, new Set([b.id]))
    const pad = LOOP_PAD + (lv - 1) * LOOP_STEP
    const ns = [...b.members].map(id => byId[id])
    const x0 = Math.min(...ns.map(n => n.position.x)) - pad
    const y0 = Math.min(...ns.map(n => n.position.y)) - pad - LOOP_HEAD
    const x1 = Math.max(...ns.map(n => n.position.x + NODE_W)) + pad
    const y1 = Math.max(...ns.map(n => n.position.y + nodeHeight(n))) + pad
    return { ...b, level: lv, x: x0, y: y0, width: x1 - x0, height: y1 - y0 }
  })
}

function LoopView({ data }: NodeProps<LoopRfNode>) {
  const color = FAMILY_INFO.operator.color
  return (
    <div style={{
      width: data.width, height: data.height, borderRadius: 10,
      background: `color-mix(in oklch, ${color} ${data.level > 1 ? 4 : 6}%, transparent)`,
      border: `1px dashed color-mix(in oklch, ${color} 45%, transparent)`,
    }}>
      <div style={{ height: LOOP_HEAD, display: 'flex', alignItems: 'center', padding: '0 9px', fontSize: 11, fontWeight: 600,
                    color: `color-mix(in oklch, ${color} 70%, var(--ink-3))`, letterSpacing: 0.3 }}>
        {data.label}
      </div>
    </div>
  )
}

export const LoopFrame = memo(LoopView)
