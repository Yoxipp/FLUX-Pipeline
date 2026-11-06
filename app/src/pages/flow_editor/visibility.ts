// visibility.ts — ports shown by the node's mode (R1 retake 2, registry Port.when): a port with
// `when: {param, in}` is shown only while that param (set value or default) is one of `in`.
// Linked or templated controlling params show everything (the value is known at run time).
// A hidden port that is linked stays drawn: the validation says W_PORT_HIDDEN.

import type { FlowViewNode, PortSpec } from './types'

export function portVisible(node: FlowViewNode, port: PortSpec): boolean {
  const w = port.when
  if (!w) return true
  const ctrl = [...node.inputs, ...(node.constants ?? [])].find(p => p.name === w.param)
  if (!ctrl || ctrl.wiredFrom) return true
  const value = ctrl.value
  if (value === undefined || value === null || value === '') return true
  const text = String(value)
  if (/[{$]/.test(text)) return true
  return w.in.some(v => String(v).toLowerCase() === text.trim().toLowerCase())
}
