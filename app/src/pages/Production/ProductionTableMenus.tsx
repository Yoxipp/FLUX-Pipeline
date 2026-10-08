import * as Menu from '@radix-ui/react-dropdown-menu'
import { Check, ChevronDown, ChevronRight, Filter, UserRound } from 'lucide-react'
import type { ProductionDepartment, ProductionSequence } from '../../types'
import type { Selection } from './Production'
import { showAllDepartments, toggleDepartment, visibleDepartments } from '../../lib/workProfiles'
import { openWorkProfile } from '../../components/shared/WorkProfileDialog'

export type ShowFilter = { kind: 'all' } | { kind: 'mine' } | { kind: 'seq'; id: string }

// Departments: columns preset by the work profile (ADR 0043), ticked by hand here.
// `departmentPref` is the comma separated names of every mode; empty = all columns.
export function ProductionShowMenu({ filter, onChange, sequences, departments, departmentPref, onDepartmentPref }: {
  filter: ShowFilter; onChange: (filter: ShowFilter) => void; sequences: ProductionSequence[]
  departments: ProductionDepartment[]; departmentPref: string; onDepartmentPref: (pref: string) => void
}) {
  const label = filter.kind === 'seq' ? sequences.find(s => s.id === filter.id)?.name ?? 'Seq' : filter.kind === 'mine' ? 'Mine' : 'All'
  const shown = visibleDepartments(departments, departmentPref)
  const partial = shown.length < departments.length
  return <Menu.Root><Menu.Trigger className="tracking-show"><Filter size={13} />Show · {label}{partial && <span className="tracking-show-count">{shown.length}/{departments.length} dép.</span>}<ChevronDown size={12} /></Menu.Trigger><Menu.Portal><Menu.Content className="production-context-menu" align="end" collisionPadding={10}>
    <Menu.Label className="production-menu-artist">Lignes</Menu.Label>
    <Menu.Item className="production-menu-item" onSelect={() => onChange({ kind: 'all' })}>All{filter.kind === 'all' && <Check size={13} />}</Menu.Item>
    <Menu.Sub><Menu.SubTrigger className="production-menu-item">Seq<ChevronRight size={13} /></Menu.SubTrigger><Menu.Portal><Menu.SubContent className="production-context-menu" sideOffset={5} collisionPadding={10}>
      {[...sequences].sort((a, b) => a.order - b.order).map(s => <Menu.Item key={s.id} className="production-menu-item" onSelect={() => onChange({ kind: 'seq', id: s.id })}>{s.name}{s.label ? ` · ${s.label}` : ''}{filter.kind === 'seq' && filter.id === s.id && <Check size={13} />}</Menu.Item>)}
      {!sequences.length && <Menu.Label className="production-menu-artist">Aucune séquence</Menu.Label>}
    </Menu.SubContent></Menu.Portal></Menu.Sub>
    <Menu.Item className="production-menu-item" onSelect={() => onChange({ kind: 'mine' })}>Mine{filter.kind === 'mine' && <Check size={13} />}</Menu.Item>
    {departments.length > 0 && <>
      <Menu.Separator className="production-menu-separator" />
      <Menu.Label className="production-menu-artist">Départements</Menu.Label>
      <Menu.Item className="production-menu-item" onSelect={e => { e.preventDefault(); onDepartmentPref(showAllDepartments(departments, departmentPref)) }}>Tous{!partial && <Check size={13} />}</Menu.Item>
      {departments.map(d => {
        const on = shown.includes(d)
        return <Menu.CheckboxItem key={d.id} className="production-menu-item" checked={on} disabled={on && shown.length === 1}
          onSelect={e => e.preventDefault()} onCheckedChange={() => onDepartmentPref(toggleDepartment(departments, departmentPref, d.name))}>
          {d.name}{on && <Check size={13} />}
        </Menu.CheckboxItem>
      })}
      <Menu.Separator className="production-menu-separator" />
      <Menu.Item className="production-menu-item" onSelect={openWorkProfile}><UserRound size={13} />Profil de travail…</Menu.Item>
    </>}
  </Menu.Content></Menu.Portal></Menu.Root>
}

export function ProductionRelatedMenu({ items, onOpen }: { items: { id: string; label: string; kind: 'asset' | 'shot'; count?: number; missing?: boolean }[]; onOpen: (selection: Selection) => void }) {
  if (!items.length) return <span className="tracking-muted">—</span>
  return <Menu.Root><Menu.Trigger className="tracking-related-summary">{'{'}{items[0].label}{'}'}{items.length > 1 ? ` +${items.length - 1}…` : ''}<ChevronDown size={11} /></Menu.Trigger><Menu.Portal><Menu.Content className="production-context-menu production-related-menu" align="start" collisionPadding={10}>
    {items.map(item => <Menu.Item key={item.id} disabled={item.missing} className="production-menu-item" onSelect={() => onOpen({ kind: item.kind, id: item.id })}>{item.label}{(item.count ?? 1) > 1 ? ` ×${item.count}` : ''}{item.missing ? ' (manquant)' : ''}</Menu.Item>)}
  </Menu.Content></Menu.Portal></Menu.Root>
}
