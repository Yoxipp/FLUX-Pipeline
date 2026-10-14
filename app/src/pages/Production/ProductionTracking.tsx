import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import * as Dropdown from '@radix-ui/react-dropdown-menu'
import { CreateMenu, type CreateKind } from './CreateMenu'
import { CalendarClock, Check, ChevronDown, ChevronRight, ImagePlus, Search, Settings2, UserRound, X } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '../../api/client'
import { useSettings } from '../../hooks/useSettings'
import type { ProductionDependency, ProductionState, ProductionTask, ProductionThumbnail } from '../../types'
import type { Selection } from './Production'
import { blockers, dependencyLabel, effectiveCasting, effectiveTasks, ensureTrackingTask, taskAssignedTo, trackingTaskStatus, trackingDepartments, trackingLocked } from './tracking'
import type { TrackingEntity } from './tracking'
import { TaskStatusBadge } from './TaskStatusBadge'
import { EntityContextMenu } from './EntityContextMenu'
import { ShotDeadlineBadge, useShotCalendar } from './ShotDeadlineBadge'
import { DepartmentSortMenu, SequenceEditMenu } from './TrackingMenus'
import { productionRowGroups, type DepartmentSort, type PersonalSort } from './tableRows'
import { entityDeadline } from './taskPriority'
import { previewCandidates, previewSources, type PreviewSource } from './previewEdit'
import { usePreviewSource } from './previewSourceStore'
import { useI18n } from '../../i18n'
import { ProductionShowMenu, ProductionRelatedMenu } from './ProductionTableMenus'
import { useProductionShow } from './useProductionShow'
import { useWorkProfile } from '../../WorkProfileContext'
import { visibleDepartments } from '../../lib/workProfiles'
import { emptyTaskSelection, pruneTaskSelection, selectProductionTask, taskSelectionKey, trackingCellTasks, type TaskActionTarget } from './taskSelection'
import { Tooltip, TooltipContent, TooltipTrigger } from '../../components/shared/ui'
import './tracking.css'

interface Props {
  project: string
  mode: 'shot' | 'asset'
  state: ProductionState
  setState: (patch: (prev: ProductionState) => ProductionState) => void
  selection: Selection
  setSelection: (s: Selection) => void
  onOpenDetail: (selection: Selection, task: ProductionTask, subtask?: string) => void
  onEdit: () => void
  onNew: (kind?: CreateKind) => void
  onSettings: () => void
  onOpenEntity: (selection: Selection) => void
  onlyEntityId?: string
  loading: boolean
}

const LS_SORT_DEADLINE_MINE = 'flux.production.sort.deadlineMine'
const IDENTITY_WIDTH = 280, TIMING_WIDTH = 110, CASTING_WIDTH = 170, DEPARTMENT_MIN_WIDTH = 110

