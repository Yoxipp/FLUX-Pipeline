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
// `flash` makes a node blink once (zoom from the Problems panel).
// P4 groups and notes: GroupBox ("group:<id>", drawn behind, follows its nodes, dragging it
// moves them, Ctrl+G) and NoteNode ("note:<id>", N at the mouse); visual only (01 §2).
// Pan: middle button, select: drag on the background. No +/- / frame buttons (2026-10-22).
// Houdini-like (2026-10-23):
// - loop frames (LoopFrame.tsx, "loop:<begin id>"): derived from the view, behind everything;
// - right drag (also Alt / Space + right) zooms around the press point, right / up = in; the
//   context menu is off on the pane; Space + left drag pans;
// - Alt + drag on a node: the original stays, a copy (onDuplicate) lands at the drop;
// - nodes snap to the 18 px dot grid;
// - shaking a dragged node (fast reversals on X) cuts its links (onDisconnect);
// - pressing a linked input picks its link up from the source: dropped on an input it moves
//   there, in the void it is removed (onRelink, one undo entry), on a refused port it stays;
// - Y (hold, or tap to keep it until Y / Echap) = knife: a left drag cuts the links it crosses;
// - runLinks (link values of the run) feed the info card of the nodes.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Background, BackgroundVariant, MiniMap, ReactFlow, useNodesState, useReactFlow,
  type NodeTypes, type EdgeTypes, type Connection as RfConnection, type Edge, type OnSelectionChangeParams,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { toast } from 'sonner'
import { FAMILY_INFO } from './families'
import { FlowEdge, type FlowRfEdge } from './edges/FlowEdge'
import { FlowNode, NODE_W, type FlowRfNode, type NodeIssues, type PortRunValues } from './nodes/FlowNode'
import { LoopFrame, LOOP_PREFIX, loopBlocks, type LoopRfNode } from './LoopFrame'
import { splitRef } from './reducers'
import { GroupBox, GROUP_HEAD, GROUP_PAD, type GroupRfNode } from './GroupBox'
import { NoteNode, type NoteRfNode } from './NoteNode'
import { nodeHeight } from './v1_adapter'
import { handleId, portOfHandle } from './nodes/PortHandle'
import { PortTooltipProvider } from './nodes/PortTooltip'
import { ConnectCtx, type ConnectState } from './nodes/connectState'
import { checkLink, firstCompatible, type PortEnd } from './portTypes'
import { TabMenu } from './TabMenu'
import type { FlowDocLink, FlowView, FlowViewNode, Issue, NodeRunInfo, RunRecord } from './types'
import type { CatalogEntry } from './v1_adapter'
import { useTr } from './useTr'

const nodeTypes: NodeTypes = { flow: FlowNode, box: GroupBox, note: NoteNode, loop: LoopFrame }
type AnyRfNode = FlowRfNode | GroupRfNode | NoteRfNode | LoopRfNode
export const GROUP_PREFIX = 'group:'
export const NOTE_PREFIX = 'note:'
const edgeTypes: EdgeTypes = { flow: FlowEdge }
export const DRAG_MIME = 'application/x-flux-node'
const MIN_ZOOM = 0.15
const MAX_ZOOM = 2              // xyflow default
const ZOOM_SPEED = 0.006        // right drag: zoom x e^(px * speed)
const GRID = 18                 // = Background gap
const SHAKE_PX = 14             // a reversal counts after this much travel (screen px)
const SHAKE_MS = 400
const SHAKE_REVERSALS = 4
const KNIFE_TAP_MS = 250        // Y shorter than this without a cut = knife kept on

