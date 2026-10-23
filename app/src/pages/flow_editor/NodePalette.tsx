// NodePalette.tsx — Catalogue drawer (03_EDITEUR §9, the old editor's Palette): every node
// of GET /flows/catalog by family, a search (label, type, aliases, doc), the team nodes
// tagged. Drag = created at the drop point, click = centre of the view (03 §4).
// Team node files that failed to load are listed at the bottom.

import { useMemo, useState } from 'react'
import { X } from 'lucide-react'
import { FAMILIES, FAMILY_INFO } from './families'
import { iconFor } from './icons'
import { DRAG_MIME } from './NetworkPane'
import type { CatalogEntry } from './v1_adapter'
import { useTr } from './useTr'

export const PALETTE_W = 240

export function NodePalette({ catalog, errors, onPick, onClose }: {
  catalog: CatalogEntry[] | null
  errors: { file: string; error: string }[]
  onPick: (e: CatalogEntry) => void
  onClose: () => void
}) {
  const { tr, lang } = useTr()
  const [q, setQ] = useState('')
  const ql = q.trim().toLowerCase()
  const groups = useMemo(() => FAMILIES.map(f => ({
    f,
    items: (catalog ?? []).filter(e => e.family === f)
      .filter(e => !ql || [e.label, e.type, ...e.aliases, e.doc_fr ?? '', e.doc_en ?? ''].join(' ').toLowerCase().includes(ql))
      .sort((a, b) => a.label.localeCompare(b.label)),
  })).filter(g => g.items.length), [catalog, ql])

  return (
    <aside style={{ width: PALETTE_W, flexShrink: 0, borderRight: '1px solid var(--rule)', background: 'var(--paper)', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 10px 6px' }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--ink)', flex: 1 }}>{tr('Catalogue', 'Catalogue')}</span>
        <button type="button" className="flow-tool" onClick={onClose} title={tr('Fermer', 'Close')}><X size={12} /></button>
      </div>
      <div style={{ padding: '0 10px 6px' }}>
        <input value={q} onChange={e => setQ(e.target.value)} placeholder={tr('Chercher un node…', 'Search a node…')}
               style={{ width: '100%', fontSize: 12, padding: '4px 8px', background: 'var(--paper-2)', border: '1px solid var(--rule-2)', borderRadius: 5, color: 'var(--ink)', outline: 'none', fontFamily: 'var(--sans)' }} />
      </div>
      <div style={{ flex: 1, overflowY: 'auto', padding: '0 6px 8px' }}>
        {!catalog && <div style={{ fontSize: 11, color: 'var(--ink-4)', padding: 4 }}>{tr('Chargement…', 'Loading…')}</div>}
        {groups.map(({ f, items }) => {
          const info = FAMILY_INFO[f]
          return (
            <div key={f} style={{ marginBottom: 6 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 10.5, color: 'var(--ink-4)', padding: '4px 4px 2px', textTransform: 'uppercase', letterSpacing: 0.4 }}>
                <span style={{ width: 7, height: 7, borderRadius: 2, background: info.color }} />{lang === 'en' ? info.en : info.fr}
              </div>
              {items.map(e => {
                const Icon = iconFor(e.icon, e.family)
                return (
                  <div key={e.type} draggable
                       onDragStart={ev => { ev.dataTransfer.setData(DRAG_MIME, e.type); ev.dataTransfer.effectAllowed = 'copy' }}
                       onClick={() => onPick(e)}
                       title={(lang === 'en' ? e.doc_en || e.doc_fr : e.doc_fr || e.doc_en) || e.type}
                       className="flow-palette-item">
                    <Icon size={13} strokeWidth={1.75} color={info.color} />
                    <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{e.label}</span>
                    {e.origin === 'equipe' && <span className="tag">{tr('equipe', 'team')}</span>}
                  </div>
                )
              })}
            </div>
          )
        })}
        {errors.length > 0 && (
          <div style={{ fontSize: 11, color: 'var(--err)', padding: '6px 4px', borderTop: '1px solid var(--rule)' }}>
            {errors.map(x => <div key={x.file} title={x.error}>{x.file} : {x.error}</div>)}
          </div>
        )}
      </div>
    </aside>
  )
}
