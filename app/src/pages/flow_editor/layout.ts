// layout.ts — the Layout button (03_EDITEUR §4), the only thing that arranges the graph.
// Layers left to right: rank = longest path over the exec links, then the data links
// (back links of a loop are ignored); inside a column, nodes are sorted by the barycentre
// of their sources (2 passes, like the old P4 editor's layout()) and centred vertically.
// Returns positions; the editor applies them with moveNodes (one undo entry) then frames.

import { nodeOfRef, splitRef, EXEC_IN } from './reducers'
import type { FlowDoc } from './types'

const COL_W = 300
const ROW_GAP = 40
const DEFAULT_H = 110

export function layoutFlow(doc: FlowDoc, heightOf: (id: string) => number = () => DEFAULT_H): Record<string, [number, number]> {
  const ids = Object.keys(doc.nodes)
  const links = doc.links.filter(l => doc.nodes[nodeOfRef(l.from)] && doc.nodes[nodeOfRef(l.to)])
  const exec = links.filter(l => splitRef(l.to)[1] === EXEC_IN)
  const data = links.filter(l => splitRef(l.to)[1] !== EXEC_IN)

  const rank: Record<string, number> = Object.fromEntries(ids.map(id => [id, 0]))
  // Bellman-Ford style relaxation, bounded so a cycle cannot loop forever.
  const relax = (list: typeof links) => {
    for (let pass = 0; pass < ids.length; pass++) {
      let moved = false
      for (const l of list) {
        const a = nodeOfRef(l.from), b = nodeOfRef(l.to)
        if (rank[b] < rank[a] + 1 && rank[a] + 1 < ids.length) { rank[b] = rank[a] + 1; moved = true }
      }
      if (!moved) break
    }
  }
  relax(exec)
  relax([...exec, ...data])

  const cols: string[][] = []
  for (const id of [...ids].sort((a, b) => (doc.nodes[a].pos?.[1] ?? 0) - (doc.nodes[b].pos?.[1] ?? 0))) (cols[rank[id]] ??= []).push(id)
  const dense = cols.filter(Boolean)

  const centerY: Record<string, number> = {}
  const heights = dense.map(col => col.reduce((a, id) => a + heightOf(id) + ROW_GAP, -ROW_GAP))
  const tallest = Math.max(0, ...heights)
  const place = (col: string[], ci: number) => {
    let y = (tallest - heights[ci]) / 2
    for (const id of col) { centerY[id] = y + heightOf(id) / 2; y += heightOf(id) + ROW_GAP }
  }
  dense.forEach(place)
  const sources: Record<string, string[]> = {}
  for (const l of links) (sources[nodeOfRef(l.to)] ??= []).push(nodeOfRef(l.from))
  for (let pass = 0; pass < 2; pass++) {
    dense.forEach((col, ci) => {
      if (ci === 0) return
      const bary = (id: string) => {
        const s = (sources[id] ?? []).filter(x => x in centerY)
        return s.length ? s.reduce((a, x) => a + centerY[x], 0) / s.length : centerY[id]
      }
      col.sort((a, b) => bary(a) - bary(b))
      place(col, ci)
    })
  }

  const out: Record<string, [number, number]> = {}
  dense.forEach((col, ci) => { for (const id of col) out[id] = [ci * COL_W, Math.round(centerY[id] - heightOf(id) / 2)] })
  return out
}
