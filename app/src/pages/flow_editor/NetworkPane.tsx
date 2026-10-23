// NetworkPane.tsx — the graph (03_EDITEUR §1, @xyflow/react). Nodes and links are derived
// from the FlowView (itself derived from the document in the store, P4); the selection is
// owned by the editor so it survives every edit. A drag stays local to xyflow and is
// committed once at onNodeDragStop (one undo entry, 03 §4).
// P2: runStates colours the nodes with the live (or opened) run.
// Tab opens the Tab menu at the mouse, F frames, Shift+S switches curved / straight wires.
// P4 editing keys (off in a field and when read-only): Suppr / Retour arriere, Ctrl+Z,
// Ctrl+Y / Ctrl+Maj+Z, Ctrl+C, Ctrl+V (at the mouse), Ctrl+A, Echap.
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
import type { FlowView, NodeRunInfo } from './types'
import type { CatalogEntry } from './v1_adapter'

const nodeTypes: NodeTypes = { flow: FlowNode }
const edgeTypes: EdgeTypes = { flow: FlowEdge }

// Shortcuts stay off while typing in a field (same guard as ActionGraph.tsx).
const typing = (t: EventTarget | null) =>
  t instanceof HTMLElement && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)

export interface EditActions {
  onMove:      (positions: Record<string, [number, number]>) => void
  onDelete:    () => void
  onCopy:      () => void
  onPaste:     (at: [number, number]) => void
  onUndo:      () => void
  onRedo:      () => void
  onSelectAll: () => void
}

export function NetworkPane({ view, flowKey, selection, search, dots, straight, catalog, runStates, edit, onSelect, onPick, onToggleWires }: {
  view: FlowView | null
  flowKey: string              // changes when another flow is loaded: frames it once
  selection: ReadonlySet<string>
  runStates?: Record<string, NodeRunInfo>
  search: string
  dots: boolean
  straight: boolean
  onToggleWires: () => void
  catalog: CatalogEntry[] | null
  edit: EditActions
  onSelect: (ids: string[]) => void
  onPick: (e: CatalogEntry) => void
}) {
  const { fitView, screenToFlowPosition } = useReactFlow()
  const wrap = useRef<HTMLDivElement>(null)
  const mouse = useRef({ x: 80, y: 80, cx: 0, cy: 0 })
  const [tab, setTab] = useState<{ x: number; y: number } | null>(null)
  const readOnly = !view || view.readOnly

  const q = search.trim().toLowerCase()
  const derived = useMemo<FlowRfNode[]>(() => {
    if (!view) return []
    const linked: Record<string, string[]> = {}
    for (const e of view.edges) {
      ;(linked[e.source] ??= []).push(handleId('out', e.sourcePort))
      ;(linked[e.target] ??= []).push(handleId('in', e.targetPort))
    }
    return view.nodes.map(n => ({
      id: n.id, type: 'flow', position: n.position, selected: selection.has(n.id),
      data: {
        node: n, linked: linked[n.id] ?? [], run: runStates?.[n.id],
        dim: !!q && ![n.label, n.type, ...n.inputs.map(p => p.name)].some(t => t.toLowerCase().includes(q)),
      },
    }))
  }, [view, q, runStates, selection])
  const [nodes, setNodes, onNodesChange] = useNodesState<FlowRfNode>(derived)
  useEffect(() => { setNodes(derived) }, [derived, setNodes])
  // Frame the whole flow once per flow loaded (not on each edit).
  useEffect(() => { if (flowKey) requestAnimationFrame(() => fitView({ padding: 0.15 })) }, [flowKey, fitView])

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
      const k = e.key.toLowerCase()
      const ctrl = e.ctrlKey || e.metaKey
      if (e.key === 'Tab') { e.preventDefault(); setTab({ x: mouse.current.x, y: mouse.current.y }) }
      else if (e.shiftKey && !ctrl && !e.altKey && k === 's') { e.preventDefault(); onToggleWires() }
      else if (!ctrl && !e.altKey && k === 'f') {
        const sel = [...selection].map(id => ({ id }))
        fitView({ padding: 0.15, ...(sel.length ? { nodes: sel } : {}) })
      }
      else if (e.key === 'Escape') { setTab(null); onSelect([]) }
      else if (ctrl && k === 'a') { e.preventDefault(); edit.onSelectAll() }
      else if (ctrl && k === 'c') { e.preventDefault(); edit.onCopy() }
      else if (readOnly) return
      else if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); edit.onDelete() }
      else if (ctrl && !e.shiftKey && k === 'z') { e.preventDefault(); edit.onUndo() }
      else if (ctrl && (k === 'y' || (e.shiftKey && k === 'z'))) { e.preventDefault(); edit.onRedo() }
      else if (ctrl && k === 'v') {
        e.preventDefault()
        const p = screenToFlowPosition({ x: mouse.current.cx, y: mouse.current.cy })
        edit.onPaste([p.x, p.y])
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [fitView, screenToFlowPosition, onSelect, onToggleWires, edit, readOnly, selection])

  return (
    <div
      ref={wrap}
      style={{ position: 'relative', flex: 1, minWidth: 480, minHeight: 0 }}
      onMouseMove={e => {
        const r = wrap.current?.getBoundingClientRect()
        if (r) mouse.current = { x: e.clientX - r.left, y: e.clientY - r.top, cx: e.clientX, cy: e.clientY }
      }}
    >
      <PortTooltipProvider>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onNodesChange={onNodesChange}
          onSelectionChange={({ nodes: sel }) => onSelect(sel.map(n => n.id))}
          onNodeDragStop={(_, __, dragged) => {
            if (!readOnly) edit.onMove(Object.fromEntries(dragged.map(n => [n.id, [n.position.x, n.position.y] as [number, number]])))
          }}
          nodesDraggable={!readOnly}
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
