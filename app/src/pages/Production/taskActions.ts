import type { ProductionAsset, ProductionSequence, ProductionShot, ProductionState, ProductionTask, ProductionTaskDetail } from '../../types'
import { ensureTrackingTask, patchTrackingDetail } from './tracking'

export type TaskEntity = ProductionAsset | ProductionShot | ProductionSequence

export function patchTaskArtist(state: ProductionState, entityId: string, task: ProductionTask, subtask: string, assignee: string): ProductionState {
  const next = ensureTrackingTask(state, entityId, task)
  const key = `${task.name.toUpperCase()}${subtask ? `|${subtask.toUpperCase()}` : ''}`
  const patch = <T extends TaskEntity>(entity: T): T => entity.id === entityId
    ? { ...entity, task_details: { ...entity.task_details, [key]: { ...entity.task_details?.[key], assignee } } } : entity
  return { ...next, assets: next.assets.map(patch), shots: next.shots.map(patch), sequences: next.sequences.map(patch) }
}

export function setTaskStatus(state: ProductionState, entity: TaskEntity, task: ProductionTask, subtask: string, status: string): ProductionState {
  if ('class' in entity || 'seq_id' in entity) return patchTrackingDetail(state, entity.id, task, subtask, status)
  const key = `${task.name.toUpperCase()}${subtask ? `|${subtask.toUpperCase()}` : ''}`
  return { ...state, sequences: state.sequences.map(seq => {
    if (seq.id !== entity.id) return seq
    const details: Record<string, ProductionTaskDetail> = { ...seq.task_details, [key]: { ...seq.task_details?.[key], status } }
    if (subtask && details[task.name.toUpperCase()]) {
      const { status: _status, ...rest } = details[task.name.toUpperCase()]
      details[task.name.toUpperCase()] = rest
    }
    return { ...seq, task_details: details }
  }) }
}

export function taskPublisherPrefill(project: string, state: ProductionState, entity: TaskEntity, task: ProductionTask) {
  const token = (task.type_tokens[0] || task.name).toUpperCase()
  if ('class' in entity) return { project, mode: 'asset', sel: { category: entity.class === 'FXRIG' ? 'FX' : entity.class, name: entity.name, task: token, instance: '', variante: '' } }
  return { project, mode: 'shot', sel: { seq: 'seq_id' in entity ? state.sequences.find(s => s.id === entity.seq_id)?.name ?? '' : entity.name, shot: 'seq_id' in entity ? entity.name : '', name: token, variante: '' } }
}

export function createShotBatch(state: ProductionState, seqId: string, count: number, main: string, secondary: string, label: string, id: () => string): ProductionState {
  const seq = state.sequences.find(s => s.id === seqId)
  if (!seq || seq.locked) throw new Error('Choisissez une séquence non verrouillée.')
  if (!Number.isInteger(count) || count < 1 || count > 1000) throw new Error('Le nombre de shots doit être compris entre 1 et 1000.')
  const siblings = state.shots.filter(s => s.seq_id === seqId)
  const numbers = siblings.map(s => Number(s.name.replace(/^SHOT/i, ''))).filter(Number.isFinite)
  const start = (main ? Number(main) * 10 : (Math.floor(Math.max(0, ...numbers) / 10) + 1) * 10) + Number(secondary || 0)
  if (!Number.isInteger(start) || start <= 0 || start + (count - 1) * 10 > 9999) throw new Error('Numéro de shot invalide (0010 à 9999).')
  const names = Array.from({ length: count }, (_, i) => `SHOT${String(start + i * 10).padStart(4, '0')}`)
  if (names.some(name => siblings.some(s => s.name.toUpperCase() === name))) throw new Error('Un des shots existe déjà. Aucun shot créé.')
  let sorted = [...siblings].sort((a, b) => a.order - b.order)
  for (const name of names) {
    const number = Number(name.slice(4))
    const before = sorted.find(s => Number(s.name.replace(/^SHOT/i, '')) > number)
    const order = before?.order ?? Math.max(-1, ...sorted.map(s => s.order)) + 1
    sorted = sorted.map(s => s.order >= order ? { ...s, order: s.order + 1 } : s)
    const created: ProductionShot = { id: id(), seq_id: seqId, name, label: label.trim() || undefined, order, inherit_tasks: true, inherit_assets: true, tasks: [], assets: [], task_details: {}, origin: 'user' }
    sorted.push(created)
    sorted.sort((a, b) => a.order - b.order)
  }
  return { ...state, shots: [...state.shots.filter(s => s.seq_id !== seqId), ...sorted] }
}
