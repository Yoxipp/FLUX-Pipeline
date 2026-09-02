// useMentions.ts — polling hook for the current user's unread @mentions.
// The backend resolves "current user" from config, so no username is needed here.

import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'

const POLL_INTERVAL_MS = 10_000

export function useMentions() {
  const [unreadCount, setUnreadCount] = useState(0)

  const refresh = useCallback(async () => {
    try {
      const data = await api.getMentions(undefined, true)
      setUnreadCount(data.unread_count)
    } catch {
      // backend not up — keep the previous count
    }
  }, [])

  useEffect(() => {
    void refresh()
    const id = setInterval(() => { void refresh() }, POLL_INTERVAL_MS)
    const onRefresh = () => { void refresh() }
    window.addEventListener('flux:refresh', onRefresh)
    window.addEventListener('flux:mentions', onRefresh)
    return () => {
      clearInterval(id)
      window.removeEventListener('flux:refresh', onRefresh)
      window.removeEventListener('flux:mentions', onRefresh)
    }
  }, [refresh])

  return { unreadMentions: unreadCount, refreshMentions: refresh }
}
