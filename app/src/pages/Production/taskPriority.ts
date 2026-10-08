// taskPriority.ts - the ONE task priority logic (retake 07), shared by Production (badge
// marker + "Priorité" menu) and the home page "Mes tâches" panel, so they never diverge.
//
// Priority  : task_details[<TASK>|<SUBTASK>].priority = 'high' | 'low' ; absent = normal.
// Deadline  : nearest open Calendar entry linked to the shot (same matching as the
//             Production deadline badge, shotCalendar.ts) or to the asset NAME.
// Updated   : latest publish of the task or latest comment on it.

import type { CalendarItem, ProductionAsset, ProductionPublish, ProductionShot, ProductionState, ProductionTask, ProductionTaskDetail } from '../../types'
import { ensureTrackingTask, effectiveTasks, taskStatus, detailStatus } from './tracking'
import { calendarLinksShot } from './shotCalendar'
import type { TaskEntity } from './taskActions'

export type Priority = 'high' | 'normal' | 'low'
export const PRIORITIES: Priority[] = ['high', 'normal', 'low']
export const PRIORITY_LABEL: Record<Priority, string> = { high: 'Haute', normal: 'Normale', low: 'Basse' }
const PRIORITY_RANK: Record<Priority, number> = { high: 0, normal: 1, low: 2 }
// What needs the artist first: a retake, work in progress, not started, waiting, done.
const STATUS_RANK: Record<string, number> = { RTK: 0, WIP: 1, TODO: 2, WFA: 3, APPROVED: 5 }

export function priorityOf(detail: ProductionTaskDetail | undefined): Priority {
  const p = detail?.priority
  return p === 'high' || p === 'low' ? p : 'normal'
}

const detailKey = (task: ProductionTask, subtask: string) =>
  `${task.name.toUpperCase()}${subtask ? `|${subtask.toUpperCase()}` : ''}`

/** Set the priority of a task / subtask ('normal' removes the field). */
export function patchTaskPriority(state: ProductionState, entityId: string, task: ProductionTask, subtask: string, priority: Priority): ProductionState {
  const next = ensureTrackingTask(state, entityId, task)
  const key = detailKey(task, subtask)
  const patch = <T extends TaskEntity>(entity: T): T => {
    if (entity.id !== entityId) return entity
    const { priority: _old, ...rest } = entity.task_details?.[key] ?? {}
    return { ...entity, task_details: { ...entity.task_details, [key]: priority === 'normal' ? rest : { ...rest, priority } } }
  }
  return { ...next, assets: next.assets.map(patch), shots: next.shots.map(patch), sequences: next.sequences.map(patch) }
}

export interface MyTask {
  id: string                        // stable: <entity id>|<detail key>
  entity: ProductionShot | ProductionAsset
  kind: 'shot' | 'asset'
  label: string                     // "SEQ0010 SHOT0020" or "CHAR HERO"
  seq: string                       // sequence name for a shot, class for an asset
  task: ProductionTask
  subtask: string
  status: string
  priority: Priority
  deadline: string | null           // YYYY-MM-DD
  updated: string                   // "YYYY-MM-DD HH:MM" or ''
}