export function ProductionTracking({ project, mode, state, setState, selection, setSelection, onOpenDetail, onEdit, onNew, onSettings, onOpenEntity, onlyEntityId, loading }: Props) {
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useProductionShow(project, mode, onlyEntityId)
  const [sort, setSort] = useState<DepartmentSort>(null)
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  // Retake B3: asset rows unfolded to show one row per subtask.
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set())
  // Retake B4: "Deadline + Me concerne" sort, a per-machine view preference.
  const [deadlineMine, setDeadlineMineState] = useState<boolean>(() => {
    try { return localStorage.getItem(LS_SORT_DEADLINE_MINE) === '1' } catch { return false }
  })
  const setDeadlineMine = (next: boolean) => {
    setDeadlineMineState(next)
    try { localStorage.setItem(LS_SORT_DEADLINE_MINE, next ? '1' : '0') } catch { /* storage blocked */ }
  }
  const [previewSource, setPreviewSource] = usePreviewSource()
  const { t } = useI18n()
  const [taskSelection, setTaskSelection] = useState(emptyTaskSelection)
  // New 100% baseline is 90% of the original interface. Old saved zoom is retired.
  const [zoom, setZoom] = useState(1)
  const scrollRef = useRef<HTMLDivElement>(null)
  const { settings } = useSettings()
  const username = settings?.username ?? ''
  const calendar = useShotCalendar(project, mode === 'shot' || deadlineMine)
  const { prefs: workPrefs, setPref: setWorkPref } = useWorkProfile()
  // Every department of the mode (dependencies, Show menu) vs. the columns ticked in Show.
  const allDepartments = useMemo(() => trackingDepartments(state, mode), [state, mode])
  const departments = useMemo(() => visibleDepartments(allDepartments, workPrefs.productionDepartments), [allDepartments, workPrefs.productionDepartments])
  const changeZoom = (next: number) => setZoom(Math.round(Math.max(0.65, Math.min(1.4, next)) * 100) / 100)
  useEffect(() => {
    const node = scrollRef.current
    if (!node) return
    const wheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return
      e.preventDefault()
      setZoom(prev => Math.round(Math.max(0.65, Math.min(1.4, prev + (e.deltaY < 0 ? 0.05 : -0.05))) * 100) / 100)
    }
    node.addEventListener('wheel', wheel, { passive: false })
    return () => node.removeEventListener('wheel', wheel)
  }, [])
  const entities: TrackingEntity[] = useMemo(() => {
    const list = mode === 'shot' ? state.shots : state.assets
    const search = query.trim().toLowerCase()
    return list.filter(e => {
      if (onlyEntityId && e.id !== onlyEntityId) return false
      if (filter.kind === 'mine' && !effectiveTasks(state, e).some(t => taskAssignedTo(e, t, username))) return false
      if (filter.kind === 'seq') {
        if ('seq_id' in e ? e.seq_id !== filter.id : !state.shots.some(sh => sh.seq_id === filter.id && effectiveCasting(state, sh).some(l => l.id === e.id))) return false
      }
      const parent = 'seq_id' in e ? state.sequences.find(s => s.id === e.seq_id)?.name ?? '' : e.class
      const related = 'seq_id' in e ? effectiveCasting(state, e).map(l => state.assets.find(a => a.id === l.id)?.name ?? l.ref).join(' ') : ''
      return `${parent} ${e.name} ${'label' in e ? e.label ?? '' : ''} ${related}`.toLowerCase().includes(search)
    }).sort((a, b) => {
      const parentOrder = (e: TrackingEntity) => 'seq_id' in e ? state.sequences.find(s => s.id === e.seq_id)?.order ?? 0 : 0
      return parentOrder(a) - parentOrder(b) || a.order - b.order || a.name.localeCompare(b.name, undefined, { numeric: true })
    })
  }, [state, mode, query, filter, username, onlyEntityId])
  const personal: PersonalSort | null = deadlineMine ? {
    mine: e => effectiveTasks(state, e).some(task => taskAssignedTo(e, task, username)),
    deadline: e => entityDeadline('seq_id' in e ? state.sequences.find(s => s.id === e.seq_id)?.name ?? '' : '', e.name, calendar.items),
  } : null
  const groups = productionRowGroups(state, entities, mode, departments, sort, mode === 'shot' && filter.kind === 'all' && !query && !onlyEntityId ? state.sequences : [], personal)
  const toggleGroup = (id: string) => setCollapsed(prev => { const next = new Set(prev); if (next.has(id)) next.delete(id); else next.add(id); return next })
  const assetGroupLabel = (cls: string) => ['CHAR', 'PROPS', 'ENV'].includes(cls) ? t(`prod.assetGroup.${cls}`) : cls
  const visibleTargets: TaskActionTarget[] = groups.filter(group => !collapsed.has(group.id)).flatMap(group => group.entities.flatMap(entity =>
    departments.flatMap((dep, columnOrder) => trackingCellTasks(state, entity, dep, filter.kind === 'mine', username).map(task => ({
      entity, task, departmentId: dep.id, columnOrder, statuses: dep.statuses, status: trackingTaskStatus(entity, task, dep),
    }))),
  ))
  const visibleKeys = visibleTargets.map(taskSelectionKey)
  const visibleSignature = JSON.stringify(visibleKeys)
  useEffect(() => { setTaskSelection(prev => pruneTaskSelection(prev, visibleKeys)) }, [visibleSignature])
  const selectedKeys = new Set(taskSelection.keys)
  const selectedTargets = [...new Map(visibleTargets.filter(target => selectedKeys.has(taskSelectionKey(target))).map(target => [taskSelectionKey(target), target])).values()]
  const columnCount = departments.length + (mode === 'shot' ? 3 : 2)
  const selectEntity = (entity: TrackingEntity): Selection => ({ kind: 'seq_id' in entity ? 'shot' : 'asset', id: entity.id })
  const openCell = (entity: TrackingEntity, task: ProductionTask) => {
    setState(prev => ensureTrackingTask(prev, entity.id, task))
    onOpenDetail(selectEntity(entity), task)
  }
  const patchThumbnail = (entityId: string, thumbnail: ProductionThumbnail) => setState(prev => ({
    ...prev, shots: prev.shots.map(e => e.id === entityId ? { ...e, thumbnail } : e), assets: prev.assets.map(e => e.id === entityId ? { ...e, thumbnail } : e),
  }))
  const beginCreate = (kind: CreateKind) => {
    const seq = filter.kind === 'seq' ? state.sequences.find(s => s.id === filter.id) : selection.kind === 'seq' ? state.sequences.find(s => s.id === selection.id) : state.sequences[0]
    setSelection(mode === 'shot' && seq ? { kind: 'seq', id: seq.id } : { kind: 'none' })
    onNew(kind)
  }
  return <div className="production-tracking">
    <div className="tracking-toolbar">
      <label className="tracking-search"><Search size={14} /><input aria-label="Rechercher dans la production" placeholder={mode === 'shot' ? 'Rechercher un shot, un asset...' : 'Rechercher un asset...'} value={query} onChange={e => setQuery(e.target.value)} /></label>
      <span className="tracking-count">{entities.length} / {mode === 'shot' ? state.shots.length : state.assets.length}</span>
      <div className="tracking-spacer" />
      <button className="tracking-sort-toggle" aria-pressed={deadlineMine} title={t('prod.sort.deadlineMineHint')} onClick={() => setDeadlineMine(!deadlineMine)}><CalendarClock size={13} /> {t('prod.sort.deadlineMine')}</button>
      <ProductionShowMenu filter={filter} onChange={setFilter} sequences={state.sequences}
        departments={allDepartments} departmentPref={workPrefs.productionDepartments} onDepartmentPref={v => setWorkPref('productionDepartments', v)} />
      <button onClick={onSettings}><Settings2 size={13} /> Settings</button>
      <CreateMenu mode={mode} hasSequences={state.sequences.length > 0} onCreate={beginCreate} />
    </div>
    <div ref={scrollRef} className="tracking-scroll" tabIndex={0} aria-label="Tableau de suivi de production" onKeyDown={e => {
      if (e.key === 'Escape' && e.currentTarget.contains(e.target as Node)) { setTaskSelection(emptyTaskSelection()); return }
      if (e.target !== e.currentTarget || (!e.ctrlKey && !e.metaKey)) return
      if (['+', '=', '-', '0'].includes(e.key)) { e.preventDefault(); changeZoom(e.key === '0' ? 1 : zoom + (e.key === '-' ? -0.1 : 0.1)) }
    }}>
      <table className="tracking-table" style={{ zoom, minWidth: IDENTITY_WIDTH + (mode === 'shot' ? TIMING_WIDTH : 0) + CASTING_WIDTH + departments.length * DEPARTMENT_MIN_WIDTH }}>
        {/* Fixed layout: Shot / Timing / Casting keep their width, hidden departments widen the department columns. */}
        <colgroup><col style={{ width: IDENTITY_WIDTH }} />{mode === 'shot' && <col style={{ width: TIMING_WIDTH }} />}<col style={{ width: CASTING_WIDTH }} />{departments.map(d => <col key={d.id} />)}</colgroup>
        <thead><tr><th className="tracking-identity">{mode === 'shot' ? 'Shot' : 'Asset'}</th>{mode === 'shot' && <th>Timing</th>}<th>{mode === 'shot' ? 'Casting' : 'Shots liés'}</th>{departments.map(d => <th key={d.id} className="tracking-department-column"><DepartmentSortMenu department={d} sort={sort} onSort={setSort} setState={setState} /></th>)}</tr></thead>
        {groups.map(group => <tbody key={group.id} className="tracking-sequence-block">
          {mode === 'asset' && <>
            <tr className="tracking-sequence-gap" aria-hidden><td colSpan={columnCount} /></tr>
            <tr className="tracking-sequence-heading"><td colSpan={columnCount}><div className="tracking-sequence-bar">
              <button aria-label={`${collapsed.has(group.id) ? t('prod.table.expand') : t('prod.table.collapse')} ${assetGroupLabel(group.assetClass ?? '')}`} aria-expanded={!collapsed.has(group.id)} onClick={() => toggleGroup(group.id)}>{collapsed.has(group.id) ? <ChevronRight size={14} /> : <ChevronDown size={14} />}</button>
              <strong className="tracking-asset-class">{assetGroupLabel(group.assetClass ?? '')}</strong>
              <span className="tracking-sequence-count">{group.entities.length} {t('prod.assetGroup.count')}</span>
            </div></td></tr>
          </>}
          {mode === 'shot' && <>
            <tr className="tracking-sequence-gap" aria-hidden><td colSpan={columnCount} /></tr>
            <tr className="tracking-sequence-heading"><td colSpan={columnCount}><div className="tracking-sequence-bar">
              <button aria-label={`${collapsed.has(group.id) ? 'Déplier' : 'Replier'} ${group.sequence?.name ?? 'Séquence manquante'}`} aria-expanded={!collapsed.has(group.id)} onClick={() => toggleGroup(group.id)}>{collapsed.has(group.id) ? <ChevronRight size={14} /> : <ChevronDown size={14} />}</button>
              {group.sequence ? <SequenceEditMenu sequence={group.sequence} onEdit={() => { setSelection({ kind: 'seq', id: group.sequence!.id }); onEdit() }} /> : <span>Séquence manquante</span>}
              {group.sequence?.label && <span className="tracking-muted">{group.sequence.label}</span>}<span className="tracking-sequence-count">{group.entities.length} shots</span>
            </div></td></tr>
          </>}
          {!collapsed.has(group.id) && group.entities.map(entity => {
          const isShot = 'seq_id' in entity
          const isSelected = (selection.kind === 'asset' || selection.kind === 'shot') && selection.id === entity.id
          const links = isShot ? effectiveCasting(state, entity) : []
          const linkedShots = !isShot ? state.shots.filter(sh => effectiveCasting(state, sh).some(l => l.id === entity.id)) : []
          const relatedItems = isShot ? links.map(link => { const asset = state.assets.find(a => a.id === link.id); return { id: link.id, label: asset?.name ?? link.ref, kind: 'asset' as const, count: link.count, missing: !asset } }) : linkedShots.map(sh => ({ id: sh.id, label: `${state.sequences.find(s => s.id === sh.seq_id)?.name}/${sh.name}`, kind: 'shot' as const }))
          const subRows = isShot ? [] : subtaskRows(state, entity, departments, filter.kind === 'mine', username)
          const expanded = expandedRows.has(entity.id)
          return <Fragment key={entity.id}><tr data-selected={isSelected || undefined}>
            <td className="tracking-identity"><div className="tracking-name-cell">
              {!isShot && <button className="tracking-row-expand" disabled={!subRows.length} aria-expanded={expanded}
                aria-label={`${expanded ? t('prod.table.collapse') : t('prod.table.expand')} ${t('prod.table.subtasks')} ${entity.name}`}
                title={subRows.length ? t('prod.table.subtasks') : t('prod.table.noSubtask')}
                onClick={() => setExpandedRows(prev => { const next = new Set(prev); if (next.has(entity.id)) next.delete(entity.id); else next.add(entity.id); return next })}>
                {expanded && subRows.length ? <ChevronDown size={13} /> : <ChevronRight size={13} />}</button>}
              <Thumbnail key={`${project}:${entity.id}`} project={project} entity={entity} locked={trackingLocked(state, entity)} onChange={thumbnail => patchThumbnail(entity.id, thumbnail)}
                previewMenu={isShot ? { sources: previewSources(previewCandidates(state, entity)), current: previewSource, onPick: setPreviewSource, title: t('prod.preview.source'), hint: t('prod.preview.sourceHint') } : undefined} />
              <div className="tracking-name">
                {!isShot && <span className="tracking-parent">{entity.class}</span>}
                <EntityContextMenu project={project} state={state} entity={entity} setState={setState} setSelection={setSelection} onEdit={onEdit} />
                {isShot && <div className="tracking-label-row">{entity.label && <span className="tracking-label" title={entity.label}>{entity.label}</span>}<ShotDeadlineBadge state={state} shot={entity} calendar={calendar} /></div>}
              </div>
            </div></td>
            {mode === 'shot' && <td className="tracking-timing">{isShot && entity.frame_start != null && entity.frame_end != null ? <><span>{entity.frame_start}–{entity.frame_end}</span><small>{entity.frame_end - entity.frame_start + 1} f</small></> : <span className="tracking-muted">—</span>}</td>}
            <td className="tracking-relations"><ProductionRelatedMenu items={relatedItems} onOpen={onOpenEntity} /></td>
            {departments.map(dep => {
              const visible = trackingCellTasks(state, entity, dep, filter.kind === 'mine', username)
              const blocked = blockers(state, entity, dep, allDepartments)
              return <td key={dep.id} className="tracking-status-cell" onClick={event => {
                if (!event.currentTarget.contains(event.target as Node) || (event.target as HTMLElement).closest('button')) return
                const additive = event.ctrlKey || event.metaKey
                if (!additive && !event.shiftKey) setTaskSelection(emptyTaskSelection())
                else if (visible.length === 1) setTaskSelection(prev => selectProductionTask(prev, visibleTargets, taskSelectionKey({ entity, task: visible[0] }), additive, event.shiftKey))
              }}><div className="tracking-task-badges">{visible.map(task => {
                const status = trackingTaskStatus(entity, task, dep)
                const editable = !trackingLocked(state, entity) || entity.tasks.some(own => own.name.toUpperCase() === task.name.toUpperCase())
                const taskKey = taskSelectionKey({ entity, task })
                const taskSelected = selectedKeys.has(taskKey)
                return <div key={task.name} className="tracking-task-slot" data-task-selected={taskSelected || undefined}>
                  <div className="tracking-task-meta">{visible.length > 1 && <span className="tracking-muted">{task.name}</span>}
                    {status && blocked.length > 0 && <Tooltip scale={0.9 * zoom}><TooltipTrigger asChild><button className="tracking-need" aria-label={`Dépendances requises : ${blocked.join(', ')}`}>NEED</button></TooltipTrigger><TooltipContent>{[...new Set(blocked)].map(label => <div key={label}>{label}</div>)}</TooltipContent></Tooltip>}
                  </div>
                  <TaskStatusBadge project={project} state={state} setState={setState} entity={entity} task={task} status={status} statuses={dep.statuses}
                  tooltipScale={0.9 * zoom}
                  actionTargets={taskSelected ? selectedTargets : undefined}
                  selectionControl={{ label: `Sélection de ${entity.name} · ${task.name}`, selected: taskSelected, onClick: event => {
                    const additive = event.ctrlKey || event.metaKey
                    if (additive || event.shiftKey) setTaskSelection(prev => selectProductionTask(prev, visibleTargets, taskKey, additive, event.shiftKey))
                    else setTaskSelection(emptyTaskSelection())
                  } }}
                  onContextTask={() => { if (!taskSelected) setTaskSelection({ keys: [taskKey], anchor: taskKey }) }}
                  onClick={editable ? () => openCell(entity, task) : undefined} />
                  <div className="tracking-task-artist">{taskAssignedTo(entity, task, username) && <UserRound size={12} className="tracking-assigned-user" aria-label="Cette tâche vous est assignée" />}</div>
                </div>
              })}</div></td>
            })}
          </tr>
          {expanded && subRows.map(row => {
            const editable = !trackingLocked(state, entity) || entity.tasks.some(own => own.name.toUpperCase() === row.task.name.toUpperCase())
            return <tr key={`${entity.id}|${row.task.name}|${row.subtask}`} className="tracking-subtask-row">
              <td className="tracking-identity"><div className="tracking-subtask-name"><span className="tracking-muted">{row.task.name}</span><span>{row.subtask}</span></div></td>
              <td className="tracking-relations" />
              {departments.map(dep => <td key={dep.id} className="tracking-status-cell">{dep.id === row.departmentId &&
                <div className="tracking-task-badges"><div className="tracking-task-slot">
                  <TaskStatusBadge project={project} state={state} setState={setState} entity={entity} task={row.task} subtask={row.subtask}
                    statuses={dep.statuses} tooltipScale={0.9 * zoom}
                    onClick={editable ? () => { setState(prev => ensureTrackingTask(prev, entity.id, row.task)); onOpenDetail(selectEntity(entity), row.task, row.subtask) } : undefined} />
                  <div className="tracking-task-artist">{entity.task_details?.[`${row.task.name.toUpperCase()}|${row.subtask.toUpperCase()}`]?.assignee?.trim().toUpperCase() === username.trim().toUpperCase() && username.trim() && <UserRound size={12} className="tracking-assigned-user" aria-label="Cette sous-tâche vous est assignée" />}</div>
                </div></div>}</td>)}
            </tr>
          })}
          </Fragment>
        })}</tbody>)}
      </table>
      {!entities.length && <div className="tracking-empty"><strong>{loading ? 'Chargement...' : 'Aucun résultat'}</strong><span>{filter.kind === 'mine' ? 'Aucun job assigné à votre artiste.' : 'Modifiez la recherche ou le filtre Show.'}</span>{!loading && filter.kind === 'all' && !query && !onlyEntityId && <button onClick={() => beginCreate(mode === 'asset' ? 'asset' : state.sequences.length ? 'shot' : 'seq')}>Create</button>}</div>}
    </div>
    <div className="tracking-footer"><span>Ctrl + molette pour zoomer · Ctrl / Shift + clic sur un badge pour sélectionner</span><span>{selectedTargets.length ? 'Clic droit pour les actions · Clic dans le vide ou Échap pour effacer' : 'Clic droit sur un statut ou un shot pour les actions'}</span></div>
  </div>
}

