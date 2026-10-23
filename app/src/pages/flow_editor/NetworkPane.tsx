// NetworkPane.tsx — the graph (03_EDITEUR §1, @xyflow/react). Nodes and links are derived
// from the FlowView (itself derived from the document in the store, P4); the selection is
// owned by the editor so it survives every edit. A drag stays local to xyflow and is
// committed once at onNodeDragStop (one undo entry, 03 §4).
// P2: runStates colours the nodes with the live (or opened) run.
// Tab opens the Tab menu at the mouse, F frames, Shift+S switches curved / straight wires.
// P4 editing keys (off in a field and when read-only): Suppr / Retour arriere, Ctrl+Z,
// Ctrl+Y / Ctrl+Maj+Z, Ctrl+C, Ctrl+V (at the mouse), Ctrl+A, Echap.
// P4 links (03 §5): checkLink while dragging (ports ringed or at 35 %, red reason in the
// tooltip, the drop creates nothing when refused); a link dropped in the void opens the Tab
// menu limited to the compatible nodes, the node created is linked. Shelf / Catalogue items
// dropped here are created at the drop point (dataTransfer application/x-flux-node).
// Pan: middle button, select: drag on the background. No +/- / frame buttons (2026-10-22).

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Background, BackgroundVariant, MiniMap, ReactFlow, useNodesState, useReactFlow,
  type NodeTypes, type EdgeTypes, type Connection as RfConnection, type Edge,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { toast } from 'sonner'
import { FAMILY_INFO } from './families'
import { FlowEdge, type FlowRfEdge } from './edges/FlowEdge'
import { FlowNode, type FlowRfNode } from './nodes/FlowNode'
import { handleId, portOfHandle } from './nodes/PortHandle'
import { PortTooltipProvider } from './nodes/PortTooltip'
import { ConnectCtx, type ConnectState } from './nodes/connectState'
import { checkLink, firstCompatible, type PortEnd } from './portTypes'
import { TabMenu } from './TabMenu'
import type { FlowDocLink, FlowView, FlowViewNode, NodeRunInfo } from './types'
import type { CatalogEntry } from './v1_adapter'
import { useTr } from './useTr'

const nodeTypes: NodeTypes = { flow: FlowNode }
const edgeTypes: EdgeTypes = { flow: FlowEdge }
export const DRAG_MIME = 'application/x-flux-node'

// Shortcuts stay off while typing in a field (same guard as ActionGraph.tsx).
export const typing = (t: EventTarget | null) =>
  t instanceof HTMLElement && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)

export interface EditActions {
  onMove:      (positions: Record<string, [number, number]>) => void
  onDelete:    () => void
  onCopy:      () => void
  onPaste:     (at: [number, number]) => void
  onUndo:      () => void
  onRedo:      () => void
  onSelectAll: () => void
  onConnect:   (from: string, to: string) => void
  onDisconnect: (links: FlowDocLink[]) => void
  // Adds a catalogue node at `at`; `link` = the dragged port to link it to.
  onAdd:       (entry: CatalogEntry, at: [number, number], link?: { end: PortEnd; port: string }) => void
}

type TabAt = { x: number; y: number; fx: number; fy: number; from?: { end: PortEnd; type: string } }

