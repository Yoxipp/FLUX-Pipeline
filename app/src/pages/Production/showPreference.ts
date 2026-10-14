import type { ShowFilter } from './ProductionTableMenus'

export function productionShowKey(project: string, mode: 'shot' | 'asset', entityId?: string): string {
  return `flux.production.show.${JSON.stringify([project, mode, entityId ?? null])}`
}

export function readProductionShow(key: string, storage?: Pick<Storage, 'getItem'>): ShowFilter {
  try {
    const value: unknown = JSON.parse((storage ?? localStorage).getItem(key) ?? 'null')
    if (!value || typeof value !== 'object' || !('kind' in value)) return { kind: 'all' }
    if (value.kind === 'all' || value.kind === 'mine') return { kind: value.kind }
    if (value.kind === 'seq' && 'id' in value && typeof value.id === 'string' && value.id.trim()) return { kind: 'seq', id: value.id }
  } catch { /* Corrupt or unavailable storage: the table stays usable. */ }
  return { kind: 'all' }
}

export function writeProductionShow(key: string, filter: ShowFilter, storage?: Pick<Storage, 'setItem'>): void {
  try { (storage ?? localStorage).setItem(key, JSON.stringify(filter)) }
  catch { /* Keep the current selection even when local storage is unavailable. */ }
}
