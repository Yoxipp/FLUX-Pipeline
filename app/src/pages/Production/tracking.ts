import type { CastingLink, ProductionAsset, ProductionDepartment, ProductionDependency, ProductionShot, ProductionState, ProductionTask, ProductionTaskDetail } from '../../types'

export type TrackingEntity = ProductionAsset | ProductionShot
export const STATUS_TOKENS = ['TODO', 'WIP', 'WFA', 'RTK', 'APPROVED']
export const STATUS_LABELS: Record<string, string> = {
  TODO: 'À faire', WIP: 'En cours', WFA: 'En attente de validation', RTK: 'Retake demandé', APPROVED: 'Validé',
}
const department = (scope: 'asset' | 'shot', id: string, name: string, tokens: string[], fixed = false): ProductionDepartment =>
  ({ id, name, task_tokens: tokens, scope, active: true, fixed, statuses: [...STATUS_TOKENS], depends_on: [] })
export const DEFAULT_DEPARTMENTS: ProductionDepartment[] = [
  department('shot', 'layout', 'Layout', ['LAYOUT', 'CAM'], true),
  department('shot', 'anim', 'Animation', ['ANIM', 'ANIMATION'], true),
  department('shot', 'fx', 'FX', ['FX']),
  department('shot', 'lighting', 'Lighting', ['LIGHT', 'LIGHTING'], true),
  department('shot', 'render', 'Rendering', ['RENDER', 'RENDERING']),
  department('shot', 'comp', 'Compositing', ['COMP']),
  department('asset', 'model', 'Modeling', ['GEO', 'MODEL', 'MODELING'], true),
  department('asset', 'rig', 'Rigging', ['RIG', 'RIGGING'], true),
  department('asset', 'look', 'Look', ['SHADING', 'LOOK', 'LOOKDEV'], true),
  department('asset', 'groom', 'Groom', ['GROOM']),
]
export const taskMatchesDepartment = (task: ProductionTask, dep: ProductionDepartment) => {
  const tokens = dep.task_tokens.map(x => x.toUpperCase())
  return tokens.includes(task.name.toUpperCase()) || task.type_tokens.some(x => tokens.includes(x.toUpperCase()))
}

/** Include inherited sequence tasks as templates, never their review details. */
export function effectiveTasks(state: ProductionState, entity: TrackingEntity): ProductionTask[] {
  if (!('seq_id' in entity) || !entity.inherit_tasks) return entity.tasks
  const seq = state.sequences.find(s => s.id === entity.seq_id)
  const names = new Set(entity.tasks.map(t => t.name.toUpperCase()))
  return [...entity.tasks, ...(seq?.tasks ?? []).filter(t => !names.has(t.name.toUpperCase()))]
}

export function trackingDepartments(state: ProductionState, scope: 'asset' | 'shot'): ProductionDepartment[] {
  const configured = state.tracking?.departments ?? DEFAULT_DEPARTMENTS
  const result = configured.filter(d => d.scope === scope)
  // Once configured, this list is authoritative, including deliberate deletion.
  if (state.tracking) return result
  // Existing departments remain reachable even on projects with custom task names.
  const entities = scope === 'shot' ? state.shots : state.assets
  for (const entity of entities) for (const task of effectiveTasks(state, entity)) {
    if (!result.some(d => taskMatchesDepartment(task, d))) {
      const id = `${scope}:${task.name.toUpperCase()}`
      if (!result.some(d => d.id === id)) result.push(department(scope, id, task.name, [task.name]))
    }
  }
  return result
}

/** Fixed departments display TODO without materializing a task or disk folder. */
export function trackingTaskStatus(entity: TrackingEntity, task: ProductionTask, dep: ProductionDepartment): string {
  if (entity.task_details?.[task.name.toUpperCase()]?.status === '') return ''
  const keys = [task.name.toUpperCase(), ...task.known_subtasks.map(s => `${task.name.toUpperCase()}|${s.toUpperCase()}`)]
  const reviewed = keys.some(k => Boolean(entity.task_details?.[k]?.status) || (entity.task_details?.[k]?.completion ?? 0) > 0)
  return dep.fixed || reviewed ? taskStatus(entity, task) : ''
}

