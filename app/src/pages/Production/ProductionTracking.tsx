import { useEffect, useMemo, useRef, useState } from 'react'
import { ImagePlus, LockKeyhole, Minus, Plus, Search, Settings2, X } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '../../api/client'
import type { ProductionDepartment, ProductionDependency, ProductionState, ProductionTask, ProductionThumbnail } from '../../types'
import type { Selection } from './Production'
import { blockers, DEFAULT_DEPARTMENTS, departmentStatus, departmentTasks, dependencyLabel, dependencyReady, detailStatus, effectiveCasting, effectiveTasks, ensureTrackingTask, patchTrackingDetail, STATUS_LABELS, STATUS_TOKENS, taskStatus, trackingDepartments, trackingLocked } from './tracking'
import type { TrackingEntity } from './tracking'
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
  loading: boolean
}

export function ProductionTracking({ project, mode, state, setState, selection, setSelection, onOpenDetail, onEdit, loading }: Props) {
  const [query, setQuery] = useState('')
  const [group, setGroup] = useState('')
  const [configOpen, setConfigOpen] = useState(false)
  const [zoom, setZoom] = useState(() => {
    try { return Math.max(0.65, Math.min(1.4, Number(localStorage.getItem('flux.production.tableZoom')) || 1)) } catch { return 1 }
  })
  const [cell, setCell] = useState<{ entityId: string; departmentId: string; taskName: string; subtask: string } | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const departments = useMemo(() => trackingDepartments(state, mode), [state, mode])
  const activeDepartments = departments.filter(d => d.active)
  const changeZoom = (next: number) => {
    const value = Math.round(Math.max(0.65, Math.min(1.4, next)) * 100) / 100
    setZoom(value)
    try { localStorage.setItem('flux.production.tableZoom', String(value)) } catch { /* unavailable */ }
  }
  useEffect(() => {
    const node = scrollRef.current
    if (!node) return
    const wheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return
      e.preventDefault()
      setZoom(prev => {
        const value = Math.round(Math.max(0.65, Math.min(1.4, prev + (e.deltaY < 0 ? 0.05 : -0.05))) * 100) / 100
        try { localStorage.setItem('flux.production.tableZoom', String(value)) } catch { /* unavailable */ }
        return value
      })
    }
    node.addEventListener('wheel', wheel, { passive: false })
    return () => node.removeEventListener('wheel', wheel)
  }, [])
  const entities: TrackingEntity[] = useMemo(() => {
    const list = mode === 'shot' ? state.shots : state.assets
    const search = query.trim().toLowerCase()
    return list.filter(e => {
      const parent = 'seq_id' in e ? state.sequences.find(s => s.id === e.seq_id)?.name ?? '' : e.class
      const related = 'seq_id' in e ? effectiveCasting(state, e).map(l => state.assets.find(a => a.id === l.id)?.name ?? l.ref).join(' ') : ''
      return (!group || ('seq_id' in e ? e.seq_id === group : e.class === group)) &&
        `${parent} ${e.name} ${'label' in e ? e.label ?? '' : ''} ${related}`.toLowerCase().includes(search)
    }).sort((a, b) => {
      const parentOrder = (e: TrackingEntity) => 'seq_id' in e ? state.sequences.find(s => s.id === e.seq_id)?.order ?? 0 : 0
      return parentOrder(a) - parentOrder(b) || a.order - b.order || a.name.localeCompare(b.name, undefined, { numeric: true })
    })
  }, [state, mode, query, group])
  const selectedEntity = cell ? [...state.shots, ...state.assets].find(e => e.id === cell.entityId) : null
  const selectedDepartment = departments.find(d => d.id === cell?.departmentId)
  const selectedTasks = selectedEntity && selectedDepartment ? departmentTasks(state, selectedEntity, selectedDepartment)
    .filter(t => !trackingLocked(state, selectedEntity) || selectedEntity.tasks.some(own => own.name.toUpperCase() === t.name.toUpperCase())) : []
  const selectedTask = selectedTasks.find(t => t.name === cell?.taskName) ?? selectedTasks[0]
  const selectedStatus = selectedEntity && selectedTask && cell
    ? cell.subtask ? detailStatus(selectedEntity.task_details?.[`${selectedTask.name.toUpperCase()}|${cell.subtask.toUpperCase()}`]) : taskStatus(selectedEntity, selectedTask)
    : 'TODO'
  const selectEntity = (entity: TrackingEntity): Selection => ({ kind: 'seq_id' in entity ? 'shot' : 'asset', id: entity.id })
  const openCell = (entity: TrackingEntity, dep: ProductionDepartment, task: ProductionTask, subtask = '') => {
    const sel = selectEntity(entity)
    setCell({ entityId: entity.id, departmentId: dep.id, taskName: task.name, subtask })
    setState(prev => ensureTrackingTask(prev, entity.id, task))
    onOpenDetail(sel, task, subtask || undefined)
  }
  const selected = selection.kind === 'shot' || selection.kind === 'asset'
    ? [...state.shots, ...state.assets].find(e => e.id === selection.id) : null
  const patchEntity = (entityId: string, patch: { thumbnail?: ProductionThumbnail; dependencies?: ProductionDependency[] }) => setState(prev => ({
    ...prev, shots: prev.shots.map(e => e.id === entityId ? { ...e, ...patch } : e), assets: prev.assets.map(e => e.id === entityId ? { ...e, ...patch } : e),
  }))
  const creationSequence = mode === 'shot' ? state.sequences.find(s => s.id === group)
    ?? state.sequences.find(s => selection.kind === 'seq' ? s.id === selection.id : selection.kind === 'shot' ? s.id === state.shots.find(sh => sh.id === selection.id)?.seq_id : false)
    ?? [...state.sequences].sort((a, b) => a.order - b.order)[0] : undefined
  const beginCreate = () => {
    setCell(null)
    setSelection(creationSequence ? { kind: 'seq', id: creationSequence.id } : { kind: 'none' })
    onEdit()
  }

  return <div className="production-tracking">
    <div className="tracking-toolbar">
      <label className="tracking-search"><Search size={14} /><input aria-label="Rechercher dans la production" placeholder={mode === 'shot' ? 'Rechercher un shot, un asset…' : 'Rechercher un asset…'} value={query} onChange={e => setQuery(e.target.value)} /></label>
      <select aria-label={mode === 'shot' ? 'Filtrer par séquence' : 'Filtrer par catégorie'} value={group} onChange={e => setGroup(e.target.value)}>
        <option value="">{mode === 'shot' ? 'Toutes les séquences' : 'Toutes les catégories'}</option>
        {mode === 'shot' ? [...state.sequences].sort((a, b) => a.order - b.order).map(s => <option key={s.id} value={s.id}>{s.name}{s.label ? ` · ${s.label}` : ''}</option>) : [...new Set(state.assets.map(a => a.class))].sort().map(c => <option key={c}>{c}</option>)}
      </select>
      <span className="tracking-count">{entities.length} / {mode === 'shot' ? state.shots.length : state.assets.length}</span>
      <div className="tracking-spacer" />
      <div className="tracking-zoom" title="Zoom : Ctrl + molette">
        <button aria-label="Réduire le tableau" disabled={zoom <= 0.65} onClick={() => changeZoom(zoom - 0.1)}><Minus size={12} /></button>
        <button aria-label="Réinitialiser le zoom" onClick={() => changeZoom(1)}>{Math.round(zoom * 100)}%</button>
        <button aria-label="Agrandir le tableau" disabled={zoom >= 1.4} onClick={() => changeZoom(zoom + 0.1)}><Plus size={12} /></button>
      </div>
      <button aria-expanded={configOpen} onClick={() => setConfigOpen(!configOpen)}><Settings2 size={13} /> Colonnes</button>
      <button title={creationSequence ? `Créer un shot dans ${creationSequence.name}` : undefined} onClick={beginCreate}><Plus size={13} /> {mode === 'shot' ? creationSequence ? 'Shot' : 'Séquence' : 'Asset'}</button>
    </div>
    {configOpen && <DepartmentSettings key={mode} departments={departments} allDepartments={[...trackingDepartments(state, 'shot'), ...trackingDepartments(state, 'asset')]} mode={mode} onClose={() => setConfigOpen(false)} onSave={deps => {
      setState(prev => ({ ...prev, tracking: { departments: [...(prev.tracking?.departments ?? DEFAULT_DEPARTMENTS).filter(d => d.scope !== mode), ...deps] } }))
      setConfigOpen(false)
    }} />}
    <div ref={scrollRef} className="tracking-scroll" tabIndex={0} aria-label="Tableau de suivi de production" onKeyDown={e => {
      if (e.target !== e.currentTarget || (!e.ctrlKey && !e.metaKey)) return
      if (['+', '=', '-', '0'].includes(e.key)) { e.preventDefault(); changeZoom(e.key === '0' ? 1 : zoom + (e.key === '-' ? -0.1 : 0.1)) }
    }}>
      <table className="tracking-table" style={{ zoom }}>
        <thead><tr><th className="tracking-identity">{mode === 'shot' ? 'Shot' : 'Asset'}</th><th>{mode === 'shot' ? 'Assets liés' : 'Shots liés'}</th>{activeDepartments.map(d => <th key={d.id} title={d.task_tokens.join(', ')}>{d.name}</th>)}<th>Dépendances</th></tr></thead>
        <tbody>{entities.map(entity => {
          const isShot = 'seq_id' in entity
          const seq = isShot ? state.sequences.find(s => s.id === entity.seq_id) : null
          const isSelected = (selection.kind === 'asset' || selection.kind === 'shot') && selection.id === entity.id
          const links = isShot ? effectiveCasting(state, entity) : []
          const linkedShots = !isShot ? state.shots.filter(sh => effectiveCasting(state, sh).some(l => l.id === entity.id)) : []
          const cells = activeDepartments.map(dep => ({ dep, tasks: departmentTasks(state, entity, dep), status: departmentStatus(state, entity, dep), blocked: blockers(state, entity, dep, departments) }))
          const entityBlockers = [...new Set(cells.flatMap(c => c.blocked))]
          return <tr key={entity.id} data-selected={isSelected || undefined}>
            <td className="tracking-identity"><div className="tracking-name-cell">
              <Thumbnail key={`${project}:${entity.id}`} project={project} entity={entity} locked={trackingLocked(state, entity)} onChange={thumbnail => patchEntity(entity.id, { thumbnail })} />
              <div className="tracking-name">
                {seq ? <button className="tracking-parent" title={`Propriétés de ${seq.name}`} onClick={() => { setCell(null); setSelection({ kind: 'seq', id: seq.id }); onEdit() }}>{seq.name}</button> : <span className="tracking-parent">{isShot ? 'Séquence manquante' : entity.class}</span>}
                <button onClick={() => { setCell(null); setSelection(selectEntity(entity)) }}><strong>{entity.name}{isShot && (entity.locked || seq?.locked) && <LockKeyhole size={11} />}</strong></button>
                {isShot && entity.label && <span className="tracking-label" title={entity.label}>{entity.label}</span>}
              </div>
            </div></td>
            <td className="tracking-relations"><div>
              {links.map(link => { const asset = state.assets.find(a => a.id === link.id); return <button key={link.id} disabled={!asset} title={asset ? `${asset.class} · ${asset.name}` : `Asset manquant : ${link.ref}`} onClick={() => { setCell(null); setSelection({ kind: 'asset', id: link.id }) }}>{asset?.name ?? `${link.ref || link.id} (manquant)`}{(link.count ?? 1) > 1 ? ` ×${link.count}` : ''}</button> })}
              {linkedShots.map(sh => <button key={sh.id} onClick={() => { setCell(null); setSelection({ kind: 'shot', id: sh.id }) }} title={`${state.sequences.find(s => s.id === sh.seq_id)?.name}/${sh.name}`}>{state.sequences.find(s => s.id === sh.seq_id)?.name}/{sh.name}</button>)}
              {!links.length && !linkedShots.length && <span className="tracking-muted">{isShot ? 'Aucun asset lié' : 'Aucun shot lié'}</span>}
            </div></td>
            {cells.map(({ dep, tasks, status, blocked }) => {
              const allowed = dep.statuses.includes(status)
              const openTask = trackingLocked(state, entity) ? tasks.find(t => entity.tasks.some(own => own.name.toUpperCase() === t.name.toUpperCase())) : tasks[0]
              const canMaterialize = !trackingLocked(state, entity) || Boolean(openTask)
              return <td key={dep.id} className="tracking-status-cell">
                <button className="tracking-status" disabled={!canMaterialize} data-status={STATUS_TOKENS.includes(status) ? status : 'UNKNOWN'} title={!canMaterialize ? 'Création indisponible : shot ou séquence verrouillé' : tasks.length ? `${dep.name} · ${STATUS_LABELS[status] ?? status}${allowed ? '' : ' (hors tokens autorisés)'}${blocked.length ? ` · Bloqué par ${blocked.join(', ')}` : ''} · Ouvrir les retakes` : `${dep.name} : aucune tâche disponible. Cliquez pour créer la tâche.`} onClick={() => openCell(entity, dep, openTask ?? {
                  id: `t_${crypto.randomUUID()}`, name: dep.task_tokens[0] ?? dep.name.toUpperCase(), order: entity.tasks.length, type_tokens: dep.task_tokens.slice(0, 1), known_subtasks: [], origin: 'user',
                })}>{status}{!tasks.length && <Plus size={10} />}</button>
                {blocked.length > 0 && <span className="tracking-blocked" title={blocked.join(', ')}>Bloqué · {blocked.length}</span>}
                {tasks.length > 1 && <span className="tracking-muted">{tasks.length} tâches</span>}
              </td>
            })}
            <td className="tracking-dependencies">
              {(entity.dependencies ?? []).map((d, i) => <button key={`${d.entity_id}:${d.task}:${i}`} data-blocked={!dependencyReady(state, d)} onClick={() => {
                const target = [...state.assets, ...state.shots].find(e => e.id === d.entity_id)
                if (target) { setCell(null); setSelection(selectEntity(target)) }
              }}>{dependencyLabel(state, d)}</button>)}
              {entityBlockers.length > 0 && <span className="tracking-blocked" title={entityBlockers.join(', ')}>{entityBlockers.length} dépendance(s) en attente</span>}
              {!entity.dependencies?.length && !entityBlockers.length && <span className="tracking-muted">Aucune</span>}
            </td>
          </tr>
        })}</tbody>
      </table>
      {!entities.length && <div className="tracking-empty"><strong>{loading ? 'Chargement de la production…' : query || group ? 'Aucun résultat' : mode === 'shot' ? 'Aucun shot dans ce projet' : 'Aucun asset dans ce projet'}</strong><span>{query || group ? 'Modifiez la recherche ou le filtre.' : 'Créez une entité ou retrouvez ici celles déjà présentes sur disque.'}</span>{!loading && !query && !group && <button onClick={beginCreate}>Ouvrir la création</button>}</div>}
    </div>
    {selectedEntity && selectedDepartment && selectedTask && cell && <div className="tracking-cell-editor">
      <span>{selectedEntity.name} · {selectedDepartment.name}</span>
      <select aria-label="Tâche du département" value={selectedTask.name} onChange={e => setCell({ ...cell, taskName: e.target.value, subtask: '' })}>{selectedTasks.map(t => <option key={t.id} value={t.name}>{t.name}</option>)}</select>
      <select aria-label="Sous-tâche" value={cell.subtask} onChange={e => setCell({ ...cell, subtask: e.target.value })}><option value="">Département entier</option>{selectedTask.known_subtasks.map(s => <option key={s}>{s}</option>)}</select>
      <select aria-label="Statut de production" value={selectedStatus} onChange={e => setState(prev => patchTrackingDetail(prev, selectedEntity.id, selectedTask, cell.subtask, e.target.value))}>
        {!selectedDepartment.statuses.includes(selectedStatus) && <option value={selectedStatus} disabled>{selectedStatus} (hors tokens autorisés)</option>}
        {selectedDepartment.statuses.map(s => <option key={s} value={s}>{s} · {STATUS_LABELS[s] ?? s}</option>)}
      </select>
      <button onClick={() => openCell(selectedEntity, selectedDepartment, selectedTask, cell.subtask)}>Ouvrir les retakes</button>
      <button aria-label="Fermer le statut" onClick={() => setCell(null)}><X size={12} /></button>
    </div>}
    <div className="tracking-footer"><span>Statuts : TODO · WIP · WFA · RTK · APPROVED</span><span>Ctrl + molette pour zoomer · Cliquez sur un statut pour les retakes</span>{selected && <button onClick={() => setConfigOpen(true)}>Relations de {selected.name}</button>}</div>
    {configOpen && selected && <DependencySettings key={selected.id} state={state} entity={selected} onChange={dependencies => patchEntity(selected.id, { dependencies })} />}
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

