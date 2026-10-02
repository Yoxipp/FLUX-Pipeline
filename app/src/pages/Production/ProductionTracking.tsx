import { useEffect, useMemo, useRef, useState } from 'react'
import { ImagePlus, Plus, Search, Settings2, X } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '../../api/client'
import { useSettings } from '../../hooks/useSettings'
import type { ProductionDependency, ProductionState, ProductionTask, ProductionThumbnail } from '../../types'
import type { Selection } from './Production'
import { blockers, departmentTasks, dependencyLabel, effectiveCasting, effectiveTasks, ensureTrackingTask, taskAssignedTo, trackingTaskStatus, trackingDepartments, trackingLocked } from './tracking'
import type { TrackingEntity } from './tracking'
import { TaskStatusBadge } from './TaskStatusBadge'
import { EntityContextMenu } from './EntityContextMenu'
import { ProductionShowMenu, ProductionRelatedMenu, type ShowFilter } from './ProductionTableMenus'
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
  onNew: () => void
  onSettings: () => void
  onOpenEntity: (selection: Selection) => void
  onlyEntityId?: string
  loading: boolean
}

export function ProductionTracking({ project, mode, state, setState, selection, setSelection, onOpenDetail, onEdit, onNew, onSettings, onOpenEntity, onlyEntityId, loading }: Props) {
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<ShowFilter>({ kind: 'all' })
  // New 100% baseline is 90% of the original interface. Old saved zoom is retired.
  const [zoom, setZoom] = useState(1)
  const scrollRef = useRef<HTMLDivElement>(null)
  const { settings } = useSettings()
  const username = settings?.username ?? ''
  const departments = useMemo(() => trackingDepartments(state, mode), [state, mode])
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
  const selectEntity = (entity: TrackingEntity): Selection => ({ kind: 'seq_id' in entity ? 'shot' : 'asset', id: entity.id })
  const openCell = (entity: TrackingEntity, task: ProductionTask) => {
    setState(prev => ensureTrackingTask(prev, entity.id, task))
    onOpenDetail(selectEntity(entity), task)
  }
  const patchThumbnail = (entityId: string, thumbnail: ProductionThumbnail) => setState(prev => ({
    ...prev, shots: prev.shots.map(e => e.id === entityId ? { ...e, thumbnail } : e), assets: prev.assets.map(e => e.id === entityId ? { ...e, thumbnail } : e),
  }))
  const beginCreate = () => {
    const seq = filter.kind === 'seq' ? state.sequences.find(s => s.id === filter.id) : selection.kind === 'seq' ? state.sequences.find(s => s.id === selection.id) : state.sequences[0]
    setSelection(mode === 'shot' && seq ? { kind: 'seq', id: seq.id } : { kind: 'none' })
    onNew()
  }
  return <div className="production-tracking">
    <div className="tracking-toolbar">
      <label className="tracking-search"><Search size={14} /><input aria-label="Rechercher dans la production" placeholder={mode === 'shot' ? 'Rechercher un shot, un asset...' : 'Rechercher un asset...'} value={query} onChange={e => setQuery(e.target.value)} /></label>
      <span className="tracking-count">{entities.length} / {mode === 'shot' ? state.shots.length : state.assets.length}</span>
      <div className="tracking-spacer" />
      <ProductionShowMenu filter={filter} onChange={setFilter} sequences={state.sequences} />
      <button onClick={onSettings}><Settings2 size={13} /> Settings</button>
      <button onClick={beginCreate}><Plus size={13} /> New</button>
    </div>
    <div ref={scrollRef} className="tracking-scroll" tabIndex={0} aria-label="Tableau de suivi de production" onKeyDown={e => {
      if (e.target !== e.currentTarget || (!e.ctrlKey && !e.metaKey)) return
      if (['+', '=', '-', '0'].includes(e.key)) { e.preventDefault(); changeZoom(e.key === '0' ? 1 : zoom + (e.key === '-' ? -0.1 : 0.1)) }
    }}>
      <table className="tracking-table" style={{ zoom }}>
        <thead><tr><th className="tracking-identity">{mode === 'shot' ? 'Shot' : 'Asset'}</th><th>Timing</th><th>{mode === 'shot' ? 'Assets liés' : 'Shots liés'}</th>{departments.map(d => <th key={d.id} title={d.task_tokens.join(', ')}>{d.name}</th>)}</tr></thead>
        <tbody>{entities.map(entity => {
          const isShot = 'seq_id' in entity
          const seq = isShot ? state.sequences.find(s => s.id === entity.seq_id) : null
          const isSelected = (selection.kind === 'asset' || selection.kind === 'shot') && selection.id === entity.id
          const links = isShot ? effectiveCasting(state, entity) : []
          const linkedShots = !isShot ? state.shots.filter(sh => effectiveCasting(state, sh).some(l => l.id === entity.id)) : []
          const relatedItems = isShot ? links.map(link => { const asset = state.assets.find(a => a.id === link.id); return { id: link.id, label: asset?.name ?? link.ref, kind: 'asset' as const, count: link.count, missing: !asset } }) : linkedShots.map(sh => ({ id: sh.id, label: `${state.sequences.find(s => s.id === sh.seq_id)?.name}/${sh.name}`, kind: 'shot' as const }))
          return <tr key={entity.id} data-selected={isSelected || undefined}>
            <td className="tracking-identity"><div className="tracking-name-cell">
              <Thumbnail key={`${project}:${entity.id}`} project={project} entity={entity} locked={trackingLocked(state, entity)} onChange={thumbnail => patchThumbnail(entity.id, thumbnail)} />
              <div className="tracking-name">
                <span className="tracking-parent">{seq?.name ?? (isShot ? '?' : entity.class)}</span>
                <EntityContextMenu project={project} state={state} entity={entity} setState={setState} setSelection={setSelection} onEdit={onEdit} />
                {isShot && entity.label && <span className="tracking-label" title={entity.label}>{entity.label}</span>}
              </div>
            </div></td>
            <td className="tracking-timing">{isShot && entity.frame_start != null && entity.frame_end != null ? <><span>{entity.frame_start}–{entity.frame_end}</span><small>{entity.frame_end - entity.frame_start + 1} f</small></> : <span className="tracking-muted">—</span>}</td>
            <td className="tracking-relations"><ProductionRelatedMenu items={relatedItems} onOpen={onOpenEntity} /></td>
            {departments.map(dep => {
              const tasks = departmentTasks(state, entity, dep)
              const candidates = tasks.length ? tasks : [{ id: `t_${entity.id}_${dep.id}`, name: dep.task_tokens[0] ?? dep.name.toUpperCase(), order: entity.tasks.length, type_tokens: dep.task_tokens.slice(0, 1), known_subtasks: [], origin: 'user' as const }]
              const visible = filter.kind === 'mine' ? candidates.filter(t => taskAssignedTo(entity, t, username)) : candidates
              const blocked = blockers(state, entity, dep, departments)
              return <td key={dep.id} className="tracking-status-cell"><div className="tracking-task-badges">{visible.map(task => {
                const status = trackingTaskStatus(entity, task, dep)
                const editable = !trackingLocked(state, entity) || entity.tasks.some(own => own.name.toUpperCase() === task.name.toUpperCase())
                return <div key={task.name}>{visible.length > 1 && <span className="tracking-muted">{task.name}</span>}<TaskStatusBadge project={project} state={state} setState={setState} entity={entity} task={task} status={status} statuses={dep.statuses} disabled={!editable}
                  title={`${dep.name} : ${status || 'Aucun statut'} - Clic droit pour les actions`} onClick={() => openCell(entity, task)} />
                  {status && blocked.map(label => <span key={label} className="tracking-blocked">{label}</span>)}
                </div>
              })}</div></td>
            })}
          </tr>
        })}</tbody>
      </table>
      {!entities.length && <div className="tracking-empty"><strong>{loading ? 'Chargement...' : 'Aucun résultat'}</strong><span>{filter.kind === 'mine' ? 'Aucun job assigné à votre artiste.' : 'Modifiez la recherche ou le filtre Show.'}</span>{!loading && filter.kind === 'all' && !query && !onlyEntityId && <button onClick={beginCreate}>New</button>}</div>}
    </div>
    <div className="tracking-footer"><span>Ctrl + molette pour zoomer</span><span>Clic droit sur un statut ou un shot pour les actions</span></div>
  </div>
}

function Thumbnail({ project, entity, locked, onChange }: { project: string; entity: TrackingEntity; locked: boolean; onChange: (thumbnail: ProductionThumbnail) => void }) {
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
  return <div className="tracking-thumbnail" onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); void upload(e.dataTransfer.files[0]) }}>
    <button disabled={busy || locked} aria-label={`Miniature de ${entity.name}`} title={locked ? 'Shot ou séquence verrouillé' : busy ? 'Import en cours…' : 'Choisir ou glisser une miniature'} onClick={() => input.current?.click()}>
      {thumb && !broken ? <img src={api.refFileUrl(project, thumb.rel_path, thumb.file)} alt={entity.name} loading="lazy" onError={() => setBroken(true)} /> : <ImagePlus size={18} />}
    </button><input ref={input} type="file" accept=".png,.jpg,.jpeg,.webp,.gif,.avif,.bmp" hidden onChange={e => void upload(e.target.files?.[0])} />
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