type Pt = { x: number; y: number }
const clientX = (ev: MouseEvent | TouchEvent) => 'touches' in ev ? ev.touches[0]?.clientX ?? 0 : ev.clientX
// Segment ab crosses segment cd (proper or touching).
function crosses(a: Pt, b: Pt, c: Pt, d: Pt): boolean {
  const o = (p: Pt, q: Pt, r: Pt) => Math.sign((q.x - p.x) * (r.y - p.y) - (q.y - p.y) * (r.x - p.x))
  const o1 = o(a, b, c), o2 = o(a, b, d), o3 = o(c, d, a), o4 = o(c, d, b)
  return o1 !== o2 && o3 !== o4
}
function polylinesCross(p: Pt[], q: Pt[]): boolean {
  for (let i = 1; i < p.length; i++) for (let j = 1; j < q.length; j++) if (crosses(p[i - 1], p[i], q[j - 1], q[j])) return true
  return false
}

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
  onRelink:    (old: FlowDocLink, to: string | null) => void   // picked-up link moved to `to` or removed
  onDuplicate: (ids: string[], at: [number, number]) => void   // Alt + drag: copy, top-left at `at`
  // Adds a catalogue node at `at`; `link` = the dragged port to link it to.
  onAdd:       (entry: CatalogEntry, at: [number, number], link?: { end: PortEnd; port: string }) => void
  onGroup:     () => void                          // Ctrl+G: box around the selected nodes
  onNote:      (at: [number, number]) => void      // N: note at the mouse
  onRenameGroup: (id: string, label: string) => void
  onNoteText:  (id: string, text: string) => void
}

type TabAt = { x: number; y: number; fx: number; fy: number; from?: { end: PortEnd; type: string } }

