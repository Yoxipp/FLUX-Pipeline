import { useState } from 'react'
import { createPortal } from 'react-dom'
import * as Menu from '@radix-ui/react-dropdown-menu'
import { ArrowDownWideNarrow, Check } from 'lucide-react'
import type { ProductionDepartment, ProductionSequence } from '../../types'
import type { DepartmentSort } from './tableRows'

export function DepartmentSortMenu({ department, sort, onSort }: { department: ProductionDepartment; sort: DepartmentSort; onSort: (sort: DepartmentSort) => void }) {
  const [open, setOpen] = useState(false)
  const [anchor, setAnchor] = useState({ x: 0, y: 0 })
  const sorted = sort?.id === department.id
  return <>
    <button className="tracking-department-heading" aria-label={`Trier ${department.name}`} onContextMenu={e => { e.preventDefault(); setAnchor({ x: e.clientX, y: e.clientY }); setOpen(true) }}
      onKeyDown={e => { if (e.key === 'ContextMenu' || (e.shiftKey && e.key === 'F10')) { e.preventDefault(); const rect = e.currentTarget.getBoundingClientRect(); setAnchor({ x: rect.left, y: rect.bottom }); setOpen(true) } }}>{department.name}{sorted && <ArrowDownWideNarrow size={12} />}</button>
    <Menu.Root open={open} onOpenChange={setOpen} modal={false}>{createPortal(<Menu.Trigger tabIndex={-1} aria-hidden style={{ position: 'fixed', left: anchor.x, top: anchor.y, width: 1, height: 1, opacity: 0, pointerEvents: 'none' }} />, document.body)}
      <Menu.Portal><Menu.Content className="production-context-menu" align="start" collisionPadding={10}>
        <Menu.Label className="production-menu-artist">Sort · {department.name}</Menu.Label>
        {department.statuses.map(status => <Menu.Item key={status} className="production-menu-item" onSelect={() => onSort({ id: department.id, first: status })}><span className="tracking-status" data-status={status}>{status}</span>{sorted && sort.first === status && <Check size={13} />}</Menu.Item>)}
        {sort && <><Menu.Separator className="production-menu-separator" /><Menu.Item className="production-menu-item" onSelect={() => onSort(null)}>Ordre de production</Menu.Item></>}
      </Menu.Content></Menu.Portal>
    </Menu.Root>
  </>
}

export function SequenceEditMenu({ sequence, onEdit }: { sequence: ProductionSequence; onEdit: () => void }) {
  const [open, setOpen] = useState(false)
  const [anchor, setAnchor] = useState({ x: 0, y: 0 })
  return <>
    <span role="button" tabIndex={0} className="tracking-sequence-name" aria-label={`Actions de ${sequence.name}`}
      onContextMenu={e => { e.preventDefault(); setAnchor({ x: e.clientX, y: e.clientY }); setOpen(true) }}
      onKeyDown={e => { if (e.key === 'ContextMenu' || (e.shiftKey && e.key === 'F10')) { e.preventDefault(); const rect = e.currentTarget.getBoundingClientRect(); setAnchor({ x: rect.left, y: rect.bottom }); setOpen(true) } }}>{sequence.name}</span>
    <Menu.Root open={open} onOpenChange={setOpen} modal={false}>{createPortal(<Menu.Trigger tabIndex={-1} aria-hidden style={{ position: 'fixed', left: anchor.x, top: anchor.y, width: 1, height: 1, opacity: 0, pointerEvents: 'none' }} />, document.body)}
      <Menu.Portal><Menu.Content className="production-context-menu" align="start"><Menu.Label className="production-menu-artist">{sequence.name}</Menu.Label><Menu.Item className="production-menu-item" onSelect={onEdit}>Edit</Menu.Item></Menu.Content></Menu.Portal>
    </Menu.Root>
  </>
}
