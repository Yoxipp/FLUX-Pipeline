// v1_adapter.ts — read-only adapter: a v1 YAML action (ActionGraph, GET /actions/{name}/graph)
// -> the editor's view model (FlowView). Pure functions, no I/O.
//
// v1 command -> one node (family from the command key, `any` port when the type is unknown),
// v1 steps run in order -> one exec chain (then -> exec), wired parameters -> data links.
// A start node (event family) heads the chain and lists what the runner injects at launch.
// Positions: one column per step, like the old editor (v1 YAML has no positions).

import type { ActionCatalog, ActionGraph, ActionGraphNode, CatalogCommand } from '../../types'
import { toPortType } from './portTypes'
import type { Family, FlowView, FlowViewEdge, FlowViewNode, NodeSpec, PortSpec } from './types'

const COL_W = 320          // node width 240 + room for the links
const ROW_GAP = 28
const HEADER_H = 28
const ROW_H = 20
const START_ID = '__start__'

// v1 command key -> family (02_NODES §1). Unknown keys (team nodes) = action: they may have effects.
const V1_FAMILY: Record<string, Family> = {
  project_context: 'flux', build_output_path: 'flux', select_publish: 'flux', select_dcc_publish: 'flux',
  select_houdini_publish: 'flux', copy_publish: 'flux', notify_activity: 'flux', refresh_component: 'flux',
  refresh_shot_stage: 'flux', usd_check: 'flux', usd_flatten: 'flux', call_function: 'flux',
  copy_file: 'action', move_file: 'action', make_folder: 'action', write_json: 'action', write_text: 'action',
  zip_folder: 'action', convert_image: 'action', conform_texture: 'action', generate_proxy: 'action',
  maya_export: 'dcc', houdini_export: 'dcc',
  format_text: 'operator', join_path: 'operator', log_message: 'operator',
  read_json: 'data', list_files: 'data',
}
const V1_PREFIX: Record<string, string> = { maya_export: 'may', houdini_export: 'hou' }

export function familyOfV1(command: string): Family {
  return V1_FAMILY[command] ?? 'action'
}

export function prefixOfV1(command: string): string | undefined {
  return V1_PREFIX[command]
}

// "select_dcc_publish" -> "SelectDccPublish" (02_NODES §1 labels).
export function pascal(key: string): string {
  return key.split(/[_\s.]+/).filter(Boolean).map(s => s[0].toUpperCase() + s.slice(1)).join('')
}

const wiredRef = (value: unknown): string | null => {
  const from = (value as { from?: string } | null)?.from
  return typeof from === 'string' ? from : null
}

// Output keys of each node: declared outputs + keys read by a wired parameter.
function outputKeys(graph: ActionGraph): Record<string, string[]> {
  const out: Record<string, string[]> = {}
  for (const n of graph.nodes) out[n.id] = [...(n.data.outputs ?? [])]
  for (const n of graph.nodes) for (const p of n.data.params) {
    const ref = p.wired ? wiredRef(p.value) : null
    if (!ref) continue
    const [s, c, key] = ref.split('.')
    const src = `${s}.${c}`
    if (out[src] && key && !out[src].includes(key)) out[src].push(key)
  }
  return out
}

function orderedNodes(graph: ActionGraph): ActionGraphNode[] {
  // Stable: by step index, then by order of appearance inside the step.
  return graph.nodes.map((n, i) => ({ n, i }))
    .sort((a, b) => a.n.data.index - b.n.data.index || a.i - b.i)
    .map(x => x.n)
}

export function nodeHeight(n: Pick<FlowViewNode, 'hasExec' | 'inputs' | 'outputs'>): number {
  return HEADER_H + ROW_H * ((n.hasExec ? 1 : 0) + Math.max(n.inputs.length, n.outputs.length)) + 8
}

function v1Node(n: ActionGraphNode, outs: string[], labels: Record<string, string>): FlowViewNode {
  const inputs: PortSpec[] = n.data.params
    .filter(p => !p.hide || p.wired)
    .map(p => {
      const ref = p.wired ? wiredRef(p.value) : null
      const [s, c, key] = (ref ?? '').split('.')
      return {
        name: p.name,
        type: toPortType(p.type),
        doc_fr: p.tooltip || p.label || undefined,
        doc_en: p.tooltip || p.label || undefined,
        value: ref ? undefined : p.value,
        wiredFrom: ref ? `${labels[`${s}.${c}`] ?? c}.${key}` : undefined,
      }
    })
  return {
    id: n.id,
    type: `v1.${n.data.command}`,
    label: pascal(n.data.command),
    family: familyOfV1(n.data.command),
    prefix: prefixOfV1(n.data.command),
    doc_fr: n.data.doc_fr || n.data.doc,
    doc_en: n.data.doc,
    hasExec: true,
    inputs,
    outputs: outs.map(o => ({ name: o, type: 'any' })),
    position: { x: 0, y: 0 },
    meta: {
      step: n.data.step,
      command: n.data.command,
      ...(n.data.module ? { module: n.data.module } : {}),
      ...(n.data.note ? { note: n.data.note } : {}),
    },
  }
}

