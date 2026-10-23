// clipboard.ts — copy / paste of nodes (03_EDITEUR §4). The system clipboard carries JSON
// tagged `flux_flow_clip: 1`: the selected nodes, the links between them (links to the
// outside are dropped) and the selected notes. Works between flows and between windows.
// On paste the ids are regenerated (free in the target flow) and the block is moved so its
// top-left corner lands at the mouse. Pure functions; the editor does the clipboard I/O.

import { nextId, nextNodeId, nodeOfRef, splitRef } from './reducers'
import type { FlowDoc, FlowDocLink, FlowDocNode, FlowNote } from './types'

export const CLIP_TAG = 'flux_flow_clip'

export interface FlowClip {
  [CLIP_TAG]: 1
  nodes: Record<string, FlowDocNode>
  links: FlowDocLink[]
  notes: FlowNote[]
}

export interface PasteBlock {
  nodes: Record<string, FlowDocNode>
  links: FlowDocLink[]
  notes: FlowNote[]
  ids:   string[]          // new ids, to select the pasted block
}

export function copySelection(doc: FlowDoc, ids: Iterable<string>): FlowClip | null {
  const want = new Set(ids)
  const nodes = Object.fromEntries(Object.entries(doc.nodes).filter(([id]) => want.has(id)))
  const notes = (doc.notes ?? []).filter(n => want.has(n.id))
  if (!Object.keys(nodes).length && !notes.length) return null
  const links = doc.links.filter(l => nodes[nodeOfRef(l.from)] && nodes[nodeOfRef(l.to)])
  return { [CLIP_TAG]: 1, nodes, links, notes }
}

export const clipToText = (clip: FlowClip) => JSON.stringify(clip, null, 2)

export function parseClip(text: string): FlowClip | null {
  try {
    const v = JSON.parse(text)
    if (!v || v[CLIP_TAG] !== 1 || typeof v.nodes !== 'object' || v.nodes === null) return null
    return { [CLIP_TAG]: 1, nodes: v.nodes, links: Array.isArray(v.links) ? v.links : [], notes: Array.isArray(v.notes) ? v.notes : [] }
  } catch { return null }
}

export function pasteBlock(doc: FlowDoc, clip: FlowClip, at: [number, number]): PasteBlock {
  const entries = Object.entries(clip.nodes)
  const xs = [...entries.map(([, n]) => n.pos?.[0] ?? 0), ...clip.notes.map(n => n.pos[0])]
  const ys = [...entries.map(([, n]) => n.pos?.[1] ?? 0), ...clip.notes.map(n => n.pos[1])]
  const dx = at[0] - Math.min(...xs)
  const dy = at[1] - Math.min(...ys)
  const shift = (p: [number, number] | undefined): [number, number] => [Math.round((p?.[0] ?? 0) + dx), Math.round((p?.[1] ?? 0) + dy)]

  const taken = new Set<string>()
  const rename: Record<string, string> = {}
  const nodes: Record<string, FlowDocNode> = {}
  for (const [old, n] of entries) {
    const id = nextNodeId(doc, taken)
    taken.add(id)
    rename[old] = id
    nodes[id] = { ...n, pos: shift(n.pos) }
  }
  const remap = (ref: string) => { const [n, p] = splitRef(ref); return `${rename[n]}.${p}` }
  const links = clip.links.filter(l => rename[nodeOfRef(l.from)] && rename[nodeOfRef(l.to)])
                          .map(l => ({ from: remap(l.from), to: remap(l.to) }))
  const noteIds = (doc.notes ?? []).map(n => n.id)
  const notes = clip.notes.map(n => {
    const id = nextId(noteIds, 'k', taken)
    taken.add(id)
    return { ...n, id, pos: shift(n.pos) }
  })
  return { nodes, links, notes, ids: [...Object.keys(nodes), ...notes.map(n => n.id)] }
}