/** Assignee field may hold several artists separated by commas. */
export function assigneeList(value?: string): string[] {
  return [...new Set((value ?? '').split(',').map(v => v.trim()).filter(Boolean))]
}

export function assigneeIncludes(value: string | undefined, username: string): boolean {
  const who = username.trim().toUpperCase()
  return !!who && assigneeList(value).some(v => v.toUpperCase() === who)
}

export function taskAssignedTo(entity: TrackingEntity, task: ProductionTask, username: string): boolean {
  if (!username.trim()) return false
  const name = username.trim().toUpperCase(), prefix = task.name.toUpperCase()
  return Object.entries(entity.task_details ?? {}).some(([key, detail]) =>
    (key.toUpperCase() === prefix || key.toUpperCase().startsWith(`${prefix}|`)) && assigneeIncludes(detail.assignee, name))
}

export function moveDepartment(departments: ProductionDepartment[], from: string, to: string): ProductionDepartment[] {
  const start = departments.findIndex(d => d.id === from), end = departments.findIndex(d => d.id === to)
  if (start < 0 || end < 0 || start === end) return departments
  const next = [...departments]
  const [item] = next.splice(start, 1)
  next.splice(end, 0, item)
  return next
}

export function effectiveCasting(state: ProductionState, shot: ProductionShot): CastingLink[] {
  const own = shot.assets ?? []
  const ids = new Set(own.map(l => l.id))
  const seq = state.sequences.find(s => s.id === shot.seq_id)
  const inherited = shot.inherit_assets ? (seq?.assets ?? []) : []
  // Pinned version (ADR 0048): the shot's pin wins, a shot link without pin keeps the sequence's.
  const withPin = own.map(l => {
    if (l.version) return l
    const pin = inherited.find(s => s.id === l.id)?.version
    return pin ? { ...l, version: pin } : l
  })
  return [...withPin, ...inherited.filter(l => !ids.has(l.id))]
}

export function detailStatus(detail?: ProductionTaskDetail): string {
  if (detail?.status === '') return ''
  if (detail?.status) return detail.status.toUpperCase()
  // Legacy percentages are work in progress, never evidence of review approval.
  return (detail?.completion ?? 0) > 0 ? 'WIP' : 'TODO'
}

export function departmentTasks(state: ProductionState, entity: TrackingEntity, dep: ProductionDepartment) {
  return effectiveTasks(state, entity).filter(t => taskMatchesDepartment(t, dep)).sort((a, b) => a.order - b.order)
}

export function taskStatus(entity: TrackingEntity, task: ProductionTask): string {
  const details = entity.task_details ?? {}
  if (details[task.name.toUpperCase()]?.status === '') return ''
  if (details[task.name.toUpperCase()]?.status) return detailStatus(details[task.name.toUpperCase()])
  const subs = task.known_subtasks.map(s => details[`${task.name.toUpperCase()}|${s.toUpperCase()}`]).filter(Boolean)
  if (subs.length) {
    const statuses = subs.map(detailStatus)
    const unknown = statuses.find(s => !STATUS_TOKENS.includes(s))
    if (unknown) return unknown
    if (statuses.includes('RTK')) return 'RTK'
    if (subs.length === task.known_subtasks.length && statuses.every(s => s === 'APPROVED')) return 'APPROVED'
    if (statuses.includes('WFA')) return 'WFA'
    if (statuses.some(s => s !== 'TODO')) return 'WIP'
  }
  return detailStatus(details[task.name.toUpperCase()])
}

