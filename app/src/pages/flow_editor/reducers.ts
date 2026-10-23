// reducers.ts — pure editing actions on a FlowDoc (03_EDITEUR §9). Each one returns a new
// document sharing what it does not touch, or the same object when nothing changes (so the
// store pushes no undo entry). No relayout: a node keeps the pos it is given (03 §4).
// Links are "<node>.<port>" refs (01 §2). The "exec" input accepts several links; a data
// input has one: a new link replaces the old one (03 §5). Type checks live in portTypes
// (front, while dragging) and in the backend validation (the reference).
// Scope: the top-level network (a subnet's inner network is edited from P6).

import type { FlowDoc, FlowDocLink, FlowDocNode, FlowGroup, FlowNote } from './types'

export const EXEC_IN = 'exec'
const NODE_ID_MAX = 31   // NODE_ID_RE in model.py: ^[a-z][a-z0-9_]{0,30}$

export function splitRef(ref: string): [string, string] {
  const i = ref.indexOf('.')
  return i < 0 ? [ref, ''] : [ref.slice(0, i), ref.slice(i + 1)]
}

export const nodeOfRef = (ref: string) => splitRef(ref)[0]
const sameLink = (a: FlowDocLink, b: FlowDocLink) => a.from === b.from && a.to === b.to
const roundPos = (p: [number, number]): [number, number] => [Math.round(p[0]), Math.round(p[1])]

// First free id "<prefix><n>" (n1, n2...), also free of the ids in `taken`.
export function nextId(used: Iterable<string>, prefix = 'n', taken: Set<string> = new Set()): string {
  const all = new Set([...used, ...taken])
  for (let i = 1; ; i++) {
    const id = `${prefix}${i}`.slice(0, NODE_ID_MAX)
    if (!all.has(id)) return id
  }
}

export const nextNodeId = (doc: FlowDoc, taken?: Set<string>) => nextId(Object.keys(doc.nodes ?? {}), 'n', taken)

// -- nodes ----------------------------------------------------------------------

export function addNode(doc: FlowDoc, id: string, node: FlowDocNode): FlowDoc {
  if (doc.nodes[id]) return doc
  return { ...doc, nodes: { ...doc.nodes, [id]: { params: {}, ...node, pos: roundPos(node.pos ?? [0, 0]) } } }
}

export function moveNodes(doc: FlowDoc, positions: Record<string, [number, number]>): FlowDoc {
  let nodes: Record<string, FlowDocNode> | null = null
  let notes: FlowNote[] | null = null
  for (const [id, raw] of Object.entries(positions)) {
    const pos = roundPos(raw)
    const n = doc.nodes[id]
    if (n) {
      if (n.pos && n.pos[0] === pos[0] && n.pos[1] === pos[1]) continue
      ;(nodes ??= { ...doc.nodes })[id] = { ...n, pos }
      continue
    }
    const k = (notes ?? doc.notes ?? []).findIndex(x => x.id === id)
    if (k < 0) continue
    const note = (notes ?? doc.notes!)[k]
    if (note.pos[0] === pos[0] && note.pos[1] === pos[1]) continue
    ;(notes ??= [...doc.notes!])[k] = { ...note, pos }
  }
  if (!nodes && !notes) return doc
  return { ...doc, ...(nodes ? { nodes } : {}), ...(notes ? { notes } : {}) }
}

// Removes nodes and notes (ids of either), their links and their group memberships.
export function removeItems(doc: FlowDoc, ids: Iterable<string>): FlowDoc {
  const gone = new Set(ids)
  const nodeIds = Object.keys(doc.nodes).filter(id => gone.has(id))
  const noteHit = (doc.notes ?? []).some(n => gone.has(n.id))
  if (!nodeIds.length && !noteHit) return doc
  const nodes = { ...doc.nodes }
  for (const id of nodeIds) delete nodes[id]
  const out: FlowDoc = { ...doc, nodes }
  if (nodeIds.length) {
    out.links = doc.links.filter(l => !gone.has(nodeOfRef(l.from)) && !gone.has(nodeOfRef(l.to)))
    if (doc.groups) out.groups = doc.groups.map(g => g.nodes.some(n => gone.has(n)) ? { ...g, nodes: g.nodes.filter(n => !gone.has(n)) } : g)
  }
  if (noteHit) out.notes = doc.notes!.filter(n => !gone.has(n.id))
  return out
}

