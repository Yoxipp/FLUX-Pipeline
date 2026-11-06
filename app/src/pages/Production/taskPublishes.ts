// Publishes of a task, shared by the task panel and the entity context menu.
import type { ProductionPublish } from '../../types'

/** vNNN of a published file name ('' when none). */
export function publishVersion(file: string): string {
  return /_(v\d{3,})(?=\.|$)/i.exec(file)?.[1] ?? ''
}

/** Newest first, by date + time (ISO date + HH:MM sort lexicographically). */
export function sortPublishes(publishes: ProductionPublish[]): ProductionPublish[] {
  return [...publishes].sort((a, b) => `${b.date} ${b.time}`.localeCompare(`${a.date} ${a.time}`))
}

/** The publish of a version, newest match first; null when absent or no version is asked. */
export function publishOfVersion(sorted: ProductionPublish[], version: string | undefined): ProductionPublish | null {
  if (!version) return null
  return sorted.find(p => publishVersion(p.file).toLowerCase() === version.toLowerCase()) ?? null
}
