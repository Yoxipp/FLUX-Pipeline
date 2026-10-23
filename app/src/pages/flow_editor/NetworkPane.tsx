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
// P4 issues: badge per node, red ring on the faulty port, the link named by an issue in --err;
// lash makes a node blink once (zoom from the Problems panel).
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
import { FlowNode, NODE_W, type FlowRfNode, type NodeIssues } from './nodes/FlowNode'
import { GroupBox, GROUP_HEAD, GROUP_PAD, type GroupRfNode } from './GroupBox'
import { NoteNode, type NoteRfNode } from './NoteNode'
import { nodeHeight } from './v1_adapter'
import { handleId, portOfHandle } from './nodes/PortHandle'
import { PortTooltipProvider } from './nodes/PortTooltip'
import { ConnectCtx, type ConnectState } from './nodes/connectState'
import { checkLink, firstCompatible, type PortEnd } from './portTypes'
import { TabMenu } from './TabMenu'
import type { FlowDocLink, FlowView, FlowViewNode, Issue, NodeRunInfo } from './types'
import type { CatalogEntry } from './v1_adapter'
import { useTr } from './useTr'

const nodeTypes: NodeTypes = { flow: FlowNode, box: GroupBox, note: NoteNode }
type AnyRfNode = FlowRfNode | GroupRfNode | NoteRfNode
export const GROUP_PREFIX = 'group:'
export const NOTE_PREFIX = 'note:'
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
  onGroup:     () => void                          // Ctrl+G: box around the selected nodes
  onNote:      (at: [number, number]) => void      // N: note at the mouse
  onRenameGroup: (id: string, label: string) => void
  onNoteText:  (id: string, text: string) => void
}

type TabAt = { x: number; y: number; fx: number; fy: number; from?: { end: PortEnd; type: string } }

