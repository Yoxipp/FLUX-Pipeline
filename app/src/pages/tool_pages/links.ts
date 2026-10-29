// links.ts — pure helpers of the TOOL pages (04_PAGES_TOOL, ADR 0068: the flow picks its page
// with an InputsPageReader, the page knows no flow). No React, no fetch: the logic is checked
// by reading and in live (no front test runner, P7).

import type { PageDoc, PageIssue, PageLayoutItem, PageWidget } from '../flow_editor/types'

// -- page walking and run values (PageRenderer, PageBuilder) -------------------------------


export const FORM_VALUE_KINDS = ['float', 'int', 'text', 'path', 'dir', 'toggle', 'select', 'list'] as const
export const DATA_KINDS = ['feed', 'table', 'cards', 'calendar', 'members', 'board'] as const

export function isValueKind(kind: string): boolean { return (FORM_VALUE_KINDS as readonly string[]).includes(kind) }
export function isDataKind(kind: string): boolean { return (DATA_KINDS as readonly string[]).includes(kind) }

export function rowsOf(items: PageLayoutItem[]): PageWidget[][] {
  return items.flatMap(item => 'row' in item ? [item.row] : rowsOf(item.children))
}

export function widgetsOf(page: PageDoc): PageWidget[] {
  return rowsOf(page.layout).flat()
}

// Initial value of a form widget: remembered (remember: user) > default > empty of its kind.
export function initialValue(w: PageWidget, remembered?: Record<string, unknown>): unknown {
  if (w.remember === 'user' && remembered && w.id in remembered) return remembered[w.id]
  if (w.default !== undefined && w.default !== null) return w.default
  if (w.kind === 'toggle') return false
  if (w.kind === 'list') return []
  if (w.kind === 'select') return w.options?.[0]?.value ?? ''
  return ''
}

// A widget value as the flow interface wants it (inputs give strings).
export function coerce(w: PageWidget, value: unknown): unknown {
  if (w.kind === 'int') { const n = parseInt(String(value), 10); return Number.isFinite(n) ? n : null }
  if (w.kind === 'float') { const n = parseFloat(String(value).replace(',', '.')); return Number.isFinite(n) ? n : null }
  if (w.kind === 'toggle') return Boolean(value)
  if (w.kind === 'list') return Array.isArray(value) ? value.map(String).filter(s => s !== '') : []
  return value === undefined || value === null ? '' : String(value)
}

// `values` of a click: every field of the page by its id (ADR 0068: the InputsPageReader
// outputs, and the interface inputs of the same id).
export function runValues(page: PageDoc, values: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const w of widgetsOf(page)) {
    if (!isValueKind(w.kind)) continue
    const v = coerce(w, values[w.id])
    if (v !== null && v !== '') out[w.id] = v
  }
  return out
}

// Error issues per widget: the widget is greyed with the first reason (04 §8).
// P_FLOW_INACTIVE is a warning but greys the button too (A7: only an active flow runs).
export function blockedWidgets(issues: PageIssue[], lang: 'fr' | 'en' | string): Record<string, string> {
  const out: Record<string, string> = {}
  for (const i of issues) {
    if (!i.widget || out[i.widget]) continue
    if (i.level === 'error' || i.code === 'P_FLOW_INACTIVE') out[i.widget] = lang === 'en' ? i.message_en : i.message_fr
  }
  return out
}

// "il y a 3 min" / "3 min ago".
export function ago(iso: string | null | undefined, lang: string, now = Date.now()): string {
  if (!iso) return ''
  const t = Date.parse(iso)
  if (!Number.isFinite(t)) return ''
  const s = Math.max(0, Math.round((now - t) / 1000))
  const [n, fr, en] = s < 60 ? [s, 's', 's'] : s < 3600 ? [Math.round(s / 60), 'min', 'min']
    : s < 86400 ? [Math.round(s / 3600), 'h', 'h'] : [Math.round(s / 86400), 'j', 'd']
  return lang === 'en' ? `${n} ${en} ago` : `il y a ${n} ${fr}`
}

export function seconds(ms: number | null | undefined, lang: string): string {
  if (ms === null || ms === undefined) return ''
  const v = (ms / 1000).toFixed(1)
  return `${lang === 'en' ? v : v.replace('.', ',')} s`
}