export function NetworkPane({ view, flowKey, selection, search, dots, straight, catalog, runStates, runLinks, issues, flash, edit, onSelect, onToggleWires, onEnter, onUp }: {
  view: FlowView | null
  issues: Issue[]
  flash: { id: string; n: number } | null
  flowKey: string              // changes when another flow is loaded: frames it once
  selection: ReadonlySet<string>
  runStates?: Record<string, NodeRunInfo>
  runLinks?: RunRecord['links']
  search: string
  dots: boolean
  straight: boolean
  onToggleWires: () => void
  catalog: CatalogEntry[] | null
  edit: EditActions
  onSelect: (ids: string[]) => void
  onEnter?: (node: FlowViewNode) => void   // double click / Enter on a DCC subflow node (P6a)
  onUp?: () => void                         // U: back to the flow we entered from
}) {
  const { tr, lang } = useTr()
  const { fitView, screenToFlowPosition, getViewport, setViewport } = useReactFlow()
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
  // Run values per node and port, from the link values "a.port->b.port".
  const io = useMemo(() => {
    const m: Record<string, PortRunValues> = {}
    for (const [key, v] of Object.entries(runLinks ?? {})) {
      const [from, to] = key.split('->')
      if (!to) continue
      const [sn, sp] = splitRef(from), [tn, tp] = splitRef(to)
      ;(m[sn] ??= { in: {}, out: {} }).out[sp] = v.value
      ;(m[tn] ??= { in: {}, out: {} }).in[tp] = v.value
    }
    return m
  }, [runLinks])
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
        flash: flash?.id === n.id ? flash.n : undefined, io: io[n.id],
        dim: !!q && ![n.label, n.type, ...n.inputs.map(p => p.name)].some(t => t.toLowerCase().includes(q)),
      },
    }))
  }, [view, q, runStates, selection, perNode, flash, io])
  // Group boxes (behind, rectangle of their nodes) and notes, ids prefixed "group:" / "note:".
  const extras = useMemo<AnyRfNode[]>(() => {
    if (!view) return []
    const out: AnyRfNode[] = []
    // Loop frames first and furthest behind (an outer loop behind its inner ones).
    for (const b of loopBlocks(view)) {
      out.push({
        id: `${LOOP_PREFIX}${b.id}`, type: 'loop', position: { x: b.x, y: b.y }, zIndex: -1 - b.level,
        selectable: false, draggable: false, connectable: false, focusable: false,
        data: { label: b.label, width: b.width, height: b.height, level: b.level },
      } as LoopRfNode)
    }
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
  // Keep the sizes xyflow measured: a node passed without `measured` is hidden and measured
  // again, so every derivation made the whole graph blink. A node being dragged keeps its
  // live position (an edit during the drag, e.g. a shake, must not snap it back).
  useEffect(() => {
    setNodes(cur => {
      const seen = new Map(cur.map(n => [n.id, n]))
      return all.map(n => {
        const c = seen.get(n.id)
        if (!c) return n
        return (c.dragging ? { ...n, measured: c.measured, position: c.position, dragging: true } : { ...n, measured: c.measured }) as AnyRfNode
      })
    })
  }, [all, setNodes])
  // Stable on purpose: xyflow calls onSelectionChange again each time this prop changes, with
  // the selection it holds then. During a render where the editor already selected something
  // (new node, paste, Problems panel) that selection is the stale one: an inline handler sent
  // it back to the editor, which re-derived the nodes, and both sides flipped forever.
  const onSelectionChange = useCallback(({ nodes: sel, edges: esel }: OnSelectionChangeParams) => {
    onSelect(sel.map(n => n.id))
    const ids = esel.map(x => x.id)
    setEdgeSel(cur => cur.length === ids.length && ids.every(id => cur.includes(id)) ? cur : ids)
  }, [onSelect])
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

  // A link picked up from its input (onMouseDownCapture of the port): the drag restarts from
  // its source handle (a mousedown sent to it, xyflow then runs the usual connection), the
  // checks ignore the lifted link, the drop decides (onConnect / onConnectEnd).
  const relink = useRef<{ old: FlowDocLink; done: boolean } | null>(null)
  const [lifted, setLifted] = useState<FlowDocLink | null>(null)
  const liveLinks = useMemo(() => lifted ? links.filter(l => !(l.from === lifted.from && l.to === lifted.to)) : links, [links, lifted])
  const grabLinked = useCallback((end: PortEnd, cx: number, cy: number) => {
    if (readOnly) return false
    const e = [...(view?.edges ?? [])].reverse().find(x => x.target === end.node && x.targetPort === end.port)
    const el = e && wrap.current?.querySelector(
      `.react-flow__handle[data-nodeid="${CSS.escape(e.source)}"][data-handleid="${CSS.escape(handleId('out', e.sourcePort))}"]`)
    if (!e || !el) return false
    const old = { from: `${e.source}.${e.sourcePort}`, to: `${e.target}.${e.targetPort}` }
    relink.current = { old, done: false }
    setLifted(old)
    setTimeout(() => {
      el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, clientX: cx, clientY: cy, button: 0, buttons: 1, view: window }))
      // After xyflow's own mouseup (registered first): a press without drag changes nothing.
      const clear = () => { document.removeEventListener('mouseup', clear); setTimeout(() => { relink.current = null; setLifted(null) }, 0) }
      document.addEventListener('mouseup', clear)
    }, 0)
    return true
  }, [readOnly, view])

  const connectState = useMemo<ConnectState>(() => ({
    editable: !readOnly,
    verdict: end => !drag || (end.node === drag.node && end.port === drag.port && end.side === drag.side) ? null : checkLink(byId, liveLinks, drag, end),
    grabLinked,
  }), [readOnly, drag, byId, liveLinks, grabLinked])

  const endsOf = (c: RfConnection | Edge): [PortEnd, PortEnd] => [
    { node: c.source, port: portOfHandle(c.sourceHandle), side: 'out' },
    { node: c.target, port: portOfHandle(c.targetHandle), side: 'in' },
  ]
  const isValidConnection = useCallback((c: RfConnection | Edge) => checkLink(byId, liveLinks, ...endsOf(c)).status !== 'incompatible', [byId, liveLinks])

  const deleteEdges = useCallback(() => {
    const gone = (view?.edges ?? []).filter(e => edgeSel.includes(e.id))
      .map(e => ({ from: `${e.source}.${e.sourcePort}`, to: `${e.target}.${e.targetPort}` }))
    if (gone.length) { edit.onDisconnect(gone); setEdgeSel([]) }
    return gone.length > 0
  }, [view, edgeSel, edit])

  // Knife (Y): `cut` = the stroke in client coordinates while the left button is down.
  const [knife, setKnife] = useState(false)
  const [cut, setCut] = useState<Pt[] | null>(null)
  const cutting = useRef(false)
  const knifeKey = useRef({ held: false, sticky: false, at: 0, used: false })
  const knifeOff = useCallback(() => { knifeKey.current = { held: false, sticky: false, at: 0, used: false }; cutting.current = false; setKnife(false); setCut(null) }, [])
  useEffect(() => { if (readOnly) knifeOff() }, [readOnly, knifeOff])
  const cutLinks = useCallback((stroke: Pt[]) => {
    if (stroke.length < 2 || !view || !wrap.current) return
    const xs = stroke.map(p => p.x), ys = stroke.map(p => p.y)
    const box = { x0: Math.min(...xs), x1: Math.max(...xs), y0: Math.min(...ys), y1: Math.max(...ys) }
    const gone: FlowDocLink[] = []
    for (const e of view.edges) {
      const path = wrap.current.querySelector<SVGPathElement>(`.react-flow__edge[data-id="${CSS.escape(e.id)}"] path.react-flow__edge-path`)
      const m = path?.getScreenCTM()
      if (!path || !m) continue
      // Same path as drawn (FlowEdge), sampled every ~6 units, then to client coordinates.
      const len = path.getTotalLength()
      const n = Math.max(8, Math.ceil(len / 6))
      const poly: Pt[] = []
      for (let i = 0; i <= n; i++) {
        const p = path.getPointAtLength((len * i) / n)
        poly.push({ x: m.a * p.x + m.c * p.y + m.e, y: m.b * p.x + m.d * p.y + m.f })
      }
      const px = poly.map(p => p.x), py = poly.map(p => p.y)
      if (Math.max(...px) < box.x0 || Math.min(...px) > box.x1 || Math.max(...py) < box.y0 || Math.min(...py) > box.y1) continue
      if (polylinesCross(stroke, poly)) gone.push({ from: `${e.source}.${e.sourcePort}`, to: `${e.target}.${e.targetPort}` })
    }
    if (gone.length) { edit.onDisconnect(gone); setEdgeSel([]) }
  }, [view, edit])

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
      else if (e.key === 'Escape') { setTab(null); onSelect([]); setEdgeSel([]); knifeOff() }
      else if (!ctrl && !e.altKey && !e.shiftKey && k === 'u' && onUp) { e.preventDefault(); onUp() }
      else if (e.key === 'Enter' && onEnter && selection.size === 1) {
        const one = byId[[...selection][0]]
        if (one?.spec?.subflow) { e.preventDefault(); onEnter(one) }
      }
      else if (ctrl && k === 'a') { e.preventDefault(); edit.onSelectAll() }
      else if (ctrl && k === 'c') { e.preventDefault(); edit.onCopy() }
      else if (readOnly) return
      else if (ctrl && k === 'g') { e.preventDefault(); edit.onGroup() }
      else if (!ctrl && !e.altKey && !e.shiftKey && k === 'y') {
        e.preventDefault()
        if (e.repeat) return
        if (knifeKey.current.sticky) { knifeOff(); return }
        knifeKey.current = { held: true, sticky: false, at: performance.now(), used: false }
        setKnife(true)
      }
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
    const onKeyUp = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() !== 'y') return
      const kk = knifeKey.current
      if (!kk.held) return
      kk.held = false
      if (!kk.used && performance.now() - kk.at < KNIFE_TAP_MS) kk.sticky = true   // a tap keeps it on
      else if (!cutting.current) knifeOff()
    }
    window.addEventListener('keydown', onKey)
    window.addEventListener('keyup', onKeyUp)
    window.addEventListener('blur', knifeOff)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('keyup', onKeyUp)
      window.removeEventListener('blur', knifeOff)
    }
  }, [fitView, screenToFlowPosition, onSelect, onToggleWires, edit, readOnly, selection, deleteEdges, knifeOff, onEnter, onUp, byId])

  // Right drag = zoom around the press point (also with Alt or Space held: the press never
  // reaches xyflow, so Space + right does not pan). No context menu on the graph.
  useEffect(() => {
    const el = wrap.current
    if (!el) return
    const inGraph = (t: EventTarget | null) => t instanceof Element && !!t.closest('.react-flow, .flow-knife') && !typing(t)
    const down = (e: MouseEvent) => {
      if (e.button !== 2 || !inGraph(e.target)) return
      e.preventDefault(); e.stopPropagation()
      const r = (el.querySelector('.react-flow') ?? el).getBoundingClientRect()
      const ax = e.clientX - r.left, ay = e.clientY - r.top
      const v0 = getViewport()
      const fx = (ax - v0.x) / v0.zoom, fy = (ay - v0.y) / v0.zoom
      const move = (m: MouseEvent) => {
        const d = (m.clientX - e.clientX) - (m.clientY - e.clientY)
        const zoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, v0.zoom * Math.exp(d * ZOOM_SPEED)))
        setViewport({ x: ax - fx * zoom, y: ay - fy * zoom, zoom })
      }
      const up = (u: MouseEvent) => {
        if (u.button !== 2) return
        window.removeEventListener('mousemove', move)
        window.removeEventListener('mouseup', up)
      }
      window.addEventListener('mousemove', move)
      window.addEventListener('mouseup', up)
    }
    const stopRight = (e: PointerEvent) => { if (e.button === 2 && inGraph(e.target)) e.stopPropagation() }
    const menu = (e: MouseEvent) => { if (inGraph(e.target)) e.preventDefault() }
    el.addEventListener('mousedown', down, true)
    el.addEventListener('pointerdown', stopRight, true)
    el.addEventListener('contextmenu', menu)
    return () => {
      el.removeEventListener('mousedown', down, true)
      el.removeEventListener('pointerdown', stopRight, true)
      el.removeEventListener('contextmenu', menu)
    }
  }, [getViewport, setViewport])

  // Alt + drag (duplicate) and shake (cut the links) of the dragged nodes.
  const dup = useRef<Record<string, { x: number; y: number }> | null>(null)
  const shake = useRef<{ x: number; dir: number; ext: number; times: number[]; done: boolean } | null>(null)
  const onShake = useCallback((dragged: { id: string; type?: string }[]) => {
    const ids = new Set(dragged.filter(n => n.type === 'flow').map(n => n.id))
    const gone = links.filter(l => ids.has(splitRef(l.from)[0]) !== ids.has(splitRef(l.to)[0]))
    if (!gone.length) return
    edit.onDisconnect(gone)
    toast.info(tr(`${gone.length} lien(s) coupe(s)`, `${gone.length} link(s) cut`), { duration: 1500 })
  }, [links, edit, tr])

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
            onSelectionChange={onSelectionChange}
            onNodeDoubleClick={(_ev, n) => { const v = byId[n.id]; if (v?.spec?.subflow && onEnter) onEnter(v) }}
            onNodeDragStart={(ev, node, dragged) => {
              dup.current = null
              shake.current = { x: clientX(ev), dir: 0, ext: clientX(ev), times: [], done: false }
              if (!readOnly && ev.altKey && node.type === 'flow') {
                // Alt: the nodes move as a preview, put back at the drop, the copy lands there.
                dup.current = Object.fromEntries(dragged.map(n => [n.id, { ...n.position }]))
                return
              }
              if (node.type !== 'box') return
              const g = view?.groups?.find(x => `${GROUP_PREFIX}${x.id}` === node.id)
              boxDrag.current = { x: node.position.x, y: node.position.y,
                members: Object.fromEntries((g?.nodes ?? []).filter(id => byId[id]).map(id => [id, { ...byId[id].position }])) }
            }}
            onNodeDrag={(ev, node, dragged) => {
              const s = shake.current
              if (s && !s.done && !dup.current && !readOnly && node.type === 'flow') {
                const x = clientX(ev), dir = Math.sign(x - s.x)
                s.x = x
                if (dir && !s.dir) { s.dir = dir; s.ext = x }
                else if (dir === s.dir) s.ext = dir > 0 ? Math.max(s.ext, x) : Math.min(s.ext, x)
                else if (dir && Math.abs(x - s.ext) >= SHAKE_PX) {
                  const now = performance.now()
                  s.times = [...s.times.filter(t => now - t < SHAKE_MS), now]
                  s.dir = dir; s.ext = x
                  if (s.times.length >= SHAKE_REVERSALS) { s.done = true; onShake(dragged) }
                }
              }
              const b = boxDrag.current
              if (node.type !== 'box' || !b) return
              const dx = node.position.x - b.x, dy = node.position.y - b.y
              setNodes(ns => ns.map(n => b.members[n.id] ? { ...n, position: { x: b.members[n.id].x + dx, y: b.members[n.id].y + dy } } : n))
            }}
            onNodeDragStop={(_, node, dragged) => {
              const b = boxDrag.current
              boxDrag.current = null
              shake.current = null
              const start = dup.current
              dup.current = null
              if (readOnly) return
              if (start) {
                const flows = dragged.filter(n => n.type === 'flow')
                setNodes(ns => ns.map(n => start[n.id] ? { ...n, position: start[n.id] } as AnyRfNode : n))
                if (flows.length) edit.onDuplicate(flows.map(n => n.id),
                  [Math.min(...flows.map(n => n.position.x)), Math.min(...flows.map(n => n.position.y))])
                return
              }
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
              const r = checkLink(byId, liveLinks, ...endsOf(c))
              if (r.status === 'incompatible' || !r.from || !r.to) return
              const lift = relink.current
              if (lift) {
                lift.done = true
                if (r.from !== lift.old.from || r.to !== lift.old.to) edit.onRelink(lift.old, r.to)
              } else edit.onConnect(r.from, r.to)
            }}
            onConnectEnd={(ev, state) => {
              const from = drag
              setDrag(null)
              const lift = relink.current
              if (lift) {
                // Picked-up link: removed when dropped away from a port; kept on a refused port.
                relink.current = null
                setLifted(null)
                if (!lift.done && !readOnly && !(state.toHandle && state.isValid === false)) edit.onRelink(lift.old, null)
                return
              }
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
            panOnDrag={[1]}
            panActivationKeyCode="Space"
            snapToGrid
            snapGrid={[GRID, GRID]}
            minZoom={MIN_ZOOM}
            maxZoom={MAX_ZOOM}
            proOptions={{ hideAttribution: true }}
            colorMode="dark"
          >
            {dots && <Background variant={BackgroundVariant.Dots} gap={GRID} size={1} color="var(--rule-2)" />}
            <MiniMap
              pannable zoomable
              nodeColor={n => n.type === 'flow' ? FAMILY_INFO[(n as FlowRfNode).data.node.family].color : 'transparent'}
              maskColor="color-mix(in oklch, var(--bg-deep) 70%, transparent)"
              style={{ background: 'var(--paper)' }}
            />
          </ReactFlow>
        </ConnectCtx.Provider>
      </PortTooltipProvider>
      {knife && (
        <div
          className="flow-knife"
          onPointerDown={e => {
            if (e.button !== 0) return
            e.preventDefault()
            e.currentTarget.setPointerCapture(e.pointerId)
            cutting.current = true
            setCut([{ x: e.clientX, y: e.clientY }])
          }}
          onPointerMove={e => {
            if (!cutting.current) return
            const p = { x: e.clientX, y: e.clientY }
            setCut(c => {
              if (!c) return c
              const l = c[c.length - 1]
              return Math.hypot(p.x - l.x, p.y - l.y) < 3 ? c : [...c, p]
            })
          }}
          onPointerUp={e => {
            if (!cutting.current || e.button !== 0) return
            cutting.current = false
            const stroke = [...(cut ?? []), { x: e.clientX, y: e.clientY }]
            setCut(null)
            cutLinks(stroke)
            const kk = knifeKey.current
            kk.used = true
            if (!kk.held && !kk.sticky) knifeOff()
          }}
        >
          {cut && cut.length > 1 && (() => {
            const r = wrap.current?.getBoundingClientRect()
            const pts = cut.map(p => `${p.x - (r?.left ?? 0)},${p.y - (r?.top ?? 0)}`).join(' ')
            return <svg><polyline points={pts} fill="none" stroke="var(--err)" strokeWidth={1.5} strokeDasharray="5 3" strokeLinecap="round" /></svg>
          })()}
        </div>
      )}
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
