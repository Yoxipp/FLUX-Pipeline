import { useState } from 'react'
import { createPortal } from 'react-dom'
import * as Menu from '@radix-ui/react-dropdown-menu'
import * as Dialog from '@radix-ui/react-dialog'
import { ArrowDownWideNarrow, Check, UserRound, X } from 'lucide-react'
import type { ProductionDepartment, ProductionSequence, ProductionState } from '../../types'
import { api } from '../../api/client'
import { assignDepartment } from './taskActions'
import type { DepartmentSort } from './tableRows'
import { viewportRect } from '../../components/shared/tooltipPosition'

export function DepartmentSortMenu({ department, sort, onSort, setState }: { department: ProductionDepartment; sort: DepartmentSort; onSort: (sort: DepartmentSort) => void; setState?: (patch: (prev: ProductionState) => ProductionState) => void }) {
  const [open, setOpen] = useState(false)
  const [assignOpen, setAssignOpen] = useState(false)
  const [users, setUsers] = useState<string[] | null>(null)
  const [search, setSearch] = useState('')
  const pickArtist = () => { setAssignOpen(true); setSearch(''); setUsers(null); void api.listUsers().then(r => setUsers(r.users)).catch(() => setUsers([])) }
  const assign = (name: string) => { setState?.(prev => assignDepartment(prev, department, name)); setAssignOpen(false) }
  const [anchor, setAnchor] = useState({ x: 0, y: 0 })
  const sorted = sort?.id === department.id
  return <>
    <button className="tracking-department-heading" aria-label={`Actions ${department.name}`} title="Clic gauche ou droit : trier, assigner" onClick={e => { setAnchor({ x: e.clientX, y: e.clientY }); setOpen(true) }} onContextMenu={e => { e.preventDefault(); setAnchor({ x: e.clientX, y: e.clientY }); setOpen(true) }}
      onKeyDown={e => { if (e.key === 'ContextMenu' || (e.shiftKey && e.key === 'F10')) { e.preventDefault(); const rect = viewportRect(e.currentTarget); setAnchor({ x: rect.left, y: rect.bottom }); setOpen(true) } }}>{department.name}{sorted && <ArrowDownWideNarrow size={12} />}</button>
    <Menu.Root open={open} onOpenChange={setOpen} modal={false}>{createPortal(<Menu.Trigger tabIndex={-1} aria-hidden style={{ position: 'fixed', left: anchor.x, top: anchor.y, width: 1, height: 1, opacity: 0, pointerEvents: 'none' }} />, document.body)}
      <Menu.Portal><Menu.Content className="production-context-menu" align="start" collisionPadding={10}>
        <Menu.Label className="production-menu-artist">Sort · {department.name}</Menu.Label>
        {department.statuses.map(status => <Menu.Item key={status} className="production-menu-item" onSelect={() => onSort({ id: department.id, first: status })}><span className="tracking-status" data-status={status}>{status}</span>{sorted && sort.first === status && <Check size={13} />}</Menu.Item>)}
        {sort && <><Menu.Separator className="production-menu-separator" /><Menu.Item className="production-menu-item" onSelect={() => onSort(null)}>Ordre de production</Menu.Item></>}
        {setState && <><Menu.Separator className="production-menu-separator" />
          <Menu.Item className="production-menu-item" onSelect={pickArtist}><UserRound size={14} />Assigner le département</Menu.Item>
          <Menu.Item className="production-menu-item production-menu-delete" onSelect={() => assign('')}><X size={14} />Retirer l’assignation du département</Menu.Item></>}
      </Menu.Content></Menu.Portal>
    </Menu.Root>
    <Dialog.Root open={assignOpen} onOpenChange={setAssignOpen}><Dialog.Portal><Dialog.Overlay className="production-dialog-overlay" /><Dialog.Content className="production-dialog">
      <div className="production-dialog-heading"><Dialog.Title>Assigner {department.name}</Dialog.Title><Dialog.Close aria-label="Fermer"><X size={16} /></Dialog.Close></div>
      <Dialog.Description>Toutes les tâches {department.name}. Les sous-tâches gardent leur propre artiste.</Dialog.Description>
      <input autoFocus aria-label="Rechercher un artiste" placeholder="Rechercher un artiste…" value={search} onChange={e => setSearch(e.target.value)} />
      <div className="production-artist-list">{users === null ? <p>Chargement…</p> : <>{users.filter(u => u.toLowerCase().includes(search.toLowerCase())).map(user => <button key={user} onClick={() => assign(user)}><UserRound size={14} /><span>{user}</span></button>)}{!users.some(u => u.toLowerCase().includes(search.toLowerCase())) && <p>Aucun artiste trouvé.</p>}</>}</div>
    </Dialog.Content></Dialog.Portal></Dialog.Root>
  </>
}

export function SequenceEditMenu({ sequence, onEdit }: { sequence: ProductionSequence; onEdit: () => void }) {
  const [open, setOpen] = useState(false)
  const [anchor, setAnchor] = useState({ x: 0, y: 0 })
  return <>
    <span role="button" tabIndex={0} className="tracking-sequence-name" aria-label={`Actions de ${sequence.name}`}
      onContextMenu={e => { e.preventDefault(); setAnchor({ x: e.clientX, y: e.clientY }); setOpen(true) }}
      onKeyDown={e => { if (e.key === 'ContextMenu' || (e.shiftKey && e.key === 'F10')) { e.preventDefault(); const rect = viewportRect(e.currentTarget); setAnchor({ x: rect.left, y: rect.bottom }); setOpen(true) } }}>{sequence.name}</span>
    <Menu.Root open={open} onOpenChange={setOpen} modal={false}>{createPortal(<Menu.Trigger tabIndex={-1} aria-hidden style={{ position: 'fixed', left: anchor.x, top: anchor.y, width: 1, height: 1, opacity: 0, pointerEvents: 'none' }} />, document.body)}
      <Menu.Portal><Menu.Content className="production-context-menu" align="start"><Menu.Label className="production-menu-artist">{sequence.name}</Menu.Label><Menu.Item className="production-menu-item" onSelect={onEdit}>Edit</Menu.Item></Menu.Content></Menu.Portal>
    </Menu.Root>
  </>
}
