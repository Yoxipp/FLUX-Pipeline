import { useRef, useState, type MouseEvent } from 'react'
import { createPortal } from 'react-dom'
import * as Menu from '@radix-ui/react-dropdown-menu'
import * as Dialog from '@radix-ui/react-dialog'
import { ArrowDown, Check, ChevronRight, Flag, FolderOpen, Plus, Trash2, Upload, UserRound, X } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { api } from '../../api/client'
import type { ProductionState, ProductionTask, Settings } from '../../types'
import { assigneeIncludes, detailStatus, STATUS_LABELS, STATUS_TOKENS, taskStatus } from './tracking'
import { taskPublisherPrefill, type TaskEntity } from './taskActions'
import { applyTaskSelection, type TaskActionTarget } from './taskSelection'
import { Tooltip, TooltipContent, TooltipTrigger } from '../../components/shared/ui'
import { expandFluxPath } from './util'
import './tracking.css'
import { viewportRect } from '../../components/shared/tooltipPosition'
import { PRIORITIES, PRIORITY_LABEL, priorityOf } from './taskPriority'

interface Props {
  project: string; state: ProductionState; setState: (patch: (prev: ProductionState) => ProductionState) => void
  entity: TaskEntity; task: ProductionTask; subtask?: string; status?: string; statuses?: string[]
  disabled?: boolean; onClick?: () => void; title?: string
  selectionControl?: { label: string; selected: boolean; onClick: (event: MouseEvent<HTMLButtonElement>) => void }
  onContextTask?: () => void
  actionTargets?: TaskActionTarget[]
  tooltipScale?: number
}

/** Priority mark shown left of the badge and in the menu: high = red "!", low = blue down arrow, same slot. */
function PriorityMark({ priority }: { priority: 'high' | 'low' }) {
  const label = `Priorité ${PRIORITY_LABEL[priority].toLowerCase()}`
  return <span className="tracking-priority-mark" data-priority={priority} aria-label={label} title={label}>
    {priority === 'high' ? '!' : <ArrowDown size={12} strokeWidth={3} aria-hidden />}
  </span>
}

