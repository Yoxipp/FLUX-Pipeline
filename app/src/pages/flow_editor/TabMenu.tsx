// TabMenu.tsx — Tab menu at the mouse, like Houdini (2026-10-22): one sub-menu per node
// family, its nodes inside; typing searches every node (names starting with the search first).
// Keys: arrows, Right / Enter opens a family, Left goes back, Enter picks, Escape closes.
// P4: picking adds the node (at the mouse). `filter` limits the menu (a link dropped in the
// void: the compatible nodes only, 03 §4), `title` replaces the footer.

import { useEffect, useMemo, useState } from 'react'
import { ChevronRight } from 'lucide-react'
import { FAMILIES, FAMILY_INFO } from './families'
import { iconFor } from './icons'
import type { Family } from './types'
import type { CatalogEntry } from './v1_adapter'
import { useTr } from './useTr'

const SEARCH_MAX = 14
const COL_W = 210

export function TabMenu({ entries: all, x, y, filter, title, onPick, onClose }: {
  entries: CatalogEntry[] | null
  filter?: (e: CatalogEntry) => boolean
  title?: string
  x: number
  y: number
  onPick: (e: CatalogEntry) => void
  onClose: () => void
}) {
  const { tr, lang } = useTr()
  const [q, setQ] = useState('')
  const [famIdx, setFamIdx] = useState(0)
  const [nodeIdx, setNodeIdx] = useState(-1)   // -1 = focus on the family column
  const ql = q.trim().toLowerCase()
  const entries = useMemo(() => all && filter ? all.filter(filter) : all, [all, filter])

  const byFamily = useMemo(() => {
    const m = {} as Record<Family, CatalogEntry[]>
    for (const f of FAMILIES) m[f] = []
    for (const e of entries ?? []) m[e.family].push(e)
    for (const f of FAMILIES) m[f].sort((a, b) => a.label.localeCompare(b.label))
    return m
  }, [entries])

  const found = useMemo(() => {
    if (!ql) return []
    const hay = (e: CatalogEntry) => [e.label, e.type, ...e.aliases, e.doc_fr ?? '', e.doc_en ?? ''].join(' ').toLowerCase()
    const starts = (e: CatalogEntry) => [e.label, ...e.aliases].some(n => n.toLowerCase().startsWith(ql)) ? 0 : 1
    return (entries ?? []).filter(e => hay(e).includes(ql))
      .sort((a, b) => starts(a) - starts(b) || a.label.localeCompare(b.label))
      .slice(0, SEARCH_MAX)
  }, [entries, ql])

  useEffect(() => { setNodeIdx(ql ? 0 : -1) }, [ql])

  const fam = FAMILIES[famIdx]
  const sub = byFamily[fam]
  const pick = (e: CatalogEntry | undefined) => { if (e) { onPick(e); onClose() } }

  const onKey = (e: React.KeyboardEvent) => {
    const k = e.key
    if (k === 'Escape' || k === 'Tab') { e.preventDefault(); onClose(); return }
    if (ql) {
      if (k === 'ArrowDown') { e.preventDefault(); setNodeIdx(i => Math.min(i + 1, found.length - 1)) }
      else if (k === 'ArrowUp') { e.preventDefault(); setNodeIdx(i => Math.max(i - 1, 0)) }
      else if (k === 'Enter') { e.preventDefault(); pick(found[nodeIdx]) }
      return
    }
    if (nodeIdx < 0) {
      if (k === 'ArrowDown') { e.preventDefault(); setFamIdx(i => Math.min(i + 1, FAMILIES.length - 1)) }
      else if (k === 'ArrowUp') { e.preventDefault(); setFamIdx(i => Math.max(i - 1, 0)) }
      else if ((k === 'ArrowRight' || k === 'Enter') && sub.length) { e.preventDefault(); setNodeIdx(0) }
    } else {
      if (k === 'ArrowDown') { e.preventDefault(); setNodeIdx(i => Math.min(i + 1, sub.length - 1)) }
      else if (k === 'ArrowUp') { e.preventDefault(); setNodeIdx(i => Math.max(i - 1, 0)) }
      else if (k === 'ArrowLeft') { e.preventDefault(); setNodeIdx(-1) }
      else if (k === 'Enter') { e.preventDefault(); pick(sub[nodeIdx]) }
    }
  }

  const box: React.CSSProperties = {
    background: 'var(--paper)', border: '1px solid var(--rule-2)', borderRadius: 8, boxShadow: 'var(--shadow)', padding: 4,
  }
  const rowStyle = (on: boolean): React.CSSProperties => ({
    display: 'flex', alignItems: 'center', gap: 7, height: 24, padding: '0 7px', borderRadius: 5, cursor: 'pointer',
    fontSize: 11.5, color: 'var(--ink)', background: on ? 'var(--accent-soft)' : 'transparent', whiteSpace: 'nowrap',
  })
  const NodeRow = ({ e, on, onHover }: { e: CatalogEntry; on: boolean; onHover: () => void }) => {
    const info = FAMILY_INFO[e.family]
    const Icon = iconFor(e.icon, e.family)
    const doc = lang === 'en' ? e.doc_en || e.doc_fr : e.doc_fr || e.doc_en
    return (
      <div onMouseDown={ev => { ev.preventDefault(); pick(e) }} onMouseEnter={onHover} style={rowStyle(on)} title={doc}>
        <Icon size={13} strokeWidth={1.75} color={info.color} />
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{e.label}</span>
        {e.prefix && <span style={{ fontSize: 10, color: 'var(--ink-4)' }}>{e.prefix}</span>}
        {e.origin === 'equipe' && <span style={{ fontSize: 10, color: 'var(--ink-4)' }}>{tr('equipe', 'team')}</span>}
      </div>
    )
  }

  return (
    <div onMouseDown={e => e.stopPropagation()} style={{ position: 'absolute', left: x, top: y, zIndex: 20, display: 'flex', alignItems: 'flex-start', gap: 4 }}>
      <div style={{ ...box, width: COL_W, display: 'flex', flexDirection: 'column', gap: 3 }}>
        <input
          autoFocus value={q} onChange={e => setQ(e.target.value)} onBlur={onClose} onKeyDown={onKey}
          placeholder={tr('Chercher un node…', 'Search a node…')}
          style={{ fontSize: 12, padding: '5px 8px', background: 'var(--paper-2)', border: '1px solid var(--rule-2)', borderRadius: 5, color: 'var(--ink)', outline: 'none', fontFamily: 'var(--sans)' }}
        />
        {!entries && <span style={{ fontSize: 11, color: 'var(--ink-4)', padding: 4 }}>{tr('Chargement du catalogue…', 'Loading the catalogue…')}</span>}
        {ql
          ? <div style={{ maxHeight: 340, overflowY: 'auto' }}>
              {found.length === 0 && <span style={{ fontSize: 11, color: 'var(--ink-4)', padding: 4 }}>{tr('Aucun node', 'No node')}</span>}
              {found.map((e, i) => <NodeRow key={e.type} e={e} on={i === nodeIdx} onHover={() => setNodeIdx(i)} />)}
            </div>
          : FAMILIES.map((f, i) => {
              const info = FAMILY_INFO[f]
              const n = byFamily[f].length
              return (
                <div key={f} onMouseEnter={() => { setFamIdx(i); setNodeIdx(-1) }} onMouseDown={e => e.preventDefault()}
                  style={{ ...rowStyle(i === famIdx), color: n ? 'var(--ink)' : 'var(--ink-4)' }}>
                  <span style={{ width: 8, height: 8, borderRadius: 2, background: info.color }} />
                  <span style={{ flex: 1 }}>{lang === 'en' ? info.en : info.fr}</span>
                  <span style={{ fontSize: 10.5, color: 'var(--ink-4)' }}>{n}</span>
                  <ChevronRight size={12} color="var(--ink-4)" />
                </div>
              )
            })}
        <div style={{ fontSize: 10.5, color: 'var(--ink-4)', padding: '3px 4px 1px', borderTop: '1px solid var(--rule)' }}>
          {title ?? tr('Entree ajoute le node a la souris', 'Enter adds the node at the mouse')}
        </div>
      </div>
      {!ql && (
        <div style={{ ...box, width: COL_W, maxHeight: 360, overflowY: 'auto', marginTop: 34 + famIdx * 27 }}>
          {sub.length === 0 && <span style={{ fontSize: 11, color: 'var(--ink-4)', padding: 4, display: 'block' }}>{tr('Aucun node pour l\'instant', 'No node yet')}</span>}
          {sub.map((e, i) => <NodeRow key={e.type} e={e} on={i === nodeIdx} onHover={() => setNodeIdx(i)} />)}
        </div>
      )}
    </div>
  )
}
