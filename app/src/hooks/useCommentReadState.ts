// useCommentReadState — user-wide read/unread flag on Production comments.
//
// Storage: /settings/user-data.production.comments_read: string[] (comment ids).
// Presence in the list = "this user has seen this comment".

import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'

const KEY = 'production'

let _cached: Set<string> | null = null
const _bus = new EventTarget()

async function _load(): Promise<Set<string>> {
  try {
    const d = await api.getUserData()
    const p = (d[KEY] ?? {}) as { comments_read?: string[] }
    const set = new Set(Array.isArray(p.comments_read) ? p.comments_read : [])
    _cached = set
    _bus.dispatchEvent(new Event('change'))
    return set
  } catch {
    _cached = new Set()
    _bus.dispatchEvent(new Event('change'))
    return _cached
  }
}

async function _save(next: Set<string>) {
  _cached = next
  _bus.dispatchEvent(new Event('change'))
  try {
    const d = await api.getUserData()
    const prod = (d[KEY] ?? {}) as Record<string, unknown>
    await api.setUserData({ [KEY]: { ...prod, comments_read: [...next] } })
  } catch { /* keep optimistic state */ }
}

export function useCommentReadState(): {
  isRead: (id: string) => boolean
  setRead: (id: string, read: boolean) => Promise<void>
} {
  const [tick, setTick] = useState(0)
  useEffect(() => {
    if (_cached === null) { void _load().then(() => setTick(t => t + 1)) }
    const on = () => setTick(t => t + 1)
    _bus.addEventListener('change', on)
    return () => _bus.removeEventListener('change', on)
  }, [])
  const isRead = useCallback((id: string) => !!_cached?.has(id), [tick])   // eslint-disable-line react-hooks/exhaustive-deps
  const setRead = useCallback(async (id: string, read: boolean) => {
    const next = new Set(_cached ?? [])
    if (read) next.add(id); else next.delete(id)
    await _save(next)
  }, [])
  return { isRead, setRead }
}