export function NetworkPane({ view, flowKey, selection, search, dots, straight, catalog, runStates, issues, flash, edit, onSelect, onToggleWires }: {
  view: FlowView | null
  issues: Issue[]
  flash: { id: string; n: number } | null
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

  const perNode = useMemo(() => {
    const m: Record<string, NodeIssues> = {}
    for (const i of issues) {
      if (!i.node) continue
      const x = (m[i.node] ??= { errors: 0, warnings: 0, ports: [] })
      if (i.level === 'error') x.errors++; else x.warnings++
      if (i.port) x.ports.push(i.port)
    }
    return m
  }, [issues])
  const badLinks = useMemo(() => new Set(issues.filter(i => i.link).map(i => `${i.link!.from}->${i.link!.to}`)), [issues])

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
        node: n, linked: linked[n.id] ?? [], run: runStates?.[n.id], issues: perNode[n.id],
        flash: flash?.id === n.id ? flash.n : undefined,
        dim: !!q && ![n.label, n.type, ...n.inputs.map(p => p.name)].some(t => t.toLowerCase().includes(q)),
      },
    }))
  }, [view, q, runStates, selection, perNode, flash])
  // Group boxes (behind, rectangle of their nodes) and notes, ids prefixed "group:" / "note:".
  const extras = useMemo<AnyRfNode[]>(() => {
    if (!view) return []
    const out: AnyRfNode[] = []
    for (const g of view.groups ?? []) {
      const members = g.nodes.map(id => byId[id]).filter(Boolean)
      if (!members.length) continue
      const x0 = Math.min(...members.map(n => n.position.x)) - GROUP_PAD
      const y0 = Math.min(...members.map(n => n.position.y)) - GROUP_PAD - GROUP_HEAD
      const x1 = Math.max(...members.map(n => n.position.x + NODE_W)) + GROUP_PAD
      const y1 = Math.max(...members.map(n => n.position.y + nodeHeight(n))) + GROUP_PAD
      out.push({
        id: `${GROUP_PREFIX}${g.id}`, type: 'box', position: { x: x0, y: y0 }, zIndex: -1,
        selected: selection.has(`${GROUP_PREFIX}${g.id}`), draggable: !readOnly,
        data: { label: g.label ?? '', color: g.color, width: x1 - x0, height: y1 - y0, editable: !readOnly,
                onRename: label => edit.onRenameGroup(g.id, label) },
      } as GroupRfNode)
    }
    for (const k of view.notes ?? []) {
      out.push({
        id: `${NOTE_PREFIX}${k.id}`, type: 'note', position: { x: k.pos[0], y: k.pos[1] },
        selected: selection.has(`${NOTE_PREFIX}${k.id}`),
        data: { text: k.text, editable: !readOnly, onText: text => edit.onNoteText(k.id, text) },
      } as NoteRfNode)
    }
    return out
  }, [view, byId, selection, readOnly, edit])
  const all = useMemo<AnyRfNode[]>(() => [...extras, ...derived], [extras, derived])
  const [nodes, setNodes, onNodesChange] = useNodesState<AnyRfNode>(all)
  useEffect(() => { setNodes(all) }, [all, setNodes])
  // Dragging a box moves its nodes along (local), committed at the drop with the box.
  const boxDrag = useRef<{ x: number; y: number; members: Record<string, { x: number; y: number }> } | null>(null)
  // Frame the whole flow once per flow loaded (not on each edit).
  useEffect(() => { if (flowKey) requestAnimationFrame(() => fitView({ padding: 0.15 })) }, [flowKey, fitView])

  // Data links first so the exec chain (the main flow) is drawn on top.
  const edges = useMemo<FlowRfEdge[]>(() => [...(view?.edges ?? [])]
    .sort((a, b) => Number(a.kind === 'exec') - Number(b.kind === 'exec'))
    .map(e => ({
      id: e.id, type: 'flow', source: e.source, target: e.target, selected: edgeSel.includes(e.id),
      sourceHandle: handleId('out', e.sourcePort), targetHandle: handleId('in', e.targetPort),
      data: { kind: e.kind, type: e.type, dim: !!q, straight, conversion: e.conversion,
              bad: e.bad || badLinks.has(`${e.source}.${e.sourcePort}->${e.target}.${e.targetPort}`) },
    })), [view, q, straight, edgeSel, badLinks])

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
      else if (ctrl && k === 'g') { e.preventDefault(); edit.onGroup() }
      else if (!ctrl && !e.altKey && !e.shiftKey && k === 'n') {
        e.preventDefault()
        const p = screenToFlowPosition({ x: mouse.current.cx, y: mouse.current.cy })
        edit.onNote([p.x, p.y])
      }
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
            onNodeDragStart={(_, node) => {
              if (node.type !== 'box') return
              const g = view?.groups?.find(x => `${GROUP_PREFIX}${x.id}` === node.id)
              boxDrag.current = { x: node.position.x, y: node.position.y,
                members: Object.fromEntries((g?.nodes ?? []).filter(id => byId[id]).map(id => [id, { ...byId[id].position }])) }
            }}
            onNodeDrag={(_, node) => {
              const b = boxDrag.current
              if (node.type !== 'box' || !b) return
              const dx = node.position.x - b.x, dy = node.position.y - b.y
              setNodes(ns => ns.map(n => b.members[n.id] ? { ...n, position: { x: b.members[n.id].x + dx, y: b.members[n.id].y + dy } } : n))
            }}
            onNodeDragStop={(_, node, dragged) => {
              const b = boxDrag.current
              boxDrag.current = null
              if (readOnly) return
              const pos: Record<string, [number, number]> = {}
              for (const n of dragged) {
                if (n.type === 'box') {
                  if (b && n.id === node.id) for (const [id, p] of Object.entries(b.members)) pos[id] = [p.x + n.position.x - b.x, p.y + n.position.y - b.y]
                } else pos[n.id.startsWith(NOTE_PREFIX) ? n.id.slice(NOTE_PREFIX.length) : n.id] = [n.position.x, n.position.y]
              }
              edit.onMove(pos)
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
              nodeColor={n => n.type === 'flow' ? FAMILY_INFO[(n as FlowRfNode).data.node.family].color : 'transparent'}
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