export function departmentStatus(state: ProductionState, entity: TrackingEntity, dep: ProductionDepartment): string {
  const tasks = departmentTasks(state, entity, dep)
  if (!tasks.length) return 'N/A'
  const statuses = tasks.map(t => taskStatus(entity, t))
  const unknown = statuses.find(s => !STATUS_TOKENS.includes(s))
  if (unknown) return unknown
  if (statuses.includes('RTK')) return 'RTK'
  if (statuses.every(s => s === 'APPROVED')) return 'APPROVED'
  if (statuses.includes('WFA')) return 'WFA'
  if (statuses.some(s => s === 'WIP' || s === 'APPROVED')) return 'WIP'
  return 'TODO'
}

export function dependencyLabel(state: ProductionState, dep: ProductionDependency): string {
  const entity = [...state.assets, ...state.shots].find(e => e.id === dep.entity_id)
  if (!entity) return `Lien manquant (${dep.entity_id})`
  const seq = 'seq_id' in entity ? state.sequences.find(s => s.id === entity.seq_id) : null
  return `${seq ? `${seq.name}/` : ''}${entity.name}${dep.task ? ` · ${dep.task}` : ''}`
}

export function dependencyReady(state: ProductionState, dep: ProductionDependency): boolean {
  const entity = [...state.assets, ...state.shots].find(e => e.id === dep.entity_id)
  if (!entity) return false
  const tasks = effectiveTasks(state, entity).filter(t => !dep.task || t.name.toUpperCase() === dep.task.toUpperCase())
  return tasks.length > 0 && tasks.every(t => taskStatus(entity, t) === 'APPROVED')
}

export function blockers(state: ProductionState, entity: TrackingEntity, dep: ProductionDepartment, departments?: ProductionDepartment[]): string[] {
  const result = (entity.dependencies ?? []).filter(d => !dependencyReady(state, d)).map(d => dependencyLabel(state, d))
  const scope = 'seq_id' in entity ? 'shot' : 'asset'
  const deps = dep.depends_on.length ? departments ?? trackingDepartments(state, scope) : []
  for (const id of dep.depends_on) {
    const prerequisite = deps.find(d => d.id === id)
    if (!prerequisite || departmentStatus(state, entity, prerequisite) !== 'APPROVED') result.push(prerequisite?.name ?? `Département manquant (${id})`)
  }
  return result
}

/** Materialize editable templates with their own id. Locked shots accept review metadata only. */
export function ensureTrackingTask(state: ProductionState, entityId: string, template: ProductionTask): ProductionState {
  const materialize = <T extends TrackingEntity>(s: T): T => {
    if (s.id !== entityId || trackingLocked(state, s) || s.tasks.some(t => t.name.toUpperCase() === template.name.toUpperCase())) return s
    return { ...s, tasks: [...s.tasks, { ...template, id: `t_${crypto.randomUUID()}`, type_tokens: [...template.type_tokens], known_subtasks: [...template.known_subtasks] }] }
  }
  return { ...state, shots: state.shots.map(materialize), assets: state.assets.map(materialize) }
}

export function patchTrackingDetail(state: ProductionState, entityId: string, task: ProductionTask, subtask: string, status: string): ProductionState {
  const next = ensureTrackingTask(state, entityId, task)
  const key = `${task.name.toUpperCase()}${subtask ? `|${subtask.toUpperCase()}` : ''}`
  const patch = <T extends TrackingEntity>(e: T): T => {
    if (e.id !== entityId) return e
    const details = { ...e.task_details, [key]: { ...e.task_details?.[key], status } }
    // Reviewing a subtask supersedes a previous explicit department override.
    if (subtask && details[task.name.toUpperCase()]?.status != null) {
      const { status: _oldStatus, ...rest } = details[task.name.toUpperCase()]
      details[task.name.toUpperCase()] = rest
    }
    return { ...e, task_details: details }
  }
  return { ...next, assets: next.assets.map(patch), shots: next.shots.map(patch) }
}

export function trackingLocked(state: ProductionState, entity: TrackingEntity): boolean {
  return 'seq_id' in entity && Boolean(entity.locked || state.sequences.find(s => s.id === entity.seq_id)?.locked)
}
