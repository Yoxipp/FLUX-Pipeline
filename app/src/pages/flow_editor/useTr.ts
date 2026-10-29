// useTr.ts — FR / EN text of the Flows editor (copied from the old P4 editor, removed in P8).

import { useMemo } from 'react'
import { useI18n } from '../../i18n'

// Stable per language: `tr` sits in the deps of the editor callbacks (a new one per render
// rebuilt every xyflow node, NetworkPane).
export function useTr() {
  const { lang } = useI18n()
  return useMemo(() => ({ lang, tr: (fr: string, en: string) => (lang === 'en' ? en : fr) }), [lang])
}

// A literal value, short enough for a port row or a tooltip.
export function formatValue(v: unknown, max: number): string {
  let s: string
  if (v === null || v === undefined || v === '') s = ''
  else if (typeof v === 'string') s = v
  else { try { s = JSON.stringify(v) } catch { s = String(v) } }
  return s.length > max ? `${s.slice(0, max - 1)}…` : s
}
