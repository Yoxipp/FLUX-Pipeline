// destructive.ts — the `!` nodes (00_LOGIQUE §13, 01 §8): a node whose catalogue flag
// `destructive` is true, or {param, equals} matched by its param (or the param default),
// bypassed nodes excluded. Mirror of registry.flag_on / validate.unconfirmed_destructive:
// "added" = `!` now and not `!` in the last saved document (a new file: every `!`).

import type { CondFlag, FlowDoc, FlowDocNode, NodeSpec } from './types'

export function flagOn(flag: CondFlag | undefined, spec: NodeSpec, params: Record<string, unknown>): boolean {
  if (!flag) return false
  if (typeof flag !== 'object') return true
  const value = flag.param in params ? params[flag.param]
    : [...spec.params, ...spec.inputs].find(p => p.name === flag.param)?.default
  return value === flag.equals
}

export function isDestructive(node: FlowDocNode | undefined, specs: Record<string, NodeSpec>): boolean {
  if (!node || node.bypass) return false
  const spec = specs[node.type]
  return !!spec && flagOn(spec.destructive, spec, node.params ?? {})
}

export function destructiveAdded(doc: FlowDoc, saved: FlowDoc | null, specs: Record<string, NodeSpec>): string[] {
  return Object.keys(doc.nodes).filter(id => isDestructive(doc.nodes[id], specs) && !isDestructive(saved?.nodes[id], specs))
}
