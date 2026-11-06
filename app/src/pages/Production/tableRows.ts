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

/** Retake B2: asset classes shown first, in this order; other classes follow alphabetically. */
export const ASSET_CLASS_ORDER = ['CHAR', 'ENV', 'PROPS']

/** Group an asset class shows under: FXRIG is animated, so under Chara (display only, the token stays). */
export const assetDisplayClass = (cls: string): string => {
  const key = cls.toUpperCase()
  return key === 'FXRIG' ? 'CHAR' : key
}

/**
 * Retake B4 "Deadline + Me concerne": rows with a task assigned to me first, then the
 * nearest open Calendar deadline (no deadline last). Callers supply both lookups.
 */
export interface PersonalSort {
  mine: (entity: TrackingEntity) => boolean
  deadline: (entity: TrackingEntity) => string | null
}

export interface ProductionRowGroup {
  id: string
  sequence: ProductionSequence | null
  /** Asset mode only: class token of the group (CHAR, PROPS, ...). */
  assetClass?: string
  entities: TrackingEntity[]
}

/** Sorting is a view preference: sequence blocks remain intact and disk/order metadata stays untouched. */
export function productionRowGroups(state: ProductionState, entities: TrackingEntity[], mode: 'shot' | 'asset', departments: ProductionDepartment[], sort: DepartmentSort, emptySequences: ProductionSequence[] = [], personal: PersonalSort | null = null): ProductionRowGroup[] {
  const dep = departments.find(d => d.id === sort?.id)
  const rank = (entity: TrackingEntity) => dep && sort ? departmentRank(state, entity, dep, sort.first) : 0
  const personalKey = (entity: TrackingEntity) => personal ? `${personal.mine(entity) ? 0 : 1}|${personal.deadline(entity) ?? '9999-99-99'}` : ''
  const compare = (a: TrackingEntity, b: TrackingEntity) => personalKey(a).localeCompare(personalKey(b)) || rank(a) - rank(b) || a.order - b.order || a.name.localeCompare(b.name, undefined, { numeric: true })
  const groupKey = (rows: TrackingEntity[]) => rows.length ? rows.map(personalKey).sort()[0] : '~'
  const groupRank = (rows: TrackingEntity[]) => rows.length ? Math.min(...rows.map(rank)) : Number.MAX_SAFE_INTEGER
  if (mode === 'asset') {
    const byClass = new Map<string, TrackingEntity[]>()
    for (const entity of entities) {
      const cls = assetDisplayClass('class' in entity ? entity.class : '') || 'OTHER'
      if (!byClass.has(cls)) byClass.set(cls, [])
      byClass.get(cls)!.push(entity)
    }
    const classRank = (cls: string) => { const i = ASSET_CLASS_ORDER.indexOf(cls); return i < 0 ? ASSET_CLASS_ORDER.length : i }
    return [...byClass.entries()]
      .map(([cls, rows]) => ({ id: `class:${cls}`, sequence: null, assetClass: cls, entities: [...rows].sort(compare) }))
      .sort((a, b) => classRank(a.assetClass) - classRank(b.assetClass) || a.assetClass.localeCompare(b.assetClass))
  }
  const groups = new Map<string, ProductionRowGroup>()
  for (const sequence of emptySequences) groups.set(sequence.id, { id: sequence.id, sequence, entities: [] })
  for (const entity of entities) {
    if (!('seq_id' in entity)) continue
    if (!groups.has(entity.seq_id)) groups.set(entity.seq_id, { id: entity.seq_id, sequence: state.sequences.find(s => s.id === entity.seq_id) ?? null, entities: [] })
    groups.get(entity.seq_id)!.entities.push(entity)
  }
  return [...groups.values()].map(group => ({ ...group, entities: [...group.entities].sort(compare) }))
    .sort((a, b) => (personal ? groupKey(a.entities).localeCompare(groupKey(b.entities)) : 0)
      || (sort ? groupRank(a.entities) - groupRank(b.entities) : 0) || (a.sequence?.order ?? 0) - (b.sequence?.order ?? 0))
}