/** Every task / subtask of *state* assigned to *username*. */
export function myTasks(state: ProductionState, username: string, items: CalendarItem[] = [],
  publishesByTask: Record<string, ProductionPublish[]> = {}): MyTask[] {
  const who = username.trim().toUpperCase()
  if (!who) return []
  const out: MyTask[] = []
  const entities: (ProductionShot | ProductionAsset)[] = [...state.shots, ...state.assets]
  for (const entity of entities) {
    const isShot = 'seq_id' in entity
    const seq = isShot ? state.sequences.find(s => s.id === entity.seq_id)?.name ?? '' : entity.class
    const deadline = entityDeadline(isShot ? seq : '', entity.name, items)
    for (const [key, detail] of Object.entries(entity.task_details ?? {})) {
      if (detail.assignee?.trim().toUpperCase() !== who) continue
      const [taskName, subtask = ''] = key.split('|')
      const task = effectiveTasks(state, entity).find(t => t.name.toUpperCase() === taskName.toUpperCase())
        ?? { id: '', name: taskName, order: 0, type_tokens: [], known_subtasks: [] }
      const status = subtask ? detailStatus(detail) : taskStatus(entity, task)
      const pubs = publishesByTask[`${entity.id}|${task.id}`] ?? []
      const stamps = [
        ...pubs.filter(p => !subtask || (p.instance ?? '').toUpperCase() === subtask.toUpperCase()).map(p => `${p.date} ${p.time.slice(0, 5)}`),
        ...(detail.comments ?? []).map(c => `${c.date} ${c.time.slice(0, 5)}`),
      ].sort()
      out.push({
        id: `${entity.id}|${key.toUpperCase()}`, entity, kind: isShot ? 'shot' : 'asset',
        label: `${seq} ${entity.name}`.trim(), seq, task, subtask, status,
        priority: priorityOf(detail), deadline, updated: stamps[stamps.length - 1] ?? '',
      })
    }
  }
  return out
}

/** Nearest open end date of the Calendar entries linked to a shot (seq + shot) or an asset. */
export function entityDeadline(seq: string, name: string, items: CalendarItem[]): string | null {
  const ends = items.filter(it => it.status !== 'declined' && it.status !== 'done' && /^\d{4}-\d{2}-\d{2}$/.test(it.end))
    .filter(it => seq ? calendarLinksShot(it.link, seq, name)
      : it.link.toUpperCase().split(/[^A-Z0-9]+/).includes(name.toUpperCase()))
    .map(it => it.end).sort()
  return ends[0] ?? null
}

export type MyTaskSort = 'smart' | 'deadline' | 'priority' | 'status' | 'updated' | 'name'
export const SORT_LABEL: Record<MyTaskSort, string> = {
  smart: 'Recommandé', deadline: 'Deadline', priority: 'Priorité', status: 'Statut', updated: 'Mise à jour', name: 'Nom',
}

const done = (t: MyTask) => t.status === 'APPROVED'
const byDeadline = (a: MyTask, b: MyTask) => (a.deadline ?? '9999') .localeCompare(b.deadline ?? '9999')
const byPriority = (a: MyTask, b: MyTask) => PRIORITY_RANK[a.priority] - PRIORITY_RANK[b.priority]
const byStatus = (a: MyTask, b: MyTask) => (STATUS_RANK[a.status] ?? 4) - (STATUS_RANK[b.status] ?? 4)
const byUpdated = (a: MyTask, b: MyTask) => b.updated.localeCompare(a.updated)
const byName = (a: MyTask, b: MyTask) => `${a.label} ${a.task.name} ${a.subtask}`.localeCompare(`${b.label} ${b.task.name} ${b.subtask}`, 'en', { numeric: true })

/**
 * Stable, deterministic order. Validated tasks always go last; missing deadline,
 * priority or status sort after the known ones, the name breaks every tie.
 * 'smart' = deadline, then priority, then status: what is due first and matters most.
 */
export function sortMyTasks(tasks: MyTask[], sort: MyTaskSort): MyTask[] {
  const chain: ((a: MyTask, b: MyTask) => number)[] = {
    smart: [byDeadline, byPriority, byStatus],
    deadline: [byDeadline, byPriority],
    priority: [byPriority, byDeadline],
    status: [byStatus, byDeadline],
    updated: [byUpdated],
    name: [],
  }[sort]
  return [...tasks].sort((a, b) => {
    if (done(a) !== done(b)) return done(a) ? 1 : -1
    for (const cmp of chain) { const r = cmp(a, b); if (r) return r }
    return byName(a, b) || a.id.localeCompare(b.id)
  })
}
