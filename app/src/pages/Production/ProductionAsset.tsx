// ProductionAsset — root shows 4 big category tiles (Charas / Enviros /
// Props / FX). Click a tile → drilldown view listing just that category's
// assets, with a back button. Clicking empty background deselects.

import { useMemo } from 'react'
import { ChevronLeft } from 'lucide-react'
import { useI18n } from '../../i18n'
import type { ProductionAsset as Asset, ProductionAssetGroup, ProductionState } from '../../types'
import { CATEGORY_ORDER, categoryColor, categoryLabelKey } from './util'
import { CategoryTile, ProdBtn } from './ProdButtons'
import type { Selection } from './Production'

interface Props {
  state:        ProductionState
  setState:     (patch: (prev: ProductionState) => ProductionState) => void
  selection:    Selection
  setSelection: (s: Selection) => void
  activeCategory:    string | null
  setActiveCategory: (c: string | null) => void
}

export function ProductionAsset({
  state, setState, selection, setSelection,
  activeCategory, setActiveCategory,
}: Props) {
  const { t } = useI18n()

  // Bucket assets by class + counts for the root tiles.
  const countByClass = useMemo(() => {
    const m: Record<string, number> = {}
    for (const cls of CATEGORY_ORDER) m[cls] = 0
    for (const a of state.assets) {
      const c = a.class.toUpperCase()
      m[c] = (m[c] ?? 0) + 1
    }
    return m
  }, [state.assets])

  const deselectOnBackground: React.MouseEventHandler<HTMLDivElement> = (e) => {
    if (e.target === e.currentTarget) setSelection({ kind: 'none' })
  }

  // ── Root : 4 tiles ──────────────────────────────────────────────────────────
  if (!activeCategory) {
    return (
      <div
        onClick={deselectOnBackground}
        style={{ padding: '24px 20px', minHeight: '100%' }}
      >
        <div style={{
          display: 'flex', flexWrap: 'wrap', gap: 14,
        }}>
          {CATEGORY_ORDER.map(cls => (
            <CategoryTile
              key={cls}
              label={t(categoryLabelKey(cls))}
              count={countByClass[cls] ?? 0}
              color={categoryColor(cls)}
              onClick={() => { setActiveCategory(cls); setSelection({ kind: 'none' }) }}
            />
          ))}
        </div>
      </div>
    )
  }

  // ── Drilldown : one category ────────────────────────────────────────────────
  return (
    <div
      onClick={deselectOnBackground}
      style={{ padding: '16px 20px', minHeight: '100%', display: 'flex', flexDirection: 'column', gap: 16 }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <ProdBtn
          variant="ghost"
          size="sm"
          onClick={() => { setActiveCategory(null); setSelection({ kind: 'none' }) }}
        >
          <ChevronLeft size={11} strokeWidth={2} /> Retour
        </ProdBtn>
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8,
          fontFamily: 'var(--sans)', fontSize: 14, fontWeight: 600, color: 'var(--ink)',
        }}>
          <span style={{
            width: 9, height: 9, borderRadius: '50%',
            background: categoryColor(activeCategory), boxShadow: `0 0 6px ${categoryColor(activeCategory)}`,
          }} />
          {t(categoryLabelKey(activeCategory)) || activeCategory}
        </div>
      </div>

      <CategoryContent
        cls={activeCategory}
        state={state}
        setState={setState}
        selection={selection}
        setSelection={setSelection}
      />
    </div>
  )
}

// ── contents of one category ────────────────────────────────────────────────
function CategoryContent({ cls, state, setState, selection, setSelection }: {
  cls:          string
  state:        ProductionState
  setState:     (patch: (prev: ProductionState) => ProductionState) => void
  selection:    Selection
  setSelection: (s: Selection) => void
}) {
  const color = categoryColor(cls)

  const groups = useMemo(
    () => state.asset_groups.filter(g => g.class.toUpperCase() === cls).sort((a, b) => a.order - b.order),
    [state.asset_groups, cls],
  )
  const assets = useMemo(
    () => state.assets.filter(a => a.class.toUpperCase() === cls).sort((a, b) => a.order - b.order),
    [state.assets, cls],
  )
  const loose = assets.filter(a => !a.group_id)

  const empty = groups.length === 0 && loose.length === 0

  const onDropAsset = (draggedId: string, targetIdx: number, groupId: string | null) => {
    setState(prev => {
      const list = prev.assets.map(a => ({ ...a }))
      const src = list.find(a => a.id === draggedId)
      if (!src) return prev
      src.class    = cls
      src.group_id = groupId
      const bucket = list
        .filter(a => a.class.toUpperCase() === cls && a.group_id === groupId && a.id !== draggedId)
        .sort((x, y) => x.order - y.order)
      bucket.splice(Math.max(0, Math.min(targetIdx, bucket.length)), 0, src)
      const orderMap = new Map(bucket.map((a, i) => [a.id, i]))
      return { ...prev, assets: list.map(a => (orderMap.has(a.id) ? { ...a, order: orderMap.get(a.id)! } : a)) }
    })
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {empty && (
        <div style={{ padding: '20px 4px', fontSize: 11, color: 'var(--ink-4)' }}>
          Aucun asset ici. Utilise le menu Edit pour en créer.
        </div>
      )}

      {groups.map(g => (
        <GroupBox
          key={g.id}
          group={g}
          assets={assets.filter(a => a.group_id === g.id)}
          color={color}
          selection={selection}
          onSelect={setSelection}
          onDrop={(id, i) => onDropAsset(id, i, g.id)}
        />
      ))}

      <ChipRow
        color={color}
        assets={loose}
        selection={selection}
        onSelect={setSelection}
        onDrop={(id, i) => onDropAsset(id, i, null)}
      />
    </div>
  )
}

