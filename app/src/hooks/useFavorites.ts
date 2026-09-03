// useFavorites — user-wide favorite tasks/subtasks, persisted in User.json
// via /settings/user-data (`production.favorites`).
//
// A favorite is a stable string key of the form:
//     "<project>|<class>/<name>|<task>"                — task favorite
//     "<project>|<class>/<name>|<task>|<subtask>"      — subtask favorite
//
// We use asset class + name (not asset_id) so the key survives publish-driven
// re-adoption when the id changes on a fresh reconcile pass. Both flavours
// share the same list; matchers below know how to compare with an activity
// event's parsed tokens.

import { useEffect, useState, useCallback } from 'react'
import { api } from '../api/client'
import { useProject } from '../ProjectContext'
import type {
  ProductionAsset, ProductionTask,
} from '../types'

const KEY = 'production'   // top-level bucket inside /settings/user-data

export function buildFavoriteKey(
  project: string, cls: string, name: string, task: string, subtask?: string | null,
): string {
  const base = `${project}|${cls.toUpperCase()}/${name.toUpperCase()}|${task.toUpperCase()}`
  return subtask ? `${base}|${subtask.toUpperCase()}` : base
}

// Match a favorite key against a parsed publish/comment event.
export function eventMatchesFavorite(
  favKey: string,
  parsed: { project: string; class: string; name: string; task: string; instance?: string | null },
): boolean {
  const parts = favKey.split('|')
  if (parts.length < 3) return false
  const [prj, entity, taskTok, subTok] = parts
  if (prj !== parsed.project) return false
  if (entity !== `${parsed.class.toUpperCase()}/${parsed.name.toUpperCase()}`) return false
  if (taskTok !== parsed.task.toUpperCase()) return false
  if (subTok) {
    const inst = (parsed.instance || '').toUpperCase()
    if (subTok !== inst) return false
  }
  return true
}

// ── shared list state (one fetch, cross-component sync via a small event bus)
let _cached: string[] | null = null
const _bus = new EventTarget()

function _readCache(): string[] { return _cached ?? [] }
function _writeCache(next: string[]) {
  _cached = next
  _bus.dispatchEvent(new Event('change'))
}

async function _load(): Promise<string[]> {
  try {
    const d = await api.getUserData()
    const p = (d[KEY] ?? {}) as { favorites?: string[] }
    const list = Array.isArray(p.favorites) ? [...p.favorites] : []
    _writeCache(list)
    return list
  } catch {
    _writeCache([])
    return []
  }
}

async function _save(next: string[]) {
  _writeCache(next)
  try {
    // Merge into existing production sub-object so we don't clobber sibling keys.
    const d = await api.getUserData()
    const prod = (d[KEY] ?? {}) as Record<string, unknown>
    await api.setUserData({ [KEY]: { ...prod, favorites: next } })
  } catch { /* keep local optimistic state */ }
}

// General-purpose hook exposing the full list.
export function useFavorites(): {
  favorites: string[]
  toggleKey: (k: string) => Promise<void>
  has: (k: string) => boolean
  reload: () => Promise<void>
} {
  const [favorites, setFavorites] = useState<string[]>(_readCache())
  useEffect(() => {
    if (_cached === null) { void _load().then(setFavorites) }
    const on = () => setFavorites(_readCache())
    _bus.addEventListener('change', on)
    return () => _bus.removeEventListener('change', on)
  }, [])
  const has = useCallback((k: string) => favorites.includes(k), [favorites])
  const toggleKey = useCallback(async (k: string) => {
    const list = _readCache()
    const next = list.includes(k) ? list.filter(x => x !== k) : [...list, k]
    await _save(next)
  }, [])
  const reload = useCallback(async () => { await _load() }, [])
  return { favorites, toggleKey, has, reload }
}

// Convenience binding for a TaskDetail header heart.
export function useFavoriteBinding(
  asset: ProductionAsset, task: ProductionTask, subtask: string | null,
): { isFavorite: boolean; toggle: () => Promise<void> } {
  const { project } = useProject()
  const { has, toggleKey } = useFavorites()
  const key = buildFavoriteKey(project || '', asset.class, asset.name, task.name, subtask)
  return {
    isFavorite: has(key),
    toggle: () => toggleKey(key),
  }
}
