// useFeeds.tsx — single shared source for the two hot shared feeds.
//
// Every instance of FLUX polls the same network-shared files (activite.json,
// chatMentions.json). Before this provider, the activity feed was polled by
// useActivity + FavoriteWatcher (two pollers) and the mentions feed by
// MentionWatcher + useMentions + the Activity page (three pollers) — all on
// their own 10s timers, so each instance hit the shared drive ~4×/10s.
//
// FeedsProvider runs EXACTLY ONE poller per feed at FEED_POLL_INTERVAL_MS and
// fans the result out to every consumer. `flux:refresh` / `flux:mentions` still
// trigger an immediate refetch, so user-visible latency stays low even though
// the idle cadence dropped to 30s.

import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState,
  type ReactNode,
} from 'react'
import { api } from '../api/client'
import { FEED_POLL_INTERVAL_MS } from '../lib/pollIntervals'
import type { ActivityEvent, ChatMention } from '../types'

// Upper bound for the shared activity fetch. FavoriteWatcher needs a deep window
// to catch matches; other consumers (badge, Hub) slice this down locally.
const ACTIVITY_LIMIT = 100

interface FeedsValue {
  events: ActivityEvent[]
  unreadCount: number
  activityLoaded: boolean
  mentions: ChatMention[]
  unreadMentions: number
  mentionsLoaded: boolean
  refreshActivity: () => Promise<void>
  refreshMentions: () => Promise<void>
  markAllRead: () => Promise<void>
}

const FeedsContext = createContext<FeedsValue | null>(null)

export function FeedsProvider({ children }: { children: ReactNode }) {
  const [events, setEvents]             = useState<ActivityEvent[]>([])
  const [unreadCount, setUnreadCount]   = useState(0)
  const [activityLoaded, setActivityLoaded] = useState(false)
  const [mentions, setMentions]         = useState<ChatMention[]>([])
  const [unreadMentions, setUnreadMentions] = useState(0)
  const [mentionsLoaded, setMentionsLoaded] = useState(false)

  // Stored ETags (Phase 2): echoed back each tick so an unchanged file answers
  // 304 and we skip both the transfer and a needless re-render.
  const activityEtag = useRef<string | undefined>(undefined)
  const mentionsEtag = useRef<string | undefined>(undefined)

  const refreshActivity = useCallback(async () => {
    try {
      const r = await api.getActivityConditional(ACTIVITY_LIMIT, activityEtag.current)
      activityEtag.current = r.etag
      if (r.notModified || !r.data) {
        setActivityLoaded(true)   // first tick may already be 304-clean
        return                    // unchanged — keep state, no re-render
      }
      setEvents(r.data.events)
      setUnreadCount(r.data.unread_count)
      setActivityLoaded(true)
    } catch {
      // backend non disponible — garde le state existant
    }
  }, [])

  const refreshMentions = useCallback(async () => {
    try {
      // No unread_only filter: the full list feeds the Activity page display,
      // while unread_count + the read flag feed the badge and the watcher.
      const r = await api.getMentionsConditional(mentionsEtag.current)
      mentionsEtag.current = r.etag
      if (r.notModified || !r.data) {
        setMentionsLoaded(true)
        return                    // unchanged — keep state, no re-render
      }
      setMentions(r.data.mentions)
      setUnreadMentions(r.data.unread_count)
      setMentionsLoaded(true)
    } catch {
      // backend not up — keep the previous state
    }
  }, [])

  const markAllRead = useCallback(async () => {
    await api.markAllRead()
    await refreshActivity()
  }, [refreshActivity])

  useEffect(() => {
    void refreshActivity()
    void refreshMentions()
    const id = setInterval(() => {
      void refreshActivity()
      void refreshMentions()
    }, FEED_POLL_INTERVAL_MS)
    const onRefresh  = () => { void refreshActivity(); void refreshMentions() }
    const onMentions = () => { void refreshMentions() }
    window.addEventListener('flux:refresh', onRefresh)
    window.addEventListener('flux:mentions', onMentions)
    return () => {
      clearInterval(id)
      window.removeEventListener('flux:refresh', onRefresh)
      window.removeEventListener('flux:mentions', onMentions)
    }
  }, [refreshActivity, refreshMentions])

  const value = useMemo<FeedsValue>(() => ({
    events, unreadCount, activityLoaded,
    mentions, unreadMentions, mentionsLoaded,
    refreshActivity, refreshMentions, markAllRead,
  }), [
    events, unreadCount, activityLoaded, mentions, unreadMentions, mentionsLoaded,
    refreshActivity, refreshMentions, markAllRead,
  ])

  return <FeedsContext.Provider value={value}>{children}</FeedsContext.Provider>
}

function useFeeds(): FeedsValue {
  const ctx = useContext(FeedsContext)
  if (!ctx) throw new Error('useFeeds must be used within a <FeedsProvider>')
  return ctx
}

/** Shared activity feed (events + unread badge). `loaded` flips true after the
 *  first successful fetch — watchers use it to avoid replaying the backlog. */
export function useActivityFeed() {
  const { events, unreadCount, activityLoaded, refreshActivity, markAllRead } = useFeeds()
  return { events, unreadCount, loaded: activityLoaded, refresh: refreshActivity, markAllRead }
}

/** Shared mentions feed (full list + unread count). */
export function useMentionsFeed() {
  const { mentions, unreadMentions, mentionsLoaded, refreshMentions } = useFeeds()
  return { mentions, unreadMentions, loaded: mentionsLoaded, refreshMentions }
}
