// TabMenu.tsx — Tab menu at the mouse (03_EDITEUR §4, taken from ActionGraph.tsx TabMenu):
// search, arrows, Enter, Escape. Names starting with the search first, family dot per row.
// P0: search only, nothing is added (editing comes in P4).

import { useEffect, useMemo, useState } from 'react'
import { FAMILY_INFO } from './families'
import { iconFor } from './icons'
import type { CatalogEntry } from './v1_adapter'
import { useTr } from './useTr'

const TAB_MENU_MAX = 14

export function TabMenu({ entries, x, y, onPick, onClose }: {
  entries: CatalogEntry[] | null
  x: number
  y: number
  onPick: (e: CatalogEntry) => void
  onClose: () => void
}) {
  const { tr, lang } = useTr()
  const [q, setQ] = useState('')
  const [idx, setIdx] = useState(0)
  const items = useMemo(() => {
    const ql = q.trim().toLowerCase()
    const hay = (e: CatalogEntry) => [e.label, e.type, ...e.aliases, e.doc_fr ?? '', e.doc_en ?? ''].join(' ').toLowerCase()
    const starts = (e: CatalogEntry) => [e.label, ...e.aliases].some(n => n.toLowerCase().startsWith(ql)) ? 0 : 1
    return (entries ?? [])
      .filter(e => !ql || hay(e).includes(ql))
      .sort((a, b) => starts(a) - starts(b) || a.family.localeCompare(b.family) || a.label.localeCompare(b.label))
      .slice(0, TAB_MENU_MAX)
  }, [entries, q])
  useEffect(() => { setIdx(0) }, [q])

  const pick = (e: CatalogEntry | undefined) => { if (e) { onPick(e); onClose() } }
  return (
    <div
      onMouseDown={e => e.stopPropagation()}
      style={{
        position: 'absolute', left: x, top: y, zIndex: 20, width: 300,
        background: 'var(--paper)', border: '1px solid var(--rule-2)', borderRadius: 8,
        boxShadow: 'var(--shadow)', padding: 6, display: 'flex', flexDirection: 'column', gap: 4,
      }}
    >
      <input
        autoFocus value={q} onChange={e => setQ(e.target.value)}
        onBlur={onClose}
        onKeyDown={e => {
          if (e.key === 'Escape' || e.key === 'Tab') { e.preventDefault(); onClose() }
          else if (e.key === 'ArrowDown') { e.preventDefault(); setIdx(i => Math.min(i + 1, items.length - 1)) }
          else if (e.key === 'ArrowUp') { e.preventDefault(); setIdx(i => Math.max(i - 1, 0)) }
          else if (e.key === 'Enter') { e.preventDefault(); pick(items[idx]) }
        }}
        placeholder={tr('Chercher un node…', 'Search a node…')}
        style={{ fontSize: 12, padding: '5px 8px', background: 'var(--paper-2)', border: '1px solid var(--rule-2)', borderRadius: 5, color: 'var(--ink)', outline: 'none' }}
      />
      {!entries && <span style={{ fontSize: 11, color: 'var(--ink-4)', padding: 4 }}>{tr('Chargement du catalogue…', 'Loading the catalogue…')}</span>}
      {entries && items.length === 0 && <span style={{ fontSize: 11, color: 'var(--ink-4)', padding: 4 }}>{tr('Aucun node', 'No node')}</span>}
      <div style={{ maxHeight: 320, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 2 }}>
        {items.map((it, i) => {
          const fam = FAMILY_INFO[it.family]
          const Icon = iconFor(undefined, it.family)
          const doc = lang === 'en' ? it.doc_en || it.doc_fr : it.doc_fr || it.doc_en
          return (
            <div
              key={it.type}
              onMouseDown={e => { e.preventDefault(); pick(it) }}
              onMouseEnter={() => setIdx(i)}
              style={{ padding: '4px 7px', borderRadius: 5, cursor: 'pointer', background: i === idx ? 'var(--accent-soft)' : 'transparent' }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, fontWeight: 600, color: 'var(--ink)' }}>
                <Icon size={12} strokeWidth={1.75} color={fam.color} />
                {it.label}
                <span style={{ fontSize: 10.5, color: 'var(--ink-4)', fontWeight: 400 }}>
                  {lang === 'en' ? fam.en : fam.fr}{it.origin === 'equipe' ? tr(' · équipe', ' · team') : ''}
                </span>
              </div>
              {doc && <div style={{ fontSize: 11, color: 'var(--ink-3)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{doc}</div>}
            </div>
          )
        })}
      </div>
      <div style={{ fontSize: 10.5, color: 'var(--ink-4)', padding: '2px 4px', borderTop: '1px solid var(--rule)' }}>
        {tr('Ajout de node : edition en phase P4', 'Adding a node: editing comes in phase P4')}
      </div>
    </div>
  )
}
