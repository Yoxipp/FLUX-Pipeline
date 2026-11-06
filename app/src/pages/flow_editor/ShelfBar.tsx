// ShelfBar.tsx — Shelf (03_EDITEUR §1): one tab per family (its colour), the common nodes
// of the active family below (spec `shelf` order, else the first ones). P4 (03 §4): drag =
// created at the drop point (dataTransfer application/x-flux-node = type id), click = centre
// of the view. "Catalogue" opens the drawer of every node (NodePalette).

import { useEffect, useState } from 'react'
import { Library } from 'lucide-react'
import { FAMILIES, FAMILY_INFO } from './families'
import { iconFor } from './icons'
import { DRAG_MIME } from './NetworkPane'
import type { Family } from './types'
import type { CatalogEntry } from './v1_adapter'
import { useTr } from './useTr'

const SHELF_MAX = 12

export function shelfItems(catalog: CatalogEntry[] | null, fam: Family): CatalogEntry[] {
  const list = (catalog ?? []).filter(e => e.family === fam)
  const ranked = list.filter(e => e.shelf !== null && e.shelf !== undefined).sort((a, b) => (a.shelf ?? 0) - (b.shelf ?? 0))
  return (ranked.length ? ranked : list).slice(0, SHELF_MAX)
}

export function ShelfBar({ catalog, paletteOpen, onPick, onTogglePalette, flowKey, startFamily = 'flux' }: {
  catalog: CatalogEntry[] | null
  paletteOpen: boolean
  onPick: (e: CatalogEntry) => void
  onTogglePalette: () => void
  flowKey?: string             // the open flow: the tab is reset when it changes
  startFamily?: Family         // R1 audit F4: Evenements for a flow that only has its start
}) {
  const { tr, lang } = useTr()
  const [fam, setFam] = useState<Family>(startFamily)
  useEffect(() => { setFam(startFamily) }, [flowKey])  // eslint-disable-line react-hooks/exhaustive-deps
  const items = shelfItems(catalog, fam)
  return (
    <div style={{ flexShrink: 0, borderBottom: '1px solid var(--rule)', background: 'var(--paper)' }}>
      <div style={{ height: 24, display: 'flex', alignItems: 'stretch', gap: 2, padding: '0 8px' }}>
        {FAMILIES.map(f => {
          const info = FAMILY_INFO[f]
          const on = f === fam
          return (
            <div
              key={f}
              onClick={() => setFam(f)}
              style={{
                display: 'flex', alignItems: 'center', gap: 5, padding: '0 8px', cursor: 'pointer', fontSize: 11,
                color: on ? 'var(--ink)' : 'var(--ink-3)',
                borderBottom: `2px solid ${on ? info.color : 'transparent'}`,
              }}
            >
              <span style={{ width: 7, height: 7, borderRadius: 2, background: info.color }} />
              {lang === 'en' ? info.en : info.fr}
            </div>
          )
        })}
        <div style={{ flex: 1 }} />
        <button type="button" className={`flow-tool${paletteOpen ? ' on' : ''}`} onClick={onTogglePalette} style={{ height: 22, alignSelf: 'center' }}
                title={tr('Tous les nodes, par famille', 'Every node, by family')}>
          <Library size={12} /> {tr('Catalogue', 'Catalogue')}
        </button>
      </div>
      <div style={{ height: 40, display: 'flex', alignItems: 'center', gap: 6, padding: '0 10px', overflowX: 'auto' }}>
        {items.length === 0 && (
          <span style={{ fontSize: 11, color: 'var(--ink-4)' }}>
            {catalog ? tr('Aucun node de cette famille pour l\'instant', 'No node of this family yet') : tr('Chargement…', 'Loading…')}
          </span>
        )}
        {items.map(e => {
          const info = FAMILY_INFO[e.family]
          const Icon = iconFor(e.icon, e.family)
          return (
            <div
              key={e.type}
              draggable
              onDragStart={ev => { ev.dataTransfer.setData(DRAG_MIME, e.type); ev.dataTransfer.effectAllowed = 'copy' }}
              onClick={() => onPick(e)}
              title={(lang === 'en' ? e.doc_en : e.doc_fr) || e.label}
              style={{
                display: 'flex', alignItems: 'center', gap: 5, height: 26, padding: '0 9px', borderRadius: 5, cursor: 'grab',
                fontSize: 11, color: 'var(--ink-2)', background: 'var(--paper-2)', border: '1px solid var(--rule-2)',
                borderLeft: `3px solid ${info.color}`, whiteSpace: 'nowrap',
              }}
            >
              <Icon size={13} strokeWidth={1.75} color={info.color} />
              {e.label}
            </div>
          )
        })}
      </div>
    </div>
  )
}
