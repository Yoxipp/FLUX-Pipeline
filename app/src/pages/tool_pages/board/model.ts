// model.ts — board data helpers (ADR 0071, v3 ADR 0074): item type, palette, geometry, ops for
// the undo stack and the clipboard, free drawing points, frame reading order. Flat fields only
// (one field = one value, per field merge).

import type { PageDataOp, PageRecord } from '../../flow_editor/types'

export type ItemType = 'note' | 'card' | 'image' | 'link' | 'shape' | 'text' | 'frame' | 'ink' | 'flux'
  | 'comment' | 'reaction' | 'timer'
export type Shape = 'rect' | 'round' | 'ellipse' | 'diamond'

export type Item = PageRecord & {
  type?: ItemType; x?: number; y?: number; w?: number; h?: number; z?: number
  text?: string; color?: string; image?: string; from?: string; to?: string
  shape?: Shape; stroke?: string; font_size?: number; bold?: boolean
  label?: string; dash?: 'solid' | 'dashed' | 'dotted'; arrow_start?: boolean; arrow_end?: boolean
  group?: string; locked?: boolean
  points?: string; stroke_width?: number; highlight?: boolean; ref?: string
  target?: string; emoji?: Emoji; ends_at?: string; seconds?: number
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
  purple: 'oklch(52% 0.12 300)', yellow: 'oklch(82% 0.15 95)', none: 'transparent',
}
export const FONT_SIZES = [10, 12, 13, 14, 16, 18, 24, 32, 48, 64]
export const SIZE: Record<ItemType, [number, number]> = {
  note: [180, 120], card: [220, 90], image: [240, 180], shape: [160, 100], text: [200, 40], link: [0, 0],
  frame: [480, 360], ink: [1, 1], flux: [240, 104], comment: [0, 0], reaction: [0, 0], timer: [0, 0],
}
export const DEFAULT_FONT: Record<ItemType, number> = { note: 13, card: 13, image: 13, shape: 14, text: 16, link: 12, frame: 13, ink: 13, flux: 12, comment: 12, reaction: 12, timer: 12 }
export const GRID = 8
// Records that are not drawn on the board: links (drawn between objects), comments, reactions, the timer (ADR 0075).
export const META_TYPES = new Set(['link', 'comment', 'reaction', 'timer'])
export type Emoji = 'like' | 'love' | 'laugh' | 'question' | 'check'
export const EMOJI: Record<Emoji, string> = { like: '\u{1F44D}', love: '\u2764\uFE0F', laugh: '\u{1F602}', question: '\u2753', check: '\u2705' }
export const CLIP_TAG = 'flux_board'

const num = (v: unknown, d: number) => typeof v === 'number' && Number.isFinite(v) ? v : d
export const typeOf = (it: Item): ItemType => (it.type && it.type in SIZE ? it.type : 'note')
export const dims = (it: Item): Box => {
  const [dw, dh] = SIZE[typeOf(it)]
  return { x: num(it.x, 0), y: num(it.y, 0), w: num(it.w, dw), h: num(it.h, dh) }
}
export const fillOf = (it: Item) => FILLS[it.color ?? ''] ?? FILLS[it.type === 'card' || it.type === 'shape' || it.type === 'flux' ? 'white'
  : it.type === 'text' || it.type === 'ink' ? 'none' : it.type === 'frame' ? 'grey' : 'yellow']
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

// -- free drawing (points relative to x / y, "x,y x,y") -----------------------
export const MAX_POINTS = 2000
export type Pt = [number, number]
export function parsePoints(s: string | undefined): Pt[] {
  if (!s) return []
  return s.split(' ').map(p => p.split(',').map(Number) as Pt).filter(p => p.length === 2 && p.every(Number.isFinite))
}
// Ramer-Douglas-Peucker: drop the points closer than *eps* to the line of their neighbours.
export function simplify(pts: Pt[], eps: number): Pt[] {
  if (pts.length < 3) return pts
  const [a, b] = [pts[0], pts[pts.length - 1]]
  let far = 0, at = 0
  for (let i = 1; i < pts.length - 1; i++) {
    const d = segDist(pts[i], a, b)
    if (d > far) { far = d; at = i }
  }
  if (far <= eps) return [a, b]
  return [...simplify(pts.slice(0, at + 1), eps).slice(0, -1), ...simplify(pts.slice(at), eps)]
}
export function segDist(p: Pt, a: Pt, b: Pt) {
  const dx = b[0] - a[0], dy = b[1] - a[1], l2 = dx * dx + dy * dy
  const t = l2 ? Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2)) : 0
  return Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)
}
// The record of a stroke drawn in board coordinates: box + points relative to its corner.
export function inkFields(pts: Pt[], eps: number): Record<string, unknown> | null {
  let s = simplify(pts, eps)
  if (s.length > MAX_POINTS) s = s.filter((_, i) => i % Math.ceil(s.length / MAX_POINTS) === 0)
  if (s.length < 2) s = [s[0], [s[0][0] + 0.5, s[0][1] + 0.5]]
  const x0 = Math.min(...s.map(p => p[0])), y0 = Math.min(...s.map(p => p[1]))
  const x1 = Math.max(...s.map(p => p[0])), y1 = Math.max(...s.map(p => p[1]))
  const r = (v: number) => Math.round(v * 10) / 10
  return { x: r(x0), y: r(y0), w: r(Math.max(1, x1 - x0)), h: r(Math.max(1, y1 - y0)),
           points: s.map(p => `${r(p[0] - x0)},${r(p[1] - y0)}`).join(' ') }
}
// Does the stroke pass within *tol* of (px, py)? (board coordinates)
export function inkHit(it: Item, px: number, py: number, tol: number) {
  const b = dims(it), pts = parsePoints(it.points)
  const t = tol + (it.stroke_width ?? 3) / 2
  if (px < b.x - t || py < b.y - t || px > b.x + b.w + t || py > b.y + b.h + t) return false
  const p: Pt = [px - b.x, py - b.y]
  for (let i = 1; i < pts.length; i++) if (segDist(p, pts[i - 1], pts[i]) <= t) return true
  return pts.length === 1 && Math.hypot(p[0] - pts[0][0], p[1] - pts[0][1]) <= t
}

// -- frames --------------------------------------------------------------------
// Reading order: rows (a frame starts a new row when its top is below half the row height),
// then left to right. Nothing to set: a storyboard laid out in rows reads by itself.
export function readingOrder(frames: Item[]): Item[] {
  const boxes = frames.map(f => ({ f, b: dims(f) })).sort((a, b) => a.b.y - b.b.y)
  const rows: { y: number; h: number; items: typeof boxes }[] = []
  for (const e of boxes) {
    const row = rows[rows.length - 1]
    if (row && e.b.y < row.y + row.h / 2) row.items.push(e)
    else rows.push({ y: e.b.y, h: e.b.h, items: [e] })
  }
  return rows.flatMap(r => r.items.sort((a, b) => a.b.x - b.b.x).map(e => e.f))
}
export const inside = (inner: Box, outer: Box) =>
  inner.x >= outer.x && inner.y >= outer.y && inner.x + inner.w <= outer.x + outer.w && inner.y + inner.h <= outer.y + outer.h
