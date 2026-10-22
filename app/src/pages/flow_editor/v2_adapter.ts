// v2_adapter.ts — read-only adapter: a v2 flow document (GET /flows/{name}, 01 §2) -> the
// editor's view model (FlowView). Pure functions, no I/O.
//
// P1: the v2 node registry holds no node yet (P2 / P3), so ports come from the document:
// flux.legacy_command / flux.call_function (migrated v1, 01 §15) carry them in
// params.ports {inputs, outputs}; any other node gets the ports its links use, plus one
// greyed input per literal param. Exec: "exec" in, "then" / "on_error" / branches out.
// Positions are the stored pos (the migration lays them out once).

import { FAMILIES } from './families'
import { familyOfV1, pascal, prefixOfV1 } from './v1_adapter'
import type { Family, FlowDoc, FlowDocNode, FlowView, FlowViewEdge, FlowViewNode, PortSpec, PortType } from './types'

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

export function adaptV2Flow(flow: FlowDoc, opts: { readOnly: boolean; origin?: string }): FlowView {
  const nodes = Object.entries(flow.nodes ?? {}).map(([id, n]) => v2Node(id, n, flow))
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
    edges.push({ id: `${exec ? 'exec' : 'data'}:${l.from}->${l.to}`, kind: exec ? 'exec' : 'data',
                 source, sourcePort, target, targetPort, type: exec ? 'exec' : (input?.type ?? 'any') })
  }
  return {
    name: flow.name,
    description: flow.description,
    nodes,
    edges,
    readOnly: opts.readOnly,
    origin: opts.origin,
  }
}
