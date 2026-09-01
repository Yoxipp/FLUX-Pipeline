// useActivity.ts — polling hook pour le feed d'activité.

import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { ActivityEvent } from '../types'

const POLL_INTERVAL_MS = 10_000

export function useActivity(limit = 50) {
  const [events, setEvents] = useState<ActivityEvent[]>([])
  const [unreadCount, setUnreadCount] = useState(0)

  const refresh = useCallback(async () => {
    try {
      const data = await api.getActivity({ limit })
      setEvents(data.events)
      setUnreadCount(data.unread_count)
    } catch {
      // backend non disponible — garde le state existant
    }
  }, [limit])

  useEffect(() => {
    void refresh()
    const id = setInterval(() => { void refresh() }, POLL_INTERVAL_MS)
    const onRefresh = () => { void refresh() }
    window.addEventListener('flux:refresh', onRefresh)
    return () => {
      clearInterval(id)
      window.removeEventListener('flux:refresh', onRefresh)
    }
  }, [refresh])

  const markAllRead = useCallback(async () => {
    await api.markAllRead()
    await refresh()
  }, [refresh])

  return { events, unreadCount, refresh, markAllRead }
}
