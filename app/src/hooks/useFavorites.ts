// useFavorites — user-wide favorite tasks/subtasks.
//
// LOCAL-FIRST (see server-load optimisation): the working copy lives in
// localStorage, so reads and toggles are instant and never touch the network on
// the hot path — this also removes the old read-modify-write round-trip against
// the shared User.json that could revert an optimistic toggle. The server copy
// (`production.favorites` in User.json via /settings/user-data) is kept as the
// cross-machine backup: seeded into local ONCE at startup (server authoritative
// unless a local change is still pending) and updated by a debounced,
// fire-and-forget write-behind. Favorites therefore follow the artist across
// machines while the UI stays offline-tolerant and chatter-free.
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
const LS_KEY = 'flux.favorites'          // local-first store (source of truth for the UI)
const FLUSH_DEBOUNCE_MS = 1_200          // coalesce rapid toggles into one server write
const FLUSH_MAX_RETRIES = 3

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

// ── local-first shared list (source of truth = localStorage) ──────────────────
// Cross-component sync via a small event bus; cross-machine sync via a debounced
// write-behind to the server and a one-time seed at startup.
let _cached: string[] | null = null
let _pending = false           // a local change not yet confirmed synced to server
let _seeded = false            // startup seed-from-server done once
let _flushTimer: ReturnType<typeof setTimeout> | undefined
const _bus = new EventTarget()

function _lsRead(): string[] {
  try {
    const raw = localStorage.getItem(LS_KEY)
    const arr = raw ? JSON.parse(raw) : []
    return Array.isArray(arr) ? arr.filter((x): x is string => typeof x === 'string') : []
  } catch { return [] }
}
function _lsWrite(list: string[]) {
  try { localStorage.setItem(LS_KEY, JSON.stringify(list)) } catch { /* storage blocked */ }
}

function _readCache(): string[] {
  if (_cached === null) _cached = _lsRead()
  return _cached
}
function _set(next: string[]) {
  _cached = next
  _lsWrite(next)                          // durable locally, instantly
  _bus.dispatchEvent(new Event('change'))
}

// Debounced, fire-and-forget push of the local list to the server backup.
function _scheduleFlush(attempt = 0) {
  _pending = true
  if (_flushTimer) clearTimeout(_flushTimer)
  _flushTimer = setTimeout(() => { void _flush(attempt) }, FLUSH_DEBOUNCE_MS)
}
async function _flush(attempt: number) {
  const list = _readCache()
  try {
    // Merge into the existing production sub-object so sibling keys survive.
    const d = await api.getUserData()
    const prod = (d[KEY] ?? {}) as Record<string, unknown>
    await api.setUserData({ [KEY]: { ...prod, favorites: list } })
    _pending = false
  } catch {
    if (attempt < FLUSH_MAX_RETRIES) _scheduleFlush(attempt + 1)   // bounded retry
    else _pending = false   // give up; local stays correct, next toggle re-syncs
  }
}

// One-time seed from the server backup. Server is authoritative EXCEPT when a
// local change is still pending (so we never clobber an unsynced toggle).
async function _seed(): Promise<void> {
  if (_seeded) return
  _seeded = true
  _readCache()   // ensure local is loaded/rendered first
  try {
    const d = await api.getUserData()
    const p = (d[KEY] ?? {}) as { favorites?: string[] }
    const serverList = Array.isArray(p.favorites) ? p.favorites.filter(x => typeof x === 'string') : []
    if (!_pending) _set(serverList)
  } catch { /* offline — keep local */ }
}

// General-purpose hook exposing the full list.
export function useFavorites(): {
  favorites: string[]
  toggleKey: (k: string) => Promise<void>
  has: (k: string) => boolean
  reload: () => Promise<void>
} {
  const [favorites, setFavorites] = useState<string[]>(() => _readCache())
  useEffect(() => {
    setFavorites(_readCache())            // render local immediately
    void _seed()                          // then reconcile with the server backup
    const on = () => setFavorites(_readCache())
    _bus.addEventListener('change', on)
    return () => _bus.removeEventListener('change', on)
  }, [])
  const has = useCallback((k: string) => favorites.includes(k), [favorites])
  const toggleKey = useCallback(async (k: string) => {
    const list = _readCache()
    const next = list.includes(k) ? list.filter(x => x !== k) : [...list, k]
    _set(next)                            // instant, durable local update
    _scheduleFlush()                      // async server backup
  }, [])
  const reload = useCallback(async () => { _seeded = false; await _seed() }, [])
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
