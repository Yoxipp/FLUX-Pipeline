// v2_adapter.ts — read-only adapter: a v2 flow document (GET /flows/{name}, 01 §2) -> the
// editor's view model (FlowView). Pure functions, no I/O.
//
// P1: the v2 node registry holds no node yet (P2 / P3), so ports come from the document:
// flux.legacy_command / flux.call_function (migrated v1, 01 §15) carry them in
// params.ports {inputs, outputs}; any other node gets the ports its links use, plus one
// greyed input per literal param. Exec: "exec" in, "then" / "on_error" / branches out.
// Positions are the stored pos (the migration lays them out once).
// P4: with the catalogue (GET /flows/catalog), a known node takes its ports from its spec:
// exec input first, inputs, then every param (each param is promotable to an input, 02 §1,
// like validate.py), outputs with the exec ones first. Unknown types keep the P1 fallback.
// Also adaptCatalog: NodeSpec -> CatalogEntry for the Shelf, the Tab menu and the palette.
// Ports carry choices / wirable / tokens. A param with wirable false (constant, e.g. the
// Path value) is not an input port: it goes to node.constants, edited in Params only.

import { FAMILIES } from './families'
import { familyOfV1, pascal, prefixOfV1, type CatalogEntry } from './v1_adapter'
import { editorConnect } from './portTypes'
import { flagOn } from './destructive'
import type { CatalogPort, Family, FlowCatalog, FlowDoc, FlowDocNode, FlowView, FlowViewEdge, FlowViewNode, NodeSpec, PortSpec, PortType } from './types'

export type SpecIndex = Record<string, NodeSpec>

export function adaptCatalog(c: FlowCatalog): CatalogEntry[] {
  return c.nodes.map(s => ({
    type: s.type, label: s.label, family: (FAMILIES.includes(s.family) ? s.family : 'action') as Family,
    icon: s.icon || undefined, doc_fr: s.doc_fr, doc_en: s.doc_en,
    origin: s.source === 'team' ? 'equipe' : undefined, aliases: s.aliases, shelf: s.shelf, spec: s,
  }))
}

const toPort = (p: CatalogPort, value?: unknown): PortSpec => ({
  name: p.name, type: p.type, required: p.required, doc_fr: p.doc_fr, doc_en: p.doc_en,
  example: p.example === null || p.example === undefined ? undefined : String(p.example),
  value: value !== undefined ? value : p.default ?? undefined,
  choices: Array.isArray(p.choices) ? p.choices : undefined,
  wirable: p.wirable === false ? false : undefined,
  tokens: p.tokens || undefined,
  choiceLabels: p.choice_labels || undefined,
  reserved: p.reserved || undefined,
  default: p.default ?? undefined,
  when: p.when || undefined,
})

function specNode(id: string, node: FlowDocNode, spec: SpecIndex[string]): FlowViewNode {
  const params = node.params ?? {}
  const inputs: PortSpec[] = []
  const constants: PortSpec[] = []
  const seen = new Set<string>()
  const add = (p: CatalogPort) => {
    if (seen.has(p.name)) return
    seen.add(p.name)
    ;(p.wirable === false ? constants : inputs).push(toPort(p, p.type === 'exec' ? undefined : params[p.name]))
  }
  spec.inputs.filter(p => p.type === 'exec').forEach(add)
  spec.inputs.filter(p => p.type !== 'exec').forEach(add)
  spec.params.forEach(add)
  const outputs = [...spec.outputs.filter(p => p.type === 'exec'), ...spec.outputs.filter(p => p.type !== 'exec')].map(p => toPort(p))
  // R1 retake 9: a FlowCall shows the interface of the called flow (params.ports, filled by
  // the Params pane from that flow): one input per interface input, one output per output.
  if (node.type === 'subflow.flow_call') {
    const ports = (params.ports ?? {}) as Ports
    for (const [name, type] of Object.entries(ports.inputs ?? {})) {
      if (seen.has(name)) continue
      seen.add(name)
      inputs.push({ name, type, value: params[name], doc_fr: 'Entree du flow appele', doc_en: 'Input of the called flow' })
    }
    for (const [name, type] of Object.entries(ports.outputs ?? {})) {
      if (outputs.some(o => o.name === name)) continue
      outputs.push({ name, type, doc_fr: 'Sortie du flow appele (son FlowOutput)', doc_en: 'Output of the called flow (its FlowOutput)' })
    }
  }
  const meta: Record<string, string> = { type: node.type }
  if (node.label) meta.step = node.label
  if (node.bypass) meta.bypass = 'true'
  return {
    id, type: node.type, label: node.label || spec.label,
    family: (FAMILIES.includes(spec.family) ? spec.family : 'action') as Family,
    icon: spec.icon || undefined, doc_fr: spec.doc_fr, doc_en: spec.doc_en,
    hasExec: false, inputs, outputs, constants: constants.length ? constants : undefined,
    position: { x: node.pos?.[0] ?? 0, y: node.pos?.[1] ?? 0 }, meta, spec,
    destructive: !node.bypass && flagOn(spec.destructive, spec, params),
  }
}

const LEGACY_TYPES = new Set(['flux.legacy_command', 'flux.call_function'])
const EXEC_OUTS = new Set(['then', 'on_error', 'else', 'default', 'done'])

