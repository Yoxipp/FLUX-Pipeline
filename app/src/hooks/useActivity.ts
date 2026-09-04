// useActivity.ts — thin subscriber to the shared activity feed (see useFeeds).
//
// Historically this hook owned its own 10s poller. Polling now lives in
// FeedsProvider (one poller for the whole app); this wrapper just slices the
// shared event list to the caller's limit so existing call sites are unchanged.

import { useMemo } from 'react'
import { useActivityFeed } from './useFeeds'

export function useActivity(limit = 50) {
  const { events, unreadCount, refresh, markAllRead } = useActivityFeed()
  const sliced = useMemo(() => events.slice(0, limit), [events, limit])
  return { events: sliced, unreadCount, refresh, markAllRead }
}