/** Retake B3: one row per subtask (known subtasks + reviewed ones), under the column of its task. */
function subtaskRows(state: ProductionState, entity: TrackingEntity, departments: ReturnType<typeof trackingDepartments>, mine: boolean, username: string) {
  const rows: Array<{ task: ProductionTask; subtask: string; departmentId: string }> = []
  for (const dep of departments) for (const task of trackingCellTasks(state, entity, dep, mine, username)) {
    const prefix = `${task.name.toUpperCase()}|`
    const fromDetails = Object.keys(entity.task_details ?? {}).filter(k => k.toUpperCase().startsWith(prefix)).map(k => k.slice(prefix.length))
    const seen = new Set<string>()
    for (const sub of [...task.known_subtasks, ...fromDetails]) {
      if (!sub || seen.has(sub.toUpperCase())) continue
      seen.add(sub.toUpperCase())
      rows.push({ task, subtask: sub, departmentId: dep.id })
    }
  }
  return rows
}

interface PreviewMenu {
  sources: Array<{ id: PreviewSource; label: string }>
  current: PreviewSource
  onPick: (source: PreviewSource) => void
  title: string
  hint: string
}

function Thumbnail({ project, entity, locked, onChange, previewMenu }: { project: string; entity: TrackingEntity; locked: boolean; onChange: (thumbnail: ProductionThumbnail) => void; previewMenu?: PreviewMenu }) {
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null)
  const [busy, setBusy] = useState(false)
  const [broken, setBroken] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const thumb = entity.thumbnail
  useEffect(() => setBroken(false), [thumb?.file, thumb?.rel_path])
  const upload = async (file?: File) => {
    if (!file || busy || locked) return
    if (!/\.(png|jpe?g|webp|gif|avif|bmp)$/i.test(file.name)) { toast.error('Choisissez une image PNG, JPEG, WebP, GIF, AVIF ou BMP'); return }
    setBusy(true)
    try {
      const rel_path = `_production/thumbnails/${entity.id}`
      const result = await api.depositRef(project, rel_path, file)
      onChange({ rel_path, file: `${result.version}${result.ext}` })
    } catch (e) { toast.error(e instanceof Error ? e.message : 'Import de miniature impossible') }
    finally { setBusy(false); if (input.current) input.current.value = '' }
  }
  const baseTitle = locked ? 'Shot ou séquence verrouillé' : busy ? 'Import en cours…' : 'Choisir ou glisser une miniature'
  return <div className="tracking-thumbnail" onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); void upload(e.dataTransfer.files[0]) }}
    onContextMenu={previewMenu ? e => { e.preventDefault(); e.stopPropagation(); setMenu({ x: e.clientX, y: e.clientY }) } : undefined}>
    <button disabled={busy || locked} aria-label={`Miniature de ${entity.name}`} title={previewMenu ? `${baseTitle}\n${previewMenu.hint}` : baseTitle} onClick={() => input.current?.click()}>
      {thumb && !broken ? <img src={api.refFileUrl(project, thumb.rel_path, thumb.file)} alt={entity.name} loading="lazy" onError={() => setBroken(true)} /> : <ImagePlus size={18} />}
    </button><input ref={input} type="file" accept=".png,.jpg,.jpeg,.webp,.gif,.avif,.bmp" hidden onChange={e => void upload(e.target.files?.[0])} />
    {previewMenu && menu && <Dropdown.Root open onOpenChange={open => { if (!open) setMenu(null) }} modal={false}>
      {createPortal(<Dropdown.Trigger tabIndex={-1} aria-hidden style={{ position: 'fixed', left: menu.x, top: menu.y, width: 1, height: 1, opacity: 0, pointerEvents: 'none' }} />, document.body)}
      <Dropdown.Portal><Dropdown.Content className="production-context-menu" align="start" collisionPadding={10}>
        <Dropdown.Label className="production-menu-artist">{previewMenu.title}</Dropdown.Label>
        {previewMenu.sources.map(option => <Dropdown.Item key={option.id} className="production-menu-item" onSelect={() => previewMenu.onPick(option.id)}>
          <span className="tracking-preview-check">{previewMenu.current === option.id && <Check size={12} />}</span>{option.label}
        </Dropdown.Item>)}
      </Dropdown.Content></Dropdown.Portal>
    </Dropdown.Root>}
  </div>
}

