import * as Menu from '@radix-ui/react-dropdown-menu'
import { Check, ChevronDown, ChevronRight } from 'lucide-react'
import type { ProductionSequence } from '../../types'
import type { Selection } from './Production'

export type ShowFilter = { kind: 'all' } | { kind: 'mine' } | { kind: 'seq'; id: string }

export function ProductionShowMenu({ filter, onChange, sequences }: { filter: ShowFilter; onChange: (filter: ShowFilter) => void; sequences: ProductionSequence[] }) {
  const label = filter.kind === 'seq' ? sequences.find(s => s.id === filter.id)?.name ?? 'Seq' : filter.kind === 'mine' ? 'Mine' : 'All'
  return <Menu.Root><Menu.Trigger className="tracking-show">Show · {label}<ChevronDown size={12} /></Menu.Trigger><Menu.Portal><Menu.Content className="production-context-menu" align="end" collisionPadding={10}>
    <Menu.Item className="production-menu-item" onSelect={() => onChange({ kind: 'all' })}>All{filter.kind === 'all' && <Check size={13} />}</Menu.Item>
    <Menu.Sub><Menu.SubTrigger className="production-menu-item">Seq<ChevronRight size={13} /></Menu.SubTrigger><Menu.Portal><Menu.SubContent className="production-context-menu" sideOffset={5} collisionPadding={10}>
      {[...sequences].sort((a, b) => a.order - b.order).map(s => <Menu.Item key={s.id} className="production-menu-item" onSelect={() => onChange({ kind: 'seq', id: s.id })}>{s.name}{s.label ? ` · ${s.label}` : ''}{filter.kind === 'seq' && filter.id === s.id && <Check size={13} />}</Menu.Item>)}
      {!sequences.length && <Menu.Label className="production-menu-artist">Aucune séquence</Menu.Label>}
    </Menu.SubContent></Menu.Portal></Menu.Sub>
    <Menu.Item className="production-menu-item" onSelect={() => onChange({ kind: 'mine' })}>Mine{filter.kind === 'mine' && <Check size={13} />}</Menu.Item>
  </Menu.Content></Menu.Portal></Menu.Root>
}

export function ProductionRelatedMenu({ items, onOpen }: { items: { id: string; label: string; kind: 'asset' | 'shot'; count?: number; missing?: boolean }[]; onOpen: (selection: Selection) => void }) {
  if (!items.length) return <span className="tracking-muted">—</span>
  return <Menu.Root><Menu.Trigger className="tracking-related-summary">{'{'}{items[0].label}{'}'}{items.length > 1 ? ` +${items.length - 1}…` : ''}<ChevronDown size={11} /></Menu.Trigger><Menu.Portal><Menu.Content className="production-context-menu production-related-menu" align="start" collisionPadding={10}>
    {items.map(item => <Menu.Item key={item.id} disabled={item.missing} className="production-menu-item" onSelect={() => onOpen({ kind: item.kind, id: item.id })}>{item.label}{(item.count ?? 1) > 1 ? ` ×${item.count}` : ''}{item.missing ? ' (manquant)' : ''}</Menu.Item>)}
  </Menu.Content></Menu.Portal></Menu.Root>
}
