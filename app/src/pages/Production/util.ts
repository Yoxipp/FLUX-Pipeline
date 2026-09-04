// Shared helpers for the Production Tab.

import type { ProductionState } from '../../types'

export const CATEGORY_ORDER = ['CHAR', 'PROPS', 'ENV', 'FXRIG'] as const
export type Category = (typeof CATEGORY_ORDER)[number]

// Map each category to its CSS var (defined in globals.css).
export const categoryColor = (cls: string): string => {
  switch (cls.toUpperCase()) {
    case 'CHAR':  return 'var(--prod-chara)'
    case 'PROPS': return 'var(--prod-props)'
    case 'ENV':   return 'var(--prod-env)'
    case 'FXRIG': return 'var(--prod-fx)'
    default:      return 'var(--ink-3)'
  }
}

export const categoryLabelKey = (cls: string): string => {
  const key = cls.toUpperCase()
  if (['CHAR', 'PROPS', 'ENV', 'FXRIG'].includes(key)) return `prod.class.${key}`
  return ''
}

// Deterministic hue from a task label — cheap, no dependency, no lookup table.
export const taskColorFromName = (name: string): string => {
  let h = 0
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) & 0xffff
  return `oklch(66% 0.06 ${h % 360})`
}

// Deterministic hue for a sequence — spread across the wheel using an
// approximation of the golden angle so consecutive seqs land in different
// zones of the color spectrum.
function hueFromKey(key: string): number {
  let h = 0
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) & 0xffff
  return (h * 137) % 360
}

function hslToHex(h: number, s: number, l: number): string {
  // s, l in [0, 100]; h in [0, 360). Returns "#rrggbb".
  const S = s / 100, L = l / 100
  const C = (1 - Math.abs(2 * L - 1)) * S
  const X = C * (1 - Math.abs(((h / 60) % 2) - 1))
  const m = L - C / 2
  let r = 0, g = 0, b = 0
  if (h < 60)       { r = C; g = X; b = 0 }
  else if (h < 120) { r = X; g = C; b = 0 }
  else if (h < 180) { r = 0; g = C; b = X }
  else if (h < 240) { r = 0; g = X; b = C }
  else if (h < 300) { r = X; g = 0; b = C }
  else              { r = C; g = 0; b = X }
  const toHex = (n: number) => Math.round((n + m) * 255).toString(16).padStart(2, '0')
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`
}

// Default seq color as hex — same shape used by <input type="color">.
export const defaultSeqColor = (key: string): string =>
  hslToHex(hueFromKey(key), 55, 58)

// Given a seq's effective color, return a related (darker/desaturated) shade
// for its shots — same hue family, lower lightness.
export const shotColorFromSeqColor = (seqColor: string): string =>
  `color-mix(in oklch, ${seqColor} 78%, black 22%)`

// $FLUX/... → absolute (mirror of Activity.tsx's expandFluxPath).
export function expandFluxPath(stored: string, workspace: string | null | undefined): string {
  if (!stored) return stored
  if (stored.startsWith('$FLUX/')) return workspace ? `${workspace}/${stored.slice('$FLUX/'.length)}` : stored
  if (stored === '$FLUX') return workspace ?? stored
  return stored
}

// Collect every TYPE token already used across assets/shots — used to seed
// autocomplete suggestions for the "Linked TYPE tokens" input on new tasks.
export function collectUsedTypeTokens(state: ProductionState): string[] {
  const s = new Set<string>()
  for (const a of state.assets) for (const t of a.tasks) for (const tk of t.type_tokens) s.add(tk.toUpperCase())
  for (const sh of state.shots) for (const t of sh.tasks) for (const tk of t.type_tokens) s.add(tk.toUpperCase())
  return [...s].sort()
}

// Filename parser that mirrors backend `reconcile.parse_publish_event`:
// tries the new order (CLASS_NAME_TASK_INSTANCE[_VARIANTE]_ITER) first, then
// the legacy order (CLASS_TYPE_NAME_INSTANCE[_VARIANTE]_ITER), using a set of
// known TYPE tokens as tie-breaker.
export interface ParsedName {
  class:    string
  name:     string
  task:     string
  instance: string
  isShot:   boolean
}
const _VERSION = /^v\d+$/i
const _ACTIVE  = 'LAST'
const _SEQ     = /^SEQ\d+$/i

function _parseNew(filename: string): ParsedName | null {
  const stem = filename.replace(/\.[^./\\]*$/, '')
  const parts = stem.split('_')
  if (parts.length < 3) return null
  const last = parts[parts.length - 1]
  const hasIter = _VERSION.test(last) || last.toUpperCase() === _ACTIVE
  const core = hasIter ? parts.slice(0, -1) : parts.slice()
  if (core.length >= 2 && _SEQ.test(core[1])) {
    return { class: core[0].toUpperCase(), name: '', task: '', instance: (core[3] || '').toUpperCase(), isShot: true }
  }
  if (core.length < 3) return null
  return {
    class:    core[0].toUpperCase(),
    name:     core[1].toUpperCase(),
    task:     core[2].toUpperCase(),
    instance: (core[3] || '').toUpperCase(),
    isShot:   false,
  }
}
function _parseLegacy(filename: string): ParsedName | null {
  const stem = filename.replace(/\.[^./\\]*$/, '')
  const parts = stem.split('_')
  if (parts.length < 3) return null
  const last = parts[parts.length - 1]
  const hasIter = _VERSION.test(last) || last.toUpperCase() === _ACTIVE
  const core = hasIter ? parts.slice(0, -1) : parts.slice()
  if (core.length >= 2 && _SEQ.test(core[1])) {
    return { class: core[0].toUpperCase(), name: '', task: '', instance: (core[3] || '').toUpperCase(), isShot: true }
  }
  if (core.length < 3) return null
  return {
    class:    core[0].toUpperCase(),
    task:     core[1].toUpperCase(),   // legacy TYPE at slot 2
    name:     core[2].toUpperCase(),
    instance: (core[3] || '').toUpperCase(),
    isShot:   false,
  }
}
export function parseFluxFilename(filename: string, knownTypeTokens: Set<string> = new Set()): ParsedName | null {
  if (!filename) return null
  const n = _parseNew(filename)
  const l = _parseLegacy(filename)
  if (n?.isShot) return n
  if (l?.isShot) return l
  if (!n && !l) return null
  if (!n)  return l
  if (!l)  return n
  if (knownTypeTokens.size) {
    const nk = knownTypeTokens.has(n.task)
    const lk = knownTypeTokens.has(l.task)
    if (lk && !nk) return l
    if (nk && !lk) return n
  }
  return n
}

export function collectAllTaskNames(state: ProductionState): string[] {
  const s = new Set<string>()
  for (const a of state.assets) for (const t of a.tasks) s.add(t.name.toUpperCase())
  return [...s].sort()
}
