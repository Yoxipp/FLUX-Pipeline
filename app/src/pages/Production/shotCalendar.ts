import type { CalendarItem, ProductionShot, ProductionState } from '../../types'
import { departmentTasks, trackingDepartments, trackingTaskStatus } from './tracking'

/** Calendar links are token strings, not title searches. Match both parent and shot. */
export function calendarLinksShot(link: string, sequence: string, shot: string): boolean {
  const tokens = link.toUpperCase().split(/[^A-Z0-9]+/).filter(Boolean)
  return Boolean(sequence && shot) && [sequence, shot].every(name => tokens.includes(name.toUpperCase()))
}

export type ShotDeadline = 'None' | 'In time' | 'Late' | 'Extra-late' | 'Done'
export function shotDeadline(state: ProductionState, shot: ProductionShot, items: CalendarItem[], now = new Date()): ShotDeadline {
  const sequence = state.sequences.find(s => s.id === shot.seq_id)?.name ?? ''
  const linked = items.filter(it => it.status !== 'declined' && calendarLinksShot(it.link, sequence, shot.name))
  if (!linked.length) return 'None'
  const statuses = trackingDepartments(state, 'shot').flatMap(dep => {
    const tasks = departmentTasks(state, shot, dep)
    if (!tasks.length) {
      const virtual = { id: '', name: dep.task_tokens[0] ?? dep.name.toUpperCase(), order: 0, type_tokens: [], known_subtasks: [] }
      const status = trackingTaskStatus(shot, virtual, dep)
      return status ? [status] : []
    }
    return tasks.map(task => trackingTaskStatus(shot, task, dep)).filter(Boolean)
  })
  if (statuses.length && statuses.every(status => status === 'APPROVED')) return 'Done'
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate())
  const remaining = linked.filter(it => it.status !== 'done').flatMap(it => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(it.end)) return []
    const [y, m, d] = it.end.split('-').map(Number)
    const end = Date.UTC(y, m - 1, d)
    if (new Date(end).toISOString().slice(0, 10) !== it.end) return []
    return [(end - today) / 86_400_000]
  })
  // Finished calendar entries don't imply that production reviews are approved.
  if (!remaining.length) return 'In time'
  const days = Math.min(...remaining)
  return days <= 0 ? 'Extra-late' : days < 5 ? 'Late' : 'In time'
}