function startNode(graph: ActionGraph): FlowViewNode {
  return {
    id: START_ID,
    type: 'event.button',
    label: 'Start',
    family: 'event',
    doc_fr: 'Lancement de l\'action (bouton du Publisher ou appel). Les sorties sont les valeurs injectees par le runner.',
    doc_en: 'Launch of the action (Publisher button or call). Outputs are the values the runner injects.',
    hasExec: false,
    inputs: [],
    outputs: [
      { name: 'then', type: 'exec' },
      ...(graph.inputs ?? []).map(i => ({
        name: i.name, type: 'any',
        doc_fr: `${i.kind === 'context' ? 'Contexte' : 'A l\'execution'} -> ${i.target}`,
        doc_en: `${i.kind === 'context' ? 'Context' : 'Runtime'} -> ${i.target}`,
      })),
    ],
    position: { x: 0, y: 0 },
  }
}

// Columns: start node, then one column per step; nodes stacked inside a column, columns centred.
function placeColumns(cols: FlowViewNode[][]): void {
  const heights = cols.map(c => c.reduce((a, n) => a + nodeHeight(n) + ROW_GAP, -ROW_GAP))
  const tallest = Math.max(0, ...heights)
  cols.forEach((col, ci) => {
    let y = (tallest - heights[ci]) / 2
    for (const n of col) { n.position = { x: ci * COL_W, y }; y += nodeHeight(n) + ROW_GAP }
  })
}

export function adaptV1Action(graph: ActionGraph): FlowView {
  const ordered = orderedNodes(graph)
  const outs = outputKeys(graph)
  const labels = Object.fromEntries(graph.nodes.map(n => [n.id, pascal(n.data.command)]))
  const start = startNode(graph)
  const nodes = ordered.map(n => v1Node(n, outs[n.id] ?? [], labels))
  const byId = Object.fromEntries(nodes.map(n => [n.id, n]))

  const steps = Array.from(new Set(ordered.map(n => n.data.step)))
  placeColumns([[start], ...steps.map(s => nodes.filter(n => n.meta?.step === s))])

  const edges: FlowViewEdge[] = []
  // Exec chain: start -> every command in run order.
  let prev = START_ID
  let prevPort = 'then'
  for (const n of nodes) {
    edges.push({ id: `exec:${prev}->${n.id}`, kind: 'exec', source: prev, sourcePort: prevPort,
                 target: n.id, targetPort: 'exec', type: 'exec' })
    prev = n.id
    prevPort = 'then'
  }
  // Data links: a parameter wired from another command's output.
  for (const n of graph.nodes) for (const p of n.data.params) {
    const ref = p.wired ? wiredRef(p.value) : null
    if (!ref) continue
    const [s, c, key] = ref.split('.')
    const src = `${s}.${c}`
    if (!byId[src] || !key) continue
    edges.push({ id: `data:${src}.${key}->${n.id}.${p.name}`, kind: 'data', source: src, sourcePort: key,
                 target: n.id, targetPort: p.name, type: toPortType(p.type) })
  }

  return {
    name: graph.name,
    description: graph.description_fr || graph.description,
    nodes: [start, ...nodes],
    edges,
    readOnly: true,
    origin: graph.origin,
  }
}

// Catalogue entry as the Shelf and Tab menu show it (P0: v1 commands; P4: v2 nodes, see
// adaptCatalog in v2_adapter.ts).
export interface CatalogEntry {
  type:   string
  label:  string
  family: Family
  icon?:  string
  prefix?: string
  doc_fr?: string
  doc_en?: string
  origin?: string
  aliases: string[]
  shelf?: number | null   // order on the Shelf; null = not on the Shelf
  spec?:  NodeSpec
}

export function adaptV1Catalog(catalog: ActionCatalog | null): CatalogEntry[] {
  return (catalog?.commands ?? []).map((c: CatalogCommand) => ({
    type: `v1.${c.key}`,
    label: pascal(c.key),
    family: familyOfV1(c.key),
    prefix: prefixOfV1(c.key),
    doc_fr: c.doc_fr || c.doc,
    doc_en: c.doc,
    origin: c.origin,
    aliases: [c.key],
  }))
}