// ── group box ────────────────────────────────────────────────────────────────
function GroupBox({ group, assets, color, selection, onSelect, onDrop }: {
  group:     ProductionAssetGroup
  assets:    Asset[]
  color:     string
  selection: Selection
  onSelect:  (s: Selection) => void
  onDrop:    (draggedId: string, targetIdx: number) => void
}) {
  const active = selection.kind === 'group' && selection.id === group.id
  return (
    <div
      onClick={(e) => { e.stopPropagation(); onSelect({ kind: 'group', id: group.id }) }}
      style={{
        border: `1px solid ${active ? 'var(--accent)' : 'var(--rule-2)'}`,
        borderRadius: 10, padding: '10px 12px',
        background: active ? 'var(--accent-soft)' : 'var(--paper-2)',
        boxShadow: 'var(--shadow-xs)',
      }}
    >
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8,
        fontFamily: 'var(--mono)', fontSize: 10, letterSpacing: '0.08em', color: 'var(--ink-2)',
      }}>
        <span style={{ width: 6, height: 6, borderRadius: 3, background: color }} />
        <span style={{ textTransform: 'uppercase' }}>{group.name}</span>
      </div>
      <ChipRow color={color} assets={assets} selection={selection} onSelect={onSelect} onDrop={onDrop} />
    </div>
  )
}

// ── chip row ────────────────────────────────────────────────────────────────
function ChipRow({ color, assets, selection, onSelect, onDrop }: {
  color:     string
  assets:    Asset[]
  selection: Selection
  onSelect:  (s: Selection) => void
  onDrop:    (draggedId: string, targetIdx: number) => void
}) {
  return (
    <div
      onDragOver={e => { e.preventDefault(); e.dataTransfer.dropEffect = 'move' }}
      onDrop={e => {
        e.preventDefault()
        const id = e.dataTransfer.getData('text/flux-asset-id')
        if (!id) return
        onDrop(id, assets.length)
      }}
      style={{ display: 'flex', flexWrap: 'wrap', gap: 8, minHeight: 42 }}
    >
      {assets.map((a, i) => (
        <Chip
          key={a.id}
          asset={a}
          color={color}
          active={selection.kind === 'asset' && selection.id === a.id}
          onClick={() => onSelect({ kind: 'asset', id: a.id })}
          onDragStart={e => {
            e.dataTransfer.effectAllowed = 'move'
            e.dataTransfer.setData('text/flux-asset-id', a.id)
          }}
          onDropBefore={id => onDrop(id, i)}
        />
      ))}
    </div>
  )
}

// ── chip (big, rounded, solid-coloured) ─────────────────────────────────────
function Chip({ asset, color, active, onClick, onDragStart, onDropBefore }: {
  asset:        Asset
  color:        string
  active:       boolean
  onClick:      () => void
  onDragStart:  React.DragEventHandler
  onDropBefore: (draggedId: string) => void
}) {
  const isAuto = asset.origin === 'auto'
  return (
    <div
      draggable
      onDragStart={onDragStart}
      onDragOver={e => { e.preventDefault(); e.dataTransfer.dropEffect = 'move' }}
      onDrop={e => {
        e.preventDefault(); e.stopPropagation()
        const id = e.dataTransfer.getData('text/flux-asset-id')
        if (id && id !== asset.id) onDropBefore(id)
      }}
      onClick={(e) => { e.stopPropagation(); onClick() }}
      title={isAuto ? 'Adopté automatiquement depuis un publish' : ''}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 8,
        padding: '9px 16px', borderRadius: 10,
        border: `1px solid ${active ? 'var(--accent)' : color}`,
        outline: active ? '2px solid var(--accent-soft)' : 'none',
        background: color,
        color: 'var(--paper)',
        fontSize: 12, fontWeight: 600, fontFamily: 'var(--sans)',
        cursor: 'pointer',
        boxShadow: '0 2px 6px rgba(0,0,0,0.35), inset 0 1px 0 rgba(255,255,255,0.15)',
        transition: 'transform 0.14s, filter 0.14s',
      }}
      onMouseEnter={e => (e.currentTarget.style.transform = 'scale(1.04)')}
      onMouseLeave={e => (e.currentTarget.style.transform = 'scale(1)')}
    >
      <span style={{ fontFamily: 'var(--mono)', fontSize: 11, letterSpacing: '0.05em' }}>{asset.name}</span>
      {isAuto && (
        <span style={{
          fontFamily: 'var(--mono)', fontSize: 8, padding: '1px 5px', borderRadius: 3,
          background: 'rgba(0,0,0,0.32)', color: 'rgba(255,255,255,0.9)',
          letterSpacing: '0.06em', textTransform: 'uppercase',
        }}>auto</span>
      )}
    </div>
  )
}
