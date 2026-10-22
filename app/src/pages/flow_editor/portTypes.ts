// portTypes.ts — port types of the Flows (01_ARCHITECTURE §3): colour and shape.
// P0 holds colours and shapes only; conversions and canConnect come with editing (P4).

import type { PortType } from './types'

export type PortShape = 'triangle' | 'circle' | 'square' | 'diamond' | 'ring' | 'hollow'

// Base of a type: "list[path]" -> "path", "session[maya]" -> "session".
export function baseType(t: PortType): string {
  const list = /^list\[(.+)\]$/.exec(t)
  if (list) return baseType(list[1])
  return t.replace(/\[.*\]$/, '')
}

export function portColor(t: PortType): string {
  return `var(--port-${baseType(t)}, var(--port-any))`
}

export function portShape(t: PortType): PortShape {
  if (t === 'exec') return 'triangle'
  if (t === 'any') return 'hollow'
  if (t.startsWith('list[')) return 'square'
  if (t === 'dict' || t === 'publish') return 'diamond'
  if (t.startsWith('session') || t === 'dcc_node') return 'ring'
  return 'circle'
}

const KNOWN = new Set(['exec', 'any', 'bool', 'int', 'float', 'str', 'path', 'dir', 'dict', 'publish', 'dcc_node', 'pattern'])

// A v1 parameter type ("string", "list", "folder"...) -> a v2 port type; unknown = any.
export function toPortType(raw: string | undefined): PortType {
  const t = (raw ?? '').trim().toLowerCase()
  const alias: Record<string, string> = {
    string: 'str', text: 'str', boolean: 'bool', integer: 'int', number: 'float',
    file: 'path', folder: 'dir', directory: 'dir', list: 'list[any]', json: 'dict',
  }
  const v = alias[t] ?? t
  if (KNOWN.has(v) || /^(list|session)\[.+\]$/.test(v)) return v
  return 'any'
}
