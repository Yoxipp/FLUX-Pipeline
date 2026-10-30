// model.ts — board v2 data helpers (ADR 0071): item type, palette, geometry, ops for the
// undo stack and the clipboard. Flat fields only (one field = one value, per field merge).

import type { PageDataOp, PageRecord } from '../../flow_editor/types'

export type ItemType = 'note' | 'card' | 'image' | 'link' | 'shape' | 'text'
export type Shape = 'rect' | 'round' | 'ellipse' | 'diamond'

export type Item = PageRecord & {
  type?: ItemType; x?: number; y?: number; w?: number; h?: number; z?: number
  text?: string; color?: string; image?: string; from?: string; to?: string
  shape?: Shape; stroke?: string; font_size?: number; bold?: boolean
  label?: string; dash?: 'solid' | 'dashed' | 'dotted'; arrow_start?: boolean; arrow_end?: boolean
  group?: string; locked?: boolean
}
export interface Box { x: number; y: number; w: number; h: number }

// Flat, muted fills (no glow). Text stays dark on them in both themes.
export const FILLS: Record<string, string> = {
  yellow: 'oklch(90% 0.07 95)', orange: 'oklch(87% 0.07 60)', pink: 'oklch(88% 0.06 0)',
  purple: 'oklch(87% 0.05 300)', blue: 'oklch(88% 0.05 240)', green: 'oklch(88% 0.06 150)',
  grey: 'oklch(90% 0.01 250)', white: 'oklch(98% 0 0)', none: 'transparent',
}
export const STROKES: Record<string, string> = {
  ink: 'oklch(30% 0.02 250)', grey: 'oklch(60% 0.01 250)', blue: 'oklch(55% 0.12 245)',
  green: 'oklch(55% 0.11 150)', red: 'oklch(55% 0.15 25)', orange: 'oklch(65% 0.13 60)',
  purple: 'oklch(52% 0.12 300)', none: 'transparent',
}
export const FONT_SIZES = [10, 12, 13, 14, 16, 18, 24, 32, 48, 64]
export const SIZE: Record<ItemType, [number, number]> = {
  note: [180, 120], card: [220, 90], image: [240, 180], shape: [160, 100], text: [200, 40], link: [0, 0],
}
export const DEFAULT_FONT: Record<ItemType, number> = { note: 13, card: 13, image: 13, shape: 14, text: 16, link: 12 }
export const GRID = 8
export const CLIP_TAG = 'flux_board'

const num = (v: unknown, d: number) => typeof v === 'number' && Number.isFinite(v) ? v : d
export const typeOf = (it: Item): ItemType => (it.type && it.type in SIZE ? it.type : 'note')
export const dims = (it: Item): Box => {
  const [dw, dh] = SIZE[typeOf(it)]
  return { x: num(it.x, 0), y: num(it.y, 0), w: num(it.w, dw), h: num(it.h, dh) }
}
export const fillOf = (it: Item) => FILLS[it.color ?? ''] ?? FILLS[it.type === 'card' || it.type === 'shape' ? 'white' : it.type === 'text' ? 'none' : 'yellow']
export const strokeOf = (it: Item, d = 'grey') => STROKES[it.stroke ?? d] ?? STROKES[d]
export const fontOf = (it: Item) => num(it.font_size, DEFAULT_FONT[typeOf(it)])

export const intersects = (a: Box, b: Box) => a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y
export const bounds = (boxes: Box[]): Box | null => {
  if (!boxes.length) return null
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
  for (const b of boxes) { x0 = Math.min(x0, b.x); y0 = Math.min(y0, b.y); x1 = Math.max(x1, b.x + b.w); y1 = Math.max(y1, b.y + b.h) }
  return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 }
}

// Where the segment from the centre of *b* towards (tx, ty) leaves *b* (links stick to the edges).
export function edgePoint(b: Box, shape: Shape | undefined, tx: number, ty: number) {
  const cx = b.x + b.w / 2, cy = b.y + b.h / 2
  const dx = tx - cx, dy = ty - cy
  if (!dx && !dy) return { x: cx, y: cy }
  const rx = b.w / 2, ry = b.h / 2
  let t: number
  if (shape === 'ellipse') t = 1 / Math.sqrt((dx * dx) / (rx * rx) + (dy * dy) / (ry * ry))
  else if (shape === 'diamond') t = 1 / (Math.abs(dx) / rx + Math.abs(dy) / ry)
  else t = Math.min(dx ? rx / Math.abs(dx) : Infinity, dy ? ry / Math.abs(dy) : Infinity)
  return { x: cx + dx * Math.min(t, 1), y: cy + dy * Math.min(t, 1) }
}

// The stored fields of a record (what a restore or a copy carries).
export function fieldsOf(it: Item): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(it)) if (k !== 'rid' && !k.startsWith('_') && v !== undefined) out[k] = v
  return out
}

// Ops that undo a put of *fields* on *before* (a field it did not have goes back to null).
export function inversePut(before: Item, fields: Record<string, unknown>): PageDataOp {
  const back: Record<string, unknown> = {}
  for (const k of Object.keys(fields)) back[k] = (before as Record<string, unknown>)[k] ?? null
  return { op: 'put', rid: before.rid, fields: back }
}
export const restoreOp = (it: Item): PageDataOp => ({ op: 'put', rid: it.rid, fields: fieldsOf(it), restore: true })

export const newGroupId = () => `g${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`

export interface ClipData { [CLIP_TAG]: 2; page: string; collection: string; items: Item[] }
export function parseClip(text: string): ClipData | null {
  try {
    const d = JSON.parse(text)
    return d && d[CLIP_TAG] === 2 && Array.isArray(d.items) ? d as ClipData : null
  } catch { return null }
}
