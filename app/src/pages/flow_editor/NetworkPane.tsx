// NetworkPane.tsx — the graph (03_EDITEUR §1, @xyflow/react). Nodes and links are derived
// from the FlowView; P0 is read-only (drag moves nodes locally, nothing is saved).
// Tab opens the Tab menu at the mouse, F frames, Shift+S switches curved / straight wires.
// Pan: middle button, select: drag on the background. No +/- / frame buttons (2026-10-22).

import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Background, BackgroundVariant, MiniMap, ReactFlow, useNodesState, useReactFlow,
  type NodeTypes, type EdgeTypes,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { FAMILY_INFO } from './families'
import { FlowEdge, type FlowRfEdge } from './edges/FlowEdge'
import { FlowNode, type FlowRfNode } from './nodes/FlowNode'
import { handleId } from './nodes/PortHandle'
import { PortTooltipProvider } from './nodes/PortTooltip'
import { TabMenu } from './TabMenu'
import type { FlowView } from './types'
import type { CatalogEntry } from './v1_adapter'

const nodeTypes: NodeTypes = { flow: FlowNode }
const edgeTypes: EdgeTypes = { flow: FlowEdge }

// Shortcuts stay off while typing in a field (same guard as ActionGraph.tsx).
const typing = (t: EventTarget | null) =>
  t instanceof HTMLElement && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)

export function NetworkPane({ view, search, dots, straight, catalog, onSelect, onPick, onToggleWires }: {
  view: FlowView | null
  search: string
  dots: boolean
  straight: boolean
  onToggleWires: () => void
  catalog: CatalogEntry[] | null
  onSelect: (id: string | null) => void
  onPick: (e: CatalogEntry) => void
}) {
  const { fitView } = useReactFlow()
  const wrap = useRef<HTMLDivElement>(null)
  const mouse = useRef({ x: 80, y: 80 })
  const [tab, setTab] = useState<{ x: number; y: number } | null>(null)

  const q = search.trim().toLowerCase()
  const derived = useMemo<FlowRfNode[]>(() => {
    if (!view) return []
    const linked: Record<string, string[]> = {}
    for (const e of view.edges) {
      ;(linked[e.source] ??= []).push(handleId('out', e.sourcePort))
      ;(linked[e.target] ??= []).push(handleId('in', e.targetPort))
    }
    return view.nodes.map(n => ({
      id: n.id, type: 'flow', position: n.position,
      data: {
        node: n, linked: linked[n.id] ?? [],
        dim: !!q && ![n.label, n.type, ...n.inputs.map(p => p.name)].some(t => t.toLowerCase().includes(q)),
      },
    }))
  }, [view, q])
  const [nodes, setNodes, onNodesChange] = useNodesState<FlowRfNode>(derived)
  useEffect(() => { setNodes(derived) }, [derived, setNodes])
  // Frame the whole flow once per flow loaded.
  useEffect(() => { if (view) requestAnimationFrame(() => fitView({ padding: 0.15 })) }, [view, fitView])

  // Data links first so the exec chain (the main flow) is drawn on top.
  const edges = useMemo<FlowRfEdge[]>(() => [...(view?.edges ?? [])]
    .sort((a, b) => Number(a.kind === 'exec') - Number(b.kind === 'exec'))
    .map(e => ({
      id: e.id, type: 'flow', source: e.source, target: e.target,
      sourceHandle: handleId('out', e.sourcePort), targetHandle: handleId('in', e.targetPort),
      data: { kind: e.kind, type: e.type, dim: !!q, straight },
    })), [view, q, straight])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (typing(e.target)) return
      if (e.key === 'Tab') { e.preventDefault(); setTab({ ...mouse.current }) }
      else if (e.shiftKey && (e.key === 'S' || e.key === 's')) { e.preventDefault(); onToggleWires() }
      else if (e.key === 'f' || e.key === 'F') fitView({ padding: 0.15 })
      else if (e.key === 'Escape') { setTab(null); onSelect(null) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [fitView, onSelect, onToggleWires])

  return (
    <div
      ref={wrap}
      style={{ position: 'relative', flex: 1, minWidth: 480, minHeight: 0 }}
      onMouseMove={e => {
        const r = wrap.current?.getBoundingClientRect()
        if (r) mouse.current = { x: e.clientX - r.left, y: e.clientY - r.top }
      }}
    >
      <PortTooltipProvider>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onNodesChange={onNodesChange}
          onSelectionChange={({ nodes: sel }) => onSelect(sel.length === 1 ? sel[0].id : null)}
          nodesConnectable={false}
          edgesFocusable={false}
          deleteKeyCode={null}
          selectionOnDrag
          panOnDrag={[1, 2]}
          minZoom={0.15}
          proOptions={{ hideAttribution: true }}
          colorMode="dark"
        >
          {dots && <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="var(--rule-2)" />}
          <MiniMap
            pannable zoomable
            nodeColor={n => FAMILY_INFO[(n as FlowRfNode).data.node.family].color}
            maskColor="color-mix(in oklch, var(--bg-deep) 70%, transparent)"
            style={{ background: 'var(--paper)' }}
          />
        </ReactFlow>
      </PortTooltipProvider>
      {tab && <TabMenu entries={catalog} x={tab.x} y={tab.y} onPick={onPick} onClose={() => setTab(null)} />}
    </div>
  )
}