export function DependencySettings({ state, entity, onChange }: { state: ProductionState; entity: TrackingEntity; onChange: (deps: ProductionDependency[]) => void }) {
  const [target, setTarget] = useState('')
  const [task, setTask] = useState('')
  const targets = [...state.assets, ...state.shots].filter(e => e.id !== entity.id)
  const targetEntity = targets.find(e => e.id === target)
  return <fieldset disabled={trackingLocked(state, entity)} className="tracking-dependency-editor" aria-label="Relations de production">
    <strong>Dépendances de {entity.name}</strong>
    {(entity.dependencies ?? []).map((d, i) => <span key={`${d.entity_id}:${d.task}:${i}`}>{dependencyLabel(state, d)}<button aria-label={`Retirer ${dependencyLabel(state, d)}`} onClick={() => onChange((entity.dependencies ?? []).filter((_, n) => n !== i))}><X size={12} /></button></span>)}
    <select aria-label="Entité requise" value={target} onChange={e => { setTarget(e.target.value); setTask('') }}><option value="">Choisir un asset ou shot</option>{targets.map(e => <option key={e.id} value={e.id}>{dependencyLabel(state, { entity_id: e.id })}</option>)}</select>
    <select aria-label="Tâche requise" value={task} onChange={e => setTask(e.target.value)}><option value="">Toutes les tâches</option>{targetEntity && effectiveTasks(state, targetEntity).map(t => <option key={t.id}>{t.name}</option>)}</select>
    <button disabled={!target} onClick={() => { if (!(entity.dependencies ?? []).some(d => d.entity_id === target && (d.task ?? '') === task)) onChange([...(entity.dependencies ?? []), { entity_id: target, ...(task ? { task } : {}) }]); setTarget(''); setTask('') }}>Ajouter</button>
  </fieldset>
}
