import type { ProductionDepartment, ProductionState, ProductionTask } from '../../types'
import { patchTaskPriority, type Priority } from './taskPriority'
import { clearTaskBadge, patchTaskArtist, setTaskStatus, type TaskEntity } from './taskActions'
import { departmentTasks, taskAssignedTo, type TrackingEntity } from './tracking'

export interface TaskActionTarget {
  entity: TaskEntity
  task: ProductionTask
  subtask?: string
  departmentId?: string
  columnOrder?: number
  statuses?: string[]
  status?: string
}

export interface TaskSelection { keys: string[]; anchor: string | null }
export const emptyTaskSelection = (): TaskSelection => ({ keys: [], anchor: null })
export const taskSelectionKey = (target: TaskActionTarget) => JSON.stringify([
  target.entity.id, target.task.name.toUpperCase(), (target.subtask ?? '').toUpperCase(),
])

/** Same candidates for rendering and selection, including optional empty cells. */
export function trackingCellTasks(state: ProductionState, entity: TrackingEntity, department: ProductionDepartment, mine: boolean, username: string): ProductionTask[] {
  const tasks = departmentTasks(state, entity, department)
  const candidates = tasks.length ? tasks : [{
    id: `t_${entity.id}_${department.id}`, name: department.task_tokens[0] ?? department.name.toUpperCase(),
    order: entity.tasks.length, type_tokens: department.task_tokens.slice(0, 1), known_subtasks: [], origin: 'user' as const,
  }]
  return mine ? candidates.filter(task => taskAssignedTo(entity, task, username)) : candidates
}

export function pruneTaskSelection(selection: TaskSelection, visibleKeys: string[]): TaskSelection {
  const visible = new Set(visibleKeys)
  const keys = selection.keys.filter(key => visible.has(key))
  const anchor = selection.anchor && visible.has(selection.anchor) ? selection.anchor : null
  return keys.length === selection.keys.length && anchor === selection.anchor ? selection : { keys, anchor }
}

/** Shift selects a rectangle of visible rows/departments; Ctrl/Meta toggles one task. */
export function selectProductionTask(selection: TaskSelection, targets: TaskActionTarget[], key: string, additive: boolean, range: boolean): TaskSelection {
  const current = pruneTaskSelection(selection, targets.map(taskSelectionKey))
  const target = targets.find(item => taskSelectionKey(item) === key)
  if (!target) return current
  const anchor = targets.find(item => taskSelectionKey(item) === current.anchor)
  if (range && anchor) {
    const rows = [...new Set(targets.map(item => item.entity.id))]
    const columns = [...new Set(targets.map(item => item.departmentId))]
    const rowBounds = [rows.indexOf(anchor.entity.id), rows.indexOf(target.entity.id)].sort((a, b) => a - b)
    const columnBounds = [anchor.columnOrder ?? columns.indexOf(anchor.departmentId), target.columnOrder ?? columns.indexOf(target.departmentId)].sort((a, b) => a - b)
    const keys = targets.filter(item => {
      const row = rows.indexOf(item.entity.id), column = item.columnOrder ?? columns.indexOf(item.departmentId)
      return row >= rowBounds[0] && row <= rowBounds[1] && column >= columnBounds[0] && column <= columnBounds[1]
    }).map(taskSelectionKey)
    return { keys: [...new Set([...(additive ? current.keys : []), ...keys])], anchor: current.anchor }
  }
  return {
    keys: additive ? current.keys.includes(key) ? current.keys.filter(item => item !== key) : [...current.keys, key] : [key],
    anchor: key,
  }
}

export type TaskBatchAction = { kind: 'artist'; value: string } | { kind: 'status'; value: string } | { kind: 'clear' }
  | { kind: 'priority'; value: Priority }

/** One state patch/save for the whole selection, without overwriting other review fields. */
export function applyTaskSelection(state: ProductionState, targets: TaskActionTarget[], action: TaskBatchAction): ProductionState {
  const seen = new Set<string>()
  return targets.reduce((next, target) => {
    const key = taskSelectionKey(target)
    if (seen.has(key)) return next
    seen.add(key)
    const entity = [...next.shots, ...next.assets, ...next.sequences].find(item => item.id === target.entity.id)
    if (!entity) return next
    if (action.kind === 'artist') return patchTaskArtist(next, entity.id, target.task, target.subtask ?? '', action.value)
    if (action.kind === 'clear') return clearTaskBadge(next, entity.id, target.task, target.subtask ?? '')
    if (action.kind === 'priority') return patchTaskPriority(next, entity.id, target.task, target.subtask ?? '', action.value)
    if (target.statuses && !target.statuses.includes(action.value)) return next
    return setTaskStatus(next, entity, target.task, target.subtask ?? '', action.value)
  }, state)
}
