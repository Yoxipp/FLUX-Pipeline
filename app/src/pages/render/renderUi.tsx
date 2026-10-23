// renderUi.tsx: shared look and helpers of the Tractor window (pages/Render.tsx and its tabs).
// Flat tokens, light elevation, no glow (FLUX UI rules).

import { useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { Info } from 'lucide-react'
import { useI18n } from '../../i18n'
import type { RenderBladeState, RenderJob } from '../../api/client'

export type Tr = (fr: string, en: string) => string

export function useTr() {
  const { lang } = useI18n()
  const tr: Tr = (fr, en) => (lang === 'en' ? en : fr)
  return { tr, locale: lang === 'en' ? 'en-GB' : 'fr-FR' }
}

export const errMsg = (e: unknown) => (e instanceof Error ? e.message : String(e))

export const btn = (primary = false, danger = false): CSSProperties => ({
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 5, padding: '5px 10px', fontSize: 11,
  borderRadius: 6, cursor: 'pointer', fontFamily: 'var(--sans)',
  border: `1px solid ${danger ? 'var(--err)' : primary ? 'var(--accent)' : 'var(--rule-2)'}`,
  background: primary && !danger ? 'var(--accent)' : 'var(--paper-2)',
  fontWeight: primary && !danger ? 700 : undefined,
  color: danger ? 'var(--err)' : primary ? 'var(--on-accent)' : 'var(--accent-hi)',
})
export const disabledIf = (off: boolean): CSSProperties => (off ? { opacity: 0.45, pointerEvents: 'none' } : {})
export const input: CSSProperties = {
  width: '100%', boxSizing: 'border-box', padding: '5px 8px', fontSize: 11.5, borderRadius: 6,
  border: '1px solid var(--rule-2)', background: 'var(--paper-2)', color: 'var(--ink)', outline: 'none',
  fontFamily: 'var(--sans)',
}
export const lbl: CSSProperties = { fontSize: 11, letterSpacing: 0.6, textTransform: 'uppercase', color: 'var(--ink-3)', marginBottom: 4 }
export const card: CSSProperties = {
  border: '1px solid var(--rule-2)', borderRadius: 6, background: 'var(--paper-2)', boxShadow: 'var(--shadow-xs)', padding: 12,
}
export const hint: CSSProperties = { fontSize: 11, color: 'var(--ink-3)' }
export const warnText: CSSProperties = { fontSize: 11.5, color: 'var(--warn)' }
export const sel: CSSProperties = { width: '100%' }

// Job and blade state colors.
export const STATE_COLOR: Record<string, string> = {
  active: 'var(--accent)', error: 'var(--err)', done: 'var(--ok)',
  paused: 'var(--ink-2)', waiting: 'var(--ink-3)', deleted: 'var(--ink-3)',
}
export const BLADE_COLOR: Record<RenderBladeState, string> = {
  free: 'var(--ok)', busy: 'var(--accent)', nimby: 'var(--warn)', offline: 'var(--ink-4)',
}

export function bladeStateLabel(state: RenderBladeState, tr: Tr): string {
  const l: Record<RenderBladeState, [string, string]> = {
    free: ['Libre', 'Free'], busy: ['Occupe', 'Busy'], nimby: ['Poste utilise', 'In use (NIMBY)'], offline: ['Eteint', 'Offline'],
  }
  return tr(...l[state])
}

export function stateLabel(state: string, tr: Tr): string {
  const labels: Record<string, [string, string]> = {
    active: ['En cours', 'Running'], error: ['Erreur', 'Error'], done: ['Fini', 'Done'],
    paused: ['Pause', 'Paused'], waiting: ['En attente', 'Waiting'], deleted: ['Supprime', 'Deleted'],
  }
  const l = labels[state]
  return l ? tr(l[0], l[1]) : state
}

const dirname = (p: string) => p.replace(/[\\/][^\\/]*$/, '')
export const openFolder = (p: string) => { if (p) void window.electronAPI?.openPath?.(dirname(p)) }
// Render output paths are folders (<shot>/render/vNNN): open them as is.
export const openDir = (p: string) => { if (p) void window.electronAPI?.openPath?.(p) }

// Tractor spooltime "2026-10-20 11:19:07+02" -> "20/10 11:19".
export function shortDate(value: string | number | undefined): string {
  const m = /^\d{4}-(\d{2})-(\d{2})[ T](\d{2}:\d{2})/.exec(String(value ?? ''))
  return m ? `${m[2]}/${m[1]} ${m[3]}` : String(value ?? '')
}

// Job metadata can be an object or a JSON string; the output path lives in it.
export function jobMeta(j: RenderJob): Record<string, unknown> {
  let m: unknown = j.metadata
  if (typeof m === 'string') { try { m = JSON.parse(m) } catch { m = null } }
  return m && typeof m === 'object' ? (m as Record<string, unknown>) : {}
}
export function jobOutput(j: RenderJob): string {
  const o = jobMeta(j).output
  return typeof o === 'string' ? o : ''
}

export function Row({ label, children, help }: { label: string; children: ReactNode; help?: string }) {
  return <div><div style={lbl}>{label}</div>{children}{help && <div style={{ ...hint, marginTop: 3 }}>{help}</div>}</div>
}

// "i" button: what "machines on" / "free machines" mean (2026-10-23). Click to show, click again to hide.
export function ShareBaseInfo() {
  const { tr } = useTr()
  const [open, setOpen] = useState(false)
  return (
    <span style={{ position: 'relative', display: 'inline-flex' }}>
      <button type="button" onClick={() => setOpen(o => !o)} title={tr('Explication', 'Explanation')}
        style={{ display: 'inline-flex', background: 'none', border: 'none', padding: 2, cursor: 'pointer', color: open ? 'var(--accent)' : 'var(--ink-3)' }}>
        <Info size={12} />
      </button>
      {open && (
        <div style={{ position: 'absolute', top: '100%', left: 0, zIndex: 20, width: 280, marginTop: 4, padding: '8px 10px',
          background: 'var(--paper)', border: '1px solid var(--rule-2)', borderRadius: 6, boxShadow: '0 2px 8px rgba(0,0,0,.12)',
          fontSize: 11, color: 'var(--ink-2)', display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div><b>{tr('Machines allumees', 'Machines on')}</b> : {tr('vues par Tractor dans les 15 dernieres minutes, occupees ou non.', 'seen by Tractor in the last 15 minutes, busy or not.')}</div>
          <div><b>{tr('Machines libres', 'Free machines')}</b> : {tr("aucun rendu Tractor en cours, mais pas forcement sans personne dessus.", 'no Tractor render running, but not necessarily nobody at the desk.')}</div>
        </div>
      )}
    </span>
  )
}

export function Toggle({ value, options, onChange }: {
  value: string; options: { id: string; label: string; title?: string }[]; onChange: (id: string) => void
}) {
  return (
    <div style={{ display: 'inline-flex', gap: 4, flexWrap: 'wrap' }}>
      {options.map(o => (
        <button key={o.id} type="button" title={o.title} onClick={() => onChange(o.id)}
          style={{ ...btn(), background: value === o.id ? 'var(--accent-soft)' : 'var(--paper-2)', borderColor: value === o.id ? 'var(--rule-3)' : 'var(--rule-2)' }}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function Check({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11.5, color: 'var(--ink-2)', cursor: 'pointer' }}>
      <input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)} />{label}
    </label>
  )
}

export function Banner({ children, color = 'var(--ink-2)' }: { children: ReactNode; color?: string }) {
  return (
    <div style={{ padding: '6px 10px', fontSize: 11.5, borderRadius: 6, border: '1px solid var(--rule-2)', background: 'var(--paper-2)', color }}>
      {children}
    </div>
  )
}

export function Bar({ value, max, color = 'var(--accent)', height = 8 }: { value: number; max: number; color?: string; height?: number }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0
  return (
    <div style={{ flex: 1, height, borderRadius: height / 2, background: 'var(--rule-2)', overflow: 'hidden' }}>
      <div style={{ width: `${pct}%`, height: '100%', background: color }} />
    </div>
  )
}

export function Section({ title, children, note }: { title: string; children: ReactNode; note?: ReactNode }) {
  return (
    <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ ...lbl, marginBottom: 0 }}>{title}</div>
      {note}
      {children}
    </div>
  )
}

// School machine names: TLSS + room number + desk (ROOM1720 = room 17, 2026-10-23). Group key stays "ROOM17".
export function roomLabel(room: string, tr: Tr): string {
  const m = /^TLSS(\d{2})$/.exec(room)
  return m ? tr(`Salle ${m[1]}`, `Room ${m[1]}`) : room === 'autres' ? tr('Autres', 'Others') : room
}

// "% of the farm" -> number of chunks at once, same rule as the backend (farm_targets.cap_from_percent).
export function capFromPercent(percent: number, pool: number): number {
  return percent > 0 ? Math.max(1, Math.floor((pool * percent) / 100)) : 0
}