export function TaskStatusBadge({ project, state, setState, entity, task, subtask = '', status: suppliedStatus, statuses = STATUS_TOKENS, disabled, onClick, selectionControl, onContextTask, actionTargets, tooltipScale }: Props) {
  const navigate = useNavigate()
  const button = useRef<HTMLButtonElement>(null)
  const selectionButton = useRef<HTMLButtonElement>(null)
  const [open, setOpen] = useState(false)
  const [anchor, setAnchor] = useState({ x: 0, y: 0 })
  const [settings, setSettings] = useState<Settings | null>(null)
  const [assignOpen, setAssignOpen] = useState(false)
  const [removeOpen, setRemoveOpen] = useState(false)
  const [users, setUsers] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const key = `${task.name.toUpperCase()}${subtask ? `|${subtask.toUpperCase()}` : ''}`
  const artist = entity.task_details?.[key]?.assignee ?? entity.task_details?.[task.name.toUpperCase()]?.assignee ?? ''
  const hoverArtists = [...new Set([artist, ...(!subtask ? task.known_subtasks.map(sub => entity.task_details?.[`${task.name.toUpperCase()}|${sub.toUpperCase()}`]?.assignee ?? '') : [])].filter(Boolean))].join(', ')
  // Priority (retake 07): only high / low are marked on the badge, normal stays quiet.
  const priority = priorityOf(entity.task_details?.[key])
  const status = suppliedStatus ?? (subtask ? detailStatus(entity.task_details?.[key]) : taskStatus({ ...entity, class: 'class' in entity ? entity.class : 'SEQ', group_id: null }, task))
  const targets = actionTargets?.length && (open || assignOpen || removeOpen) ? actionTargets : [{ entity, task, subtask, status, statuses }]
  const multiple = targets.length > 1
  const availableStatuses = multiple ? statuses.filter(token => targets.every(target => !target.statuses || target.statuses.includes(token))) : statuses
  const targetPriorities = [...new Set(targets.map(target =>
    priorityOf(target.entity.task_details?.[`${target.task.name.toUpperCase()}${target.subtask ? `|${target.subtask.toUpperCase()}` : ''}`])))]
  const targetArtists = [...new Set(targets.map(target => {
    const targetKey = `${target.task.name.toUpperCase()}${target.subtask ? `|${target.subtask.toUpperCase()}` : ''}`
    return target.entity.task_details?.[targetKey]?.assignee ?? target.entity.task_details?.[target.task.name.toUpperCase()]?.assignee ?? ''
  }))]
  const menuArtist = targetArtists.length === 1 ? targetArtists[0] || 'Aucun artiste assigné' : 'Artistes différents'
  const assignedToAll = (name: string) => targets.every(target => assigneeIncludes(target.entity.task_details?.[`${target.task.name.toUpperCase()}${target.subtask ? `|${target.subtask.toUpperCase()}` : ''}`]?.assignee, name))
  // Several artists per task: a click in the list toggles that artist, the dialog stays open.
  const toggleArtist = (name: string) => setState(prev => applyTaskSelection(prev, targets, { kind: assignedToAll(name) ? 'artist_remove' : 'artist_add', value: name }))
  const description = multiple ? `${targets.length} tâches sélectionnées` : `${entity.name} · ${task.name}${subtask ? ` · ${subtask}` : ''}`
  const showMenu = (x: number, y: number) => {
    if (disabled) return
    setAnchor({ x, y }); setOpen(true)
    void api.getSettings().then(setSettings).catch(() => {})
  }
  const assign = (name: string) => { setState(prev => applyTaskSelection(prev, targets, { kind: 'artist', value: name })); setAssignOpen(false) }
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
      setState(prev => applyTaskSelection(prev, targets, { kind: 'artist_add', value: current.username! }))
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
    {selectionControl && <button ref={selectionButton} className="tracking-task-select" aria-label={selectionControl.label} aria-pressed={selectionControl.selected}
      onClick={e => {
        // A plain click on an empty cell opens the menu so a task can be added right there.
        if (!status && !e.ctrlKey && !e.metaKey && !e.shiftKey) { onContextTask?.(); showMenu(e.clientX, e.clientY); return }
        selectionControl.onClick(e)
      }}
      onContextMenu={e => { e.preventDefault(); onContextTask?.(); showMenu(e.clientX, e.clientY) }}
      onKeyDown={e => { if (e.key === 'ContextMenu' || (e.shiftKey && e.key === 'F10')) { e.preventDefault(); onContextTask?.(); const rect = viewportRect(e.currentTarget); showMenu(rect.left, rect.bottom) } }} />}
    {status && priority !== 'normal' && <PriorityMark priority={priority} />}
    <Tooltip scale={tooltipScale}><TooltipTrigger asChild><button ref={button} className="tracking-status" data-status={STATUS_TOKENS.includes(status) ? status : 'UNKNOWN'} disabled={disabled}
      aria-label={`${task.name} : ${status || 'Aucun statut - clic droit'}`}
      data-empty={!status || undefined}
      data-selectable-empty={!status && selectionControl ? true : undefined}
      tabIndex={!status && selectionControl ? -1 : undefined}
      onClick={event => {
        // Ctrl / Meta / Shift + click selects the badge itself; a plain click opens the retakes.
        if (selectionControl && (event.ctrlKey || event.metaKey || event.shiftKey)) { selectionControl.onClick(event); return }
        if (!status) return
        if (onClick) onClick()
        else { const rect = viewportRect(button.current!); showMenu(rect.left, rect.bottom) }
      }}
      onContextMenu={e => { e.preventDefault(); onContextTask?.(); showMenu(e.clientX, e.clientY) }}
      onKeyDown={e => { if (e.key === 'ContextMenu' || (e.shiftKey && e.key === 'F10')) { e.preventDefault(); onContextTask?.(); const rect = viewportRect(e.currentTarget); showMenu(rect.left, rect.bottom) } }}>{status || <Plus size={11} className="tracking-empty-add" aria-hidden />}</button></TooltipTrigger><TooltipContent>{hoverArtists || 'Aucun artiste assigné'}{priority !== 'normal' ? ` · priorité ${PRIORITY_LABEL[priority].toLowerCase()}` : ''}</TooltipContent></Tooltip>
    <Menu.Root open={open} onOpenChange={setOpen} modal={false}>
      {createPortal(<Menu.Trigger aria-hidden tabIndex={-1} style={{ position: 'fixed', left: anchor.x, top: anchor.y, width: 1, height: 1, opacity: 0, pointerEvents: 'none' }} />, document.body)}
      <Menu.Portal><Menu.Content className="production-context-menu" side="bottom" align="start" collisionPadding={10} onCloseAutoFocus={e => { e.preventDefault(); (!status && selectionControl ? selectionButton : button).current?.focus() }}>
        {multiple && <Menu.Label className="production-menu-artist">{description}</Menu.Label>}
        <Menu.Label className="production-menu-artist"><UserRound size={14} /><span>{menuArtist}</span></Menu.Label>
        <Menu.Separator className="production-menu-separator" />
        {availableStatuses.map(token => <Menu.Item className="production-menu-item" key={token} onSelect={() => setState(prev => applyTaskSelection(prev, targets, { kind: 'status', value: token }))}>
          <span className="tracking-status" data-status={STATUS_TOKENS.includes(token) ? token : 'UNKNOWN'}>{token}</span><span>{STATUS_LABELS[token] ?? token}</span>{(multiple ? targets.every(target => target.status === token) : token === status) && <Check size={13} />}
        </Menu.Item>)}
        <Menu.Separator className="production-menu-separator" />
        <Menu.Sub><Menu.SubTrigger className="production-menu-item"><UserRound size={14} />Artiste<ChevronRight size={13} className="production-menu-chevron" /></Menu.SubTrigger>
          <Menu.Portal><Menu.SubContent className="production-context-menu" sideOffset={5} collisionPadding={10}>
            <Menu.Item className="production-menu-item" onSelect={() => void takeTask()}>{multiple ? 'Prendre les tasks' : 'Prendre la task'}</Menu.Item>
            <Menu.Item className="production-menu-item" onSelect={() => void pickArtist()}>Assigner artiste</Menu.Item>
            {targetArtists.some(Boolean) && <Menu.Item className="production-menu-item production-menu-delete" onSelect={() => assign('')}><X size={14} />Supprimer l’assignation</Menu.Item>}
          </Menu.SubContent></Menu.Portal></Menu.Sub>
        <Menu.Sub><Menu.SubTrigger className="production-menu-item"><Flag size={14} />Priorité<ChevronRight size={13} className="production-menu-chevron" /></Menu.SubTrigger>
          <Menu.Portal><Menu.SubContent className="production-context-menu" sideOffset={5} collisionPadding={10}>
            {PRIORITIES.map(p => <Menu.Item key={p} className="production-menu-item" onSelect={() => setState(prev => applyTaskSelection(prev, targets, { kind: 'priority', value: p }))}>
              <span className="production-menu-priority">{p !== 'normal' && <PriorityMark priority={p} />}</span>{PRIORITY_LABEL[p]}{targetPriorities.length === 1 && targetPriorities[0] === p && <Check size={13} />}
            </Menu.Item>)}
          </Menu.SubContent></Menu.Portal></Menu.Sub>
        {!multiple && <><Menu.Item className="production-menu-item" onSelect={() => navigate('/publisher', { state: { prefill: taskPublisherPrefill(project, state, entity, task) } })}><Upload size={14} />Publish here</Menu.Item>
        <Menu.Item className="production-menu-item" onSelect={() => void folder()}><FolderOpen size={14} />Folder manager</Menu.Item></>}
        {(multiple ? targets.some(target => target.status) : status) && <><Menu.Separator className="production-menu-separator" /><Menu.Item className="production-menu-item production-menu-delete" onSelect={() => setRemoveOpen(true)}><Trash2 size={14} />{multiple ? 'Supprimer les badges' : 'Supprimer le badge'}</Menu.Item></>}
      </Menu.Content></Menu.Portal>
    </Menu.Root>
    <Dialog.Root open={removeOpen} onOpenChange={setRemoveOpen}><Dialog.Portal><Dialog.Overlay className="production-dialog-overlay" /><Dialog.Content className="production-dialog" onCloseAutoFocus={e => { e.preventDefault(); (!status && selectionControl ? selectionButton : button).current?.focus() }}>
      <div className="production-dialog-heading"><Dialog.Title>{multiple ? 'Supprimer les badges ?' : 'Supprimer le badge ?'}</Dialog.Title><Dialog.Close aria-label="Fermer"><X size={16} /></Dialog.Close></div>
      <Dialog.Description>{description}. Les tâches, les artistes et les notes sont conservés.</Dialog.Description>
      <div className="production-dialog-actions"><Dialog.Close>Annuler</Dialog.Close><button onClick={() => { setState(prev => applyTaskSelection(prev, targets, { kind: 'clear' })); setRemoveOpen(false) }}>Supprimer</button></div>
    </Dialog.Content></Dialog.Portal></Dialog.Root>
    <Dialog.Root open={assignOpen} onOpenChange={setAssignOpen}><Dialog.Portal><Dialog.Overlay className="production-dialog-overlay" /><Dialog.Content className="production-dialog" onCloseAutoFocus={e => { e.preventDefault(); (!status && selectionControl ? selectionButton : button).current?.focus() }}>
      <div className="production-dialog-heading"><Dialog.Title>Assigner artistes</Dialog.Title><Dialog.Close aria-label="Fermer"><X size={16} /></Dialog.Close></div>
      <Dialog.Description>{description}. Cliquez plusieurs artistes pour les ajouter ou les retirer.</Dialog.Description>
      <input autoFocus aria-label="Rechercher un artiste" placeholder="Rechercher un artiste…" value={search} onChange={e => setSearch(e.target.value)} />
      <div className="production-artist-list">{loading ? <p>Chargement…</p> : error ? <p role="alert">{error}<button onClick={() => void pickArtist()}>Réessayer</button></p> : <>{users.filter(u => u.toLowerCase().includes(search.toLowerCase())).map(user => <button key={user} aria-pressed={assignedToAll(user)} onClick={() => toggleArtist(user)}><UserRound size={14} /><span>{user}</span>{assignedToAll(user) && <Check size={14} />}</button>)}{!users.filter(u => u.toLowerCase().includes(search.toLowerCase())).length && <p>Aucun artiste trouvé.</p>}<button onClick={() => assign('')}>Retirer l’assignation</button></>}</div>
    </Dialog.Content></Dialog.Portal></Dialog.Root>
  </>
}