function DepartmentSettings({ departments, allDepartments, mode, onSave, onClose }: { departments: ProductionDepartment[]; allDepartments: ProductionDepartment[]; mode: 'shot' | 'asset'; onSave: (deps: ProductionDepartment[]) => void; onClose: () => void }) {
  const [draft, setDraft] = useState(() => departments.map(d => ({ ...d, task_tokens: [...d.task_tokens], statuses: [...d.statuses], depends_on: [...d.depends_on] })))
  const [error, setError] = useState('')
  const patch = (id: string, value: Partial<ProductionDepartment>) => setDraft(prev => prev.map(d => d.id === id ? { ...d, ...value } : d))
  const save = () => {
    if (draft.some(d => !d.name.trim() || !d.task_tokens.length || !d.statuses.length)) { setError('Chaque département doit avoir un nom, un token de tâche et un statut autorisé.'); return }
    const visited = new Set<string>(), visiting = new Set<string>()
    const cycle = (id: string): boolean => {
      if (visiting.has(id)) return true
      if (visited.has(id)) return false
      visiting.add(id)
      if ((draft.find(d => d.id === id)?.depends_on ?? []).some(cycle)) return true
      visiting.delete(id); visited.add(id); return false
    }
    if (draft.some(d => cycle(d.id))) { setError('Les dépendances entre départements forment un cycle.'); return }
    onSave(draft.map(d => ({ ...d, name: d.name.trim(), statuses: [...new Set(d.statuses)], task_tokens: [...new Set(d.task_tokens)] })))
  }
  return <section className="tracking-settings" aria-label="Configuration des départements">
    <div className="tracking-settings-heading"><strong>Départements du projet · {mode === 'shot' ? 'Shots' : 'Assets'}</strong><button aria-label="Fermer les colonnes" onClick={onClose}><X size={13} /></button></div>
    <p>Les tokens correspondent aux tâches existantes. Masquer une colonne conserve ses données. Les statuts sont partagés par le projet.</p>
    <div className="tracking-config-list">{draft.map(d => <div key={d.id} className="tracking-config-row">
      <label><input type="checkbox" checked={d.active} onChange={e => patch(d.id, { active: e.target.checked })} /> Actif{d.fixed ? ' · fixe' : ''}</label>
      <input aria-label={`Nom ${d.name}`} value={d.name} onChange={e => patch(d.id, { name: e.target.value })} />
      <input aria-label={`Tokens ${d.name}`} defaultValue={d.task_tokens.join(', ')} placeholder="ANIM, ANIMATION" onBlur={e => patch(d.id, { task_tokens: e.target.value.split(',').map(s => s.trim().toUpperCase()).filter(Boolean) })} />
      <input aria-label={`Statuts ${d.name}`} defaultValue={d.statuses.join(', ')} onBlur={e => patch(d.id, { statuses: e.target.value.split(',').map(s => s.trim().toUpperCase()).filter(Boolean) })} />
      <details><summary>Dépend de ({d.depends_on.length})</summary>{draft.filter(x => x.id !== d.id).map(x => <label key={x.id}><input type="checkbox" checked={d.depends_on.includes(x.id)} onChange={e => patch(d.id, { depends_on: e.target.checked ? [...d.depends_on, x.id] : d.depends_on.filter(id => id !== x.id) })} /> {x.name}</label>)}</details>
      {!d.fixed && <button aria-label={`Retirer ${d.name}`} onClick={() => setDraft(prev => prev.filter(x => x.id !== d.id).map(x => ({ ...x, depends_on: x.depends_on.filter(id => id !== d.id) })))}><X size={12} /></button>}
    </div>)}</div>
    {error && <p role="alert">{error}</p>}
    <div className="tracking-settings-actions"><button onClick={() => setDraft(prev => [...prev, { id: `${mode}:${crypto.randomUUID()}`, name: 'Département', scope: mode, task_tokens: [], statuses: [...STATUS_TOKENS], depends_on: [], active: true }])}><Plus size={12} /> Département</button><span className="tracking-spacer" /><button onClick={onClose}>Annuler</button><button onClick={save}>Enregistrer pour le projet</button></div>
    <span className="tracking-muted">{allDepartments.length} départements reconnus dans le projet.</span>
  </section>
}

function DependencySettings({ state, entity, onChange }: { state: ProductionState; entity: TrackingEntity; onChange: (deps: ProductionDependency[]) => void }) {
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
