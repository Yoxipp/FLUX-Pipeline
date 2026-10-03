import type { ProductionDepartment, ProductionSequence, ProductionState } from '../../types'
import { departmentTasks, trackingTaskStatus, type TrackingEntity } from './tracking'

export type DepartmentSort = { id: string; first: string } | null
export function departmentRank(state: ProductionState, entity: TrackingEntity, department: ProductionDepartment, first: string): number {
  const tasks = departmentTasks(state, entity, department)
  const statuses = (tasks.length ? tasks : [{ id: '', name: department.task_tokens[0] ?? department.name.toUpperCase(), type_tokens: [], known_subtasks: [], order: 0 }])
    .map(task => trackingTaskStatus(entity, task, department))
  if (statuses.includes(first)) return 0
  const ranks = statuses.map(status => status ? department.statuses.indexOf(status) : -1)
    .map(rank => rank < 0 ? department.statuses.length + 1 : rank + 1)
  return Math.min(...ranks)
}

/** Sorting is a view preference: sequence blocks remain intact and disk/order metadata stays untouched. */
export function productionRowGroups(state: ProductionState, entities: TrackingEntity[], mode: 'shot' | 'asset', departments: ProductionDepartment[], sort: DepartmentSort, emptySequences: ProductionSequence[] = []) {
  const dep = departments.find(d => d.id === sort?.id)
  const rank = (entity: TrackingEntity) => dep && sort ? departmentRank(state, entity, dep, sort.first) : 0
  const compare = (a: TrackingEntity, b: TrackingEntity) => rank(a) - rank(b) || a.order - b.order || a.name.localeCompare(b.name, undefined, { numeric: true })
  if (mode === 'asset') return [{ id: 'assets', sequence: null, entities: [...entities].sort(compare) }]
  const groups = new Map<string, { id: string; sequence: ProductionSequence | null; entities: TrackingEntity[] }>()
  for (const sequence of emptySequences) groups.set(sequence.id, { id: sequence.id, sequence, entities: [] })
  for (const entity of entities) {
    if (!('seq_id' in entity)) continue
    if (!groups.has(entity.seq_id)) groups.set(entity.seq_id, { id: entity.seq_id, sequence: state.sequences.find(s => s.id === entity.seq_id) ?? null, entities: [] })
    groups.get(entity.seq_id)!.entities.push(entity)
  }
  const groupRank = (rows: TrackingEntity[]) => rows.length ? Math.min(...rows.map(rank)) : Number.MAX_SAFE_INTEGER
  return [...groups.values()].map(group => ({ ...group, entities: [...group.entities].sort(compare) }))
    .sort((a, b) => (sort ? groupRank(a.entities) - groupRank(b.entities) : 0) || (a.sequence?.order ?? 0) - (b.sequence?.order ?? 0))
}
