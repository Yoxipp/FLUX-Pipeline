import { useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import * as Menu from '@radix-ui/react-dropdown-menu'
import * as Dialog from '@radix-ui/react-dialog'
import { Check, ChevronRight, FolderOpen, Upload, UserRound, X } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { api } from '../../api/client'
import type { ProductionState, ProductionTask, Settings } from '../../types'
import { detailStatus, STATUS_LABELS, STATUS_TOKENS, taskStatus } from './tracking'
import { patchTaskArtist, setTaskStatus, taskPublisherPrefill, type TaskEntity } from './taskActions'
import { expandFluxPath } from './util'
import './tracking.css'

interface Props {
  project: string; state: ProductionState; setState: (patch: (prev: ProductionState) => ProductionState) => void
  entity: TaskEntity; task: ProductionTask; subtask?: string; status?: string; statuses?: string[]
  disabled?: boolean; onClick?: () => void; title?: string
}

export function TaskStatusBadge({ project, state, setState, entity, task, subtask = '', status: suppliedStatus, statuses = STATUS_TOKENS, disabled, onClick, title }: Props) {
  const navigate = useNavigate()
  const button = useRef<HTMLButtonElement>(null)
  const [open, setOpen] = useState(false)
  const [anchor, setAnchor] = useState({ x: 0, y: 0 })
  const [settings, setSettings] = useState<Settings | null>(null)
  const [assignOpen, setAssignOpen] = useState(false)
  const [users, setUsers] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const key = `${task.name.toUpperCase()}${subtask ? `|${subtask.toUpperCase()}` : ''}`
  const artist = entity.task_details?.[key]?.assignee ?? entity.task_details?.[task.name.toUpperCase()]?.assignee ?? ''
  const status = suppliedStatus ?? (subtask ? detailStatus(entity.task_details?.[key]) : taskStatus({ ...entity, class: 'class' in entity ? entity.class : 'SEQ', group_id: null }, task))
  const showMenu = (x: number, y: number) => {
    if (disabled) return
    setAnchor({ x, y }); setOpen(true)
    void api.getSettings().then(setSettings).catch(() => {})
  }
  const assign = (name: string) => { setState(prev => patchTaskArtist(prev, entity.id, task, subtask, name)); setAssignOpen(false) }
  const pickArtist = async () => {
    setAssignOpen(true); setLoading(true); setError(''); setSearch('')
    try { const result = await api.listUsers(); setUsers(result.users) }
    catch { setError('Impossible de charger les artistes du pipe. Réessayez.') }
    finally { setLoading(false) }
  }
  const takeTask = async () => {
    try {
      const current = settings ?? await api.getSettings()
      if (!current.username?.trim()) { toast.error('Renseignez votre nom d’artiste dans les paramètres.'); return }
      assign(current.username)
    } catch { toast.error('Impossible de charger votre profil.') }
  }
  const folder = async () => {
    try {
      const isShot = 'seq_id' in entity, isAsset = 'class' in entity
      const result = await api.resolveRefPath(project, { kind: isAsset ? 'asset' : isShot ? 'shot' : 'seq',
        ...(isAsset ? { class_token: entity.class, name: entity.name } : { seq: isShot ? state.sequences.find(s => s.id === entity.seq_id)?.name : entity.name, shot: isShot ? entity.name : undefined }),
        task: task.type_tokens[0] || task.name, subtask: subtask || undefined })
      const current = settings ?? await api.getSettings()
      const relative = result.rel_path
      navigate('/projects', { state: { openPath: expandFluxPath(`$FLUX/DOSSIER_PROJETS/${project}/${relative}`, current.workspace) } })
    } catch (e) { toast.error(e instanceof Error ? e.message : 'Dossier indisponible') }
  }
  return <>
    <button ref={button} className="tracking-status" data-status={STATUS_TOKENS.includes(status) ? status : 'UNKNOWN'} disabled={disabled}
      title={title ?? `${task.name} · ${STATUS_LABELS[status] ?? status} · Clic droit pour les actions`} aria-label={`${task.name} : ${status || 'Aucun statut - clic droit'}`}
      data-empty={!status || undefined}
      onClick={status ? onClick ?? (() => { const rect = button.current!.getBoundingClientRect(); showMenu(rect.left, rect.bottom) }) : undefined}
      onContextMenu={e => { e.preventDefault(); showMenu(e.clientX, e.clientY) }}
      onKeyDown={e => { if (e.key === 'ContextMenu' || (e.shiftKey && e.key === 'F10')) { e.preventDefault(); const rect = e.currentTarget.getBoundingClientRect(); showMenu(rect.left, rect.bottom) } }}>{status}</button>
    <Menu.Root open={open} onOpenChange={setOpen} modal={false}>
      {createPortal(<Menu.Trigger aria-hidden tabIndex={-1} style={{ position: 'fixed', left: anchor.x, top: anchor.y, width: 1, height: 1, opacity: 0, pointerEvents: 'none' }} />, document.body)}
      <Menu.Portal><Menu.Content className="production-context-menu" side="bottom" align="start" collisionPadding={10} onCloseAutoFocus={e => { e.preventDefault(); button.current?.focus() }}>
        <Menu.Label className="production-menu-artist"><UserRound size={14} /><span>{artist || 'Aucun artiste assigné'}</span></Menu.Label>
        <Menu.Separator className="production-menu-separator" />
        {statuses.map(token => <Menu.Item className="production-menu-item" key={token} onSelect={() => setState(prev => setTaskStatus(prev, entity, task, subtask, token))}>
          <span className="tracking-status" data-status={STATUS_TOKENS.includes(token) ? token : 'UNKNOWN'}>{token}</span><span>{STATUS_LABELS[token] ?? token}</span>{token === status && <Check size={13} />}
        </Menu.Item>)}
        <Menu.Separator className="production-menu-separator" />
        <Menu.Sub><Menu.SubTrigger className="production-menu-item"><UserRound size={14} />Artiste<ChevronRight size={13} className="production-menu-chevron" /></Menu.SubTrigger>
          <Menu.Portal><Menu.SubContent className="production-context-menu" sideOffset={5} collisionPadding={10}>
            <Menu.Item className="production-menu-item" onSelect={() => void takeTask()}>Prendre la task</Menu.Item>
            <Menu.Item className="production-menu-item" onSelect={() => void pickArtist()}>Assigner artiste</Menu.Item>
          </Menu.SubContent></Menu.Portal></Menu.Sub>
        <Menu.Item className="production-menu-item" onSelect={() => navigate('/publisher', { state: { prefill: taskPublisherPrefill(project, state, entity, task) } })}><Upload size={14} />Publish here</Menu.Item>
        <Menu.Item className="production-menu-item" onSelect={() => void folder()}><FolderOpen size={14} />Folder manager</Menu.Item>
      </Menu.Content></Menu.Portal>
    </Menu.Root>
    <Dialog.Root open={assignOpen} onOpenChange={setAssignOpen}><Dialog.Portal><Dialog.Overlay className="production-dialog-overlay" /><Dialog.Content className="production-dialog" onCloseAutoFocus={e => { e.preventDefault(); button.current?.focus() }}>
      <div className="production-dialog-heading"><Dialog.Title>Assigner artiste</Dialog.Title><Dialog.Close aria-label="Fermer"><X size={16} /></Dialog.Close></div>
      <Dialog.Description>{entity.name} · {task.name}{subtask ? ` · ${subtask}` : ''}</Dialog.Description>
      <input autoFocus aria-label="Rechercher un artiste" placeholder="Rechercher un artiste…" value={search} onChange={e => setSearch(e.target.value)} />
      <div className="production-artist-list">{loading ? <p>Chargement…</p> : error ? <p role="alert">{error}<button onClick={() => void pickArtist()}>Réessayer</button></p> : <>{users.filter(u => u.toLowerCase().includes(search.toLowerCase())).map(user => <button key={user} onClick={() => assign(user)}><UserRound size={14} /><span>{user}</span>{artist === user && <Check size={14} />}</button>)}{!users.filter(u => u.toLowerCase().includes(search.toLowerCase())).length && <p>Aucun artiste trouvé.</p>}<button onClick={() => assign('')}>Retirer l’assignation</button></>}</div>
    </Dialog.Content></Dialog.Portal></Dialog.Root>
  </>
}