export function NetworkPane({ view, flowKey, selection, search, dots, straight, catalog, runStates, edit, onSelect, onToggleWires }: {
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
}) {
  const { tr, lang } = useTr()
  const { fitView, screenToFlowPosition } = useReactFlow()
  const wrap = useRef<HTMLDivElement>(null)
  const mouse = useRef({ x: 80, y: 80, cx: 0, cy: 0 })
  const [tab, setTab] = useState<TabAt | null>(null)
  const [drag, setDrag] = useState<PortEnd | null>(null)
  const [edgeSel, setEdgeSel] = useState<string[]>([])
  const readOnly = !view || view.readOnly

  const byId = useMemo(() => Object.fromEntries((view?.nodes ?? []).map(n => [n.id, n])) as Record<string, FlowViewNode>, [view])
  const links = useMemo<FlowDocLink[]>(() => (view?.edges ?? []).map(e => ({ from: `${e.source}.${e.sourcePort}`, to: `${e.target}.${e.targetPort}` })), [view])

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
      id: e.id, type: 'flow', source: e.source, target: e.target, selected: edgeSel.includes(e.id),
      sourceHandle: handleId('out', e.sourcePort), targetHandle: handleId('in', e.targetPort),
      data: { kind: e.kind, type: e.type, dim: !!q, straight, conversion: e.conversion, bad: e.bad },
    })), [view, q, straight, edgeSel])

  const connectState = useMemo<ConnectState>(() => ({
    editable: !readOnly,
    verdict: end => !drag || (end.node === drag.node && end.port === drag.port && end.side === drag.side) ? null : checkLink(byId, links, drag, end),
  }), [readOnly, drag, byId, links])

  const endsOf = (c: RfConnection | Edge): [PortEnd, PortEnd] => [
    { node: c.source, port: portOfHandle(c.sourceHandle), side: 'out' },
    { node: c.target, port: portOfHandle(c.targetHandle), side: 'in' },
  ]
  const isValidConnection = useCallback((c: RfConnection | Edge) => checkLink(byId, links, ...endsOf(c)).status !== 'incompatible', [byId, links])

  const deleteEdges = useCallback(() => {
    const gone = (view?.edges ?? []).filter(e => edgeSel.includes(e.id))
      .map(e => ({ from: `${e.source}.${e.sourcePort}`, to: `${e.target}.${e.targetPort}` }))
    if (gone.length) { edit.onDisconnect(gone); setEdgeSel([]) }
    return gone.length > 0
  }, [view, edgeSel, edit])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (typing(e.target)) return
      const k = e.key.toLowerCase()
      const ctrl = e.ctrlKey || e.metaKey
      if (e.key === 'Tab') {
        e.preventDefault()
        const p = screenToFlowPosition({ x: mouse.current.cx, y: mouse.current.cy })
        setTab({ x: mouse.current.x, y: mouse.current.y, fx: p.x, fy: p.y })
      }
      else if (e.shiftKey && !ctrl && !e.altKey && k === 's') { e.preventDefault(); onToggleWires() }
      else if (!ctrl && !e.altKey && k === 'f') {
        const sel = [...selection].map(id => ({ id }))
        fitView({ padding: 0.15, ...(sel.length ? { nodes: sel } : {}) })
      }
      else if (e.key === 'Escape') { setTab(null); onSelect([]); setEdgeSel([]) }
      else if (ctrl && k === 'a') { e.preventDefault(); edit.onSelectAll() }
      else if (ctrl && k === 'c') { e.preventDefault(); edit.onCopy() }
      else if (readOnly) return
      else if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); if (!deleteEdges()) edit.onDelete() }
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
  }, [fitView, screenToFlowPosition, onSelect, onToggleWires, edit, readOnly, selection, deleteEdges])

  const pickTab = useCallback((entry: CatalogEntry) => {
    if (!tab) return
    if (readOnly) { toast.info(tr('Flow en lecture seule', 'Read-only flow')); return }
    const from = tab.from
    const port = from && entry.spec ? firstCompatible(entry.spec, from.type, from.end.side) : null
    edit.onAdd(entry, [tab.fx, tab.fy], from && port ? { end: from.end, port } : undefined)
  }, [tab, readOnly, edit, tr])

  const tabFilter = useMemo(() => {
    const from = tab?.from
    if (!from) return undefined
    return (e: CatalogEntry) => !!e.spec && firstCompatible(e.spec, from.type, from.end.side) !== null
  }, [tab])

  const typeOf = (end: PortEnd) => {
    const n = byId[end.node]
    const p = (end.side === 'in' ? n?.inputs : n?.outputs)?.find(x => x.name === end.port)
    return p?.type ?? (end.port === 'exec' || end.port === 'then' ? 'exec' : 'any')
  }

  return (
    <div
      ref={wrap}
      style={{ position: 'relative', flex: 1, minWidth: 480, minHeight: 0 }}
      onMouseMove={e => {
        const r = wrap.current?.getBoundingClientRect()
        if (r) mouse.current = { x: e.clientX - r.left, y: e.clientY - r.top, cx: e.clientX, cy: e.clientY }
      }}
      onDragOver={e => { if (!readOnly && e.dataTransfer.types.includes(DRAG_MIME)) { e.preventDefault(); e.dataTransfer.dropEffect = 'copy' } }}
      onDrop={e => {
        const type = e.dataTransfer.getData(DRAG_MIME)
        const entry = catalog?.find(c => c.type === type)
        if (!entry || readOnly) return
        e.preventDefault()
        const p = screenToFlowPosition({ x: e.clientX, y: e.clientY })
        edit.onAdd(entry, [p.x, p.y])
      }}
    >
      <PortTooltipProvider>
        <ConnectCtx.Provider value={connectState}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            onNodesChange={onNodesChange}
            onSelectionChange={({ nodes: sel, edges: esel }) => {
              onSelect(sel.map(n => n.id))
              const ids = esel.map(x => x.id)
              setEdgeSel(cur => cur.length === ids.length && ids.every(id => cur.includes(id)) ? cur : ids)
            }}
            onNodeDragStop={(_, __, dragged) => {
              if (!readOnly) edit.onMove(Object.fromEntries(dragged.map(n => [n.id, [n.position.x, n.position.y] as [number, number]])))
            }}
            nodesDraggable={!readOnly}
            nodesConnectable={!readOnly}
            isValidConnection={isValidConnection}
            onConnectStart={(_, p) => {
              if (p.nodeId && p.handleId) setDrag({ node: p.nodeId, port: portOfHandle(p.handleId), side: p.handleType === 'source' ? 'out' : 'in' })
            }}
            onConnect={c => {
              const r = checkLink(byId, links, ...endsOf(c))
              if (r.status !== 'incompatible' && r.from && r.to) edit.onConnect(r.from, r.to)
            }}
            onConnectEnd={(ev, state) => {
              const from = drag
              setDrag(null)
              if (!from || state.toNode || readOnly) return
              // Dropped in the void: Tab menu of the compatible nodes, at the drop point.
              const pt = 'changedTouches' in ev ? ev.changedTouches[0] : ev
              const r = wrap.current?.getBoundingClientRect()
              if (!r) return
              const p = screenToFlowPosition({ x: pt.clientX, y: pt.clientY })
              setTab({ x: pt.clientX - r.left, y: pt.clientY - r.top, fx: p.x, fy: p.y, from: { end: from, type: typeOf(from) } })
            }}
            connectionRadius={24}
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
        </ConnectCtx.Provider>
      </PortTooltipProvider>
      {tab && (
        <TabMenu
          entries={catalog} x={tab.x} y={tab.y} filter={tabFilter}
          title={tab.from ? (lang === 'en' ? 'Compatible nodes' : 'Nodes compatibles') : undefined}
          onPick={pickTab} onClose={() => setTab(null)}
        />
      )}
    </div>
  )
}
