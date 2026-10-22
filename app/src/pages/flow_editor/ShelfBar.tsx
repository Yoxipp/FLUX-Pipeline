// ShelfBar.tsx — Shelf (03_EDITEUR §1): one tab per family (its colour), the common nodes
// of the active family below. P0: display only (adding a node comes in P4).

import { useState } from 'react'
import { FAMILIES, FAMILY_INFO } from './families'
import { iconFor } from './icons'
import type { Family } from './types'
import type { CatalogEntry } from './v1_adapter'
import { useTr } from './useTr'

const SHELF_MAX = 12

export function ShelfBar({ catalog, onPick }: { catalog: CatalogEntry[] | null; onPick: (e: CatalogEntry) => void }) {
  const { tr, lang } = useTr()
  const [fam, setFam] = useState<Family>('flux')
  const items = (catalog ?? []).filter(e => e.family === fam).slice(0, SHELF_MAX)
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
      </div>
      <div style={{ height: 40, display: 'flex', alignItems: 'center', gap: 6, padding: '0 10px', overflowX: 'auto' }}>
        {items.length === 0 && (
          <span style={{ fontSize: 11, color: 'var(--ink-4)' }}>
            {catalog ? tr('Aucun node de cette famille pour l\'instant (nodes v2 en phase P2)', 'No node of this family yet (v2 nodes in phase P2)') : tr('Chargement…', 'Loading…')}
          </span>
        )}
        {items.map(e => {
          const info = FAMILY_INFO[e.family]
          const Icon = iconFor(undefined, e.family)
          return (
            <div
              key={e.type}
              onClick={() => onPick(e)}
              title={(lang === 'en' ? e.doc_en : e.doc_fr) || e.label}
              style={{
                display: 'flex', alignItems: 'center', gap: 5, height: 26, padding: '0 9px', borderRadius: 5, cursor: 'pointer',
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