type Ports = { inputs?: Record<string, string>; outputs?: Record<string, string> }

function splitRef(ref: string): [string, string] {
  const i = ref.indexOf('.')
  return [ref.slice(0, i), ref.slice(i + 1)]
}

const isExecOut = (port: string) => EXEC_OUTS.has(port) || port.startsWith('case_')

function familyOf(node: FlowDocNode): Family {
  if (node.type === 'flux.legacy_command') return familyOfV1(String(node.params?.command ?? ''))
  const head = node.type.split('.')[0] as Family
  return FAMILIES.includes(head) ? head : 'action'
}

function labelOf(node: FlowDocNode): string {
  if (node.type === 'flux.legacy_command') return pascal(String(node.params?.command ?? 'LegacyCommand'))
  return pascal(node.type.split('.').slice(1).join('_') || node.type)
}

function v2Node(id: string, node: FlowDocNode, flow: FlowDoc): FlowViewNode {
  const params = node.params ?? {}
  const inputs: PortSpec[] = []
  const outputs: PortSpec[] = []
  const links = flow.links ?? []
  const addIn = (name: string, type: PortType, value?: unknown) => {
    if (!inputs.some(p => p.name === name)) inputs.push({ name, type, value })
  }
  const addOut = (name: string, type: PortType) => {
    if (!outputs.some(p => p.name === name)) outputs.push({ name, type })
  }

  if (LEGACY_TYPES.has(node.type)) {
    const ports = (params.ports ?? {}) as Ports
    const literals = (params.params ?? params.args ?? {}) as Record<string, unknown>
    for (const [name, type] of Object.entries(ports.inputs ?? {})) addIn(name, type)
    for (const [name, value] of Object.entries(literals)) addIn(name, 'any', value)
    for (const [name, type] of Object.entries(ports.outputs ?? {})) addOut(name, type)
  } else {
    for (const l of links) {
      const [fromNode, fromPort] = splitRef(l.from)
      const [toNode, toPort] = splitRef(l.to)
      if (toNode === id && toPort !== 'exec') addIn(toPort, 'any')
      if (fromNode === id && !isExecOut(fromPort)) addOut(fromPort, 'any')
    }
    for (const [name, value] of Object.entries(params)) addIn(name, 'any', value)
  }

  const execIn = links.some(l => l.to === `${id}.exec`)
  const execOut = links.some(l => { const [n, p] = splitRef(l.from); return n === id && isExecOut(p) })
  const meta: Record<string, string> = { type: node.type }
  if (node.label) meta.step = node.label
  if (typeof params.command === 'string') meta.command = params.command
  if (typeof params.function === 'string') meta.function = params.function
  if (node.bypass) meta.bypass = 'true'
  return {
    id,
    type: node.type,
    label: labelOf(node),
    family: familyOf(node),
    prefix: node.type === 'flux.legacy_command' ? prefixOfV1(String(params.command ?? '')) : undefined,
    hasExec: execIn || (execOut && !node.type.startsWith('event.')),
    inputs,
    // Event nodes start the chain: their "then" is drawn as an output port.
    outputs: node.type.startsWith('event.') ? [{ name: 'then', type: 'exec' }, ...outputs] : outputs,
    position: { x: node.pos?.[0] ?? 0, y: node.pos?.[1] ?? 0 },
    meta,
  }
}

export function adaptV2Flow(flow: FlowDoc, opts: { readOnly: boolean; origin?: string; specs?: SpecIndex }): FlowView {
  const nodes = Object.entries(flow.nodes ?? {}).map(([id, n]) =>
    opts.specs?.[n.type] && !LEGACY_TYPES.has(n.type) ? specNode(id, n, opts.specs[n.type]) : v2Node(id, n, flow))
  const byId = Object.fromEntries(nodes.map(n => [n.id, n]))
  const labels = Object.fromEntries(nodes.map(n => [n.id, n.label]))
  const edges: FlowViewEdge[] = []
  for (const l of flow.links ?? []) {
    const [source, sourcePort] = splitRef(l.from)
    const [target, targetPort] = splitRef(l.to)
    if (!byId[source] || !byId[target]) continue
    const exec = targetPort === 'exec'
    const input = byId[target].inputs.find(p => p.name === targetPort)
    if (input && !exec) input.wiredFrom = `${labels[source]}.${sourcePort}`
    const srcType = byId[source].outputs.find(p => p.name === sourcePort)?.type ?? 'any'
    const dstType = exec ? 'exec' : (input?.type ?? 'any')
    const status = exec ? 'ok' : editorConnect(srcType, dstType).status
    edges.push({ id: `${exec ? 'exec' : 'data'}:${l.from}->${l.to}`, kind: exec ? 'exec' : 'data',
                 source, sourcePort, target, targetPort, type: dstType,
                 conversion: status === 'implicit' && srcType !== dstType && srcType !== 'any' && dstType !== 'any',
                 bad: status === 'incompatible' })
  }
  return {
    name: flow.name,
    description: flow.description,
    nodes,
    edges,
    groups: flow.groups,
    notes: flow.notes,
    readOnly: opts.readOnly,
    origin: opts.origin,
  }
}