export function setParam(doc: FlowDoc, id: string, name: string, value: unknown): FlowDoc {
  const n = doc.nodes[id]
  if (!n) return doc
  const params = { ...(n.params ?? {}) }
  if (value === undefined) {
    if (!(name in params)) return doc
    delete params[name]
  } else {
    if (Object.is(params[name], value)) return doc
    params[name] = value
  }
  return { ...doc, nodes: { ...doc.nodes, [id]: { ...n, params } } }
}

export function setNodeFields(doc: FlowDoc, id: string, patch: Partial<Pick<FlowDocNode, 'label' | 'bypass' | 'type'>>): FlowDoc {
  const n = doc.nodes[id]
  if (!n || Object.entries(patch).every(([k, v]) => (n as unknown as Record<string, unknown>)[k] === v)) return doc
  const next = { ...n, ...patch }
  if (next.label === '') delete next.label
  if (next.bypass === false) delete next.bypass
  return { ...doc, nodes: { ...doc.nodes, [id]: next } }
}

// -- links ----------------------------------------------------------------------

export function connect(doc: FlowDoc, from: string, to: string): FlowDoc {
  const link = { from, to }
  if (doc.links.some(l => sameLink(l, link))) return doc
  if (!doc.nodes[nodeOfRef(from)] || !doc.nodes[nodeOfRef(to)] || nodeOfRef(from) === nodeOfRef(to)) return doc
  const exec = splitRef(to)[1] === EXEC_IN
  const kept = exec ? doc.links : doc.links.filter(l => l.to !== to)
  return { ...doc, links: [...kept, link] }
}

export function disconnect(doc: FlowDoc, links: FlowDocLink[]): FlowDoc {
  const kept = doc.links.filter(l => !links.some(x => sameLink(l, x)))
  return kept.length === doc.links.length ? doc : { ...doc, links: kept }
}

// -- flow fields, groups, notes -------------------------------------------------

type FlowFields = Pick<FlowDoc, 'label' | 'description' | 'run_policy' | 'interface' | 'variables' | 'node_type'>

export function setFlowFields(doc: FlowDoc, patch: Partial<FlowFields>): FlowDoc {
  const cur = doc as unknown as Record<string, unknown>
  if (Object.entries(patch).every(([k, v]) => cur[k] === v)) return doc
  const next = { ...doc, ...patch } as FlowDoc & Record<string, unknown>
  for (const [k, v] of Object.entries(patch)) if (v === undefined) delete next[k]
  return next
}

export function upsertGroup(doc: FlowDoc, group: FlowGroup): FlowDoc {
  const list = doc.groups ?? []
  const k = list.findIndex(g => g.id === group.id)
  return { ...doc, groups: k < 0 ? [...list, group] : list.map((g, i) => i === k ? group : g) }
}

export function removeGroup(doc: FlowDoc, id: string): FlowDoc {
  if (!(doc.groups ?? []).some(g => g.id === id)) return doc
  return { ...doc, groups: doc.groups!.filter(g => g.id !== id) }
}

export function upsertNote(doc: FlowDoc, note: FlowNote): FlowDoc {
  const list = doc.notes ?? []
  const k = list.findIndex(n => n.id === note.id)
  return { ...doc, notes: k < 0 ? [...list, { ...note, pos: roundPos(note.pos) }] : list.map((n, i) => i === k ? note : n) }
}

// -- paste ----------------------------------------------------------------------

// Adds a block of nodes, links and notes whose ids are already free (clipboard.ts).
export function insertBlock(doc: FlowDoc, block: { nodes: Record<string, FlowDocNode>; links: FlowDocLink[]; notes?: FlowNote[] }): FlowDoc {
  if (!Object.keys(block.nodes).length && !block.notes?.length) return doc
  return {
    ...doc,
    nodes: { ...doc.nodes, ...block.nodes },
    links: [...doc.links, ...block.links.filter(l => !doc.links.some(x => sameLink(l, x)))],
    ...(block.notes?.length ? { notes: [...(doc.notes ?? []), ...block.notes] } : {}),
  }
}
