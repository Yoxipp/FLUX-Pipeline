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
//
// Retake 04: the activity feed is no longer the global log. It is the active
// project's feed for the current artist (GET /activity/notifications, scope global),
// every event annotated server-side with its `reason` (followed shot, favorite,
// assigned task). The unread badge counts only events that concern the artist.

import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState,
  type ReactNode,
} from 'react'
import { api } from '../api/client'
import {
  FEED_POLL_INTERVAL_MS, IDLE_AFTER_MS, IDLE_POLL_INTERVAL_MS,
} from '../lib/pollIntervals'
import { useProject } from '../ProjectContext'
import type { ActivityEvent, ChatMention, FollowedShot } from '../types'

// Upper bound for the shared activity fetch. FavoriteWatcher needs a deep window
// to catch matches; other consumers (badge, Hub) slice this down locally.
const ACTIVITY_LIMIT = 100

interface FeedsValue {
  events: ActivityEvent[]
  followedShots: FollowedShot[]
  feedProject: string
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
  const [followedShots, setFollowedShots] = useState<FollowedShot[]>([])
  const [feedProject, setFeedProject]   = useState('')
  const { project } = useProject()
  const projectRef = useRef(project)
  projectRef.current = project
  const [unreadCount, setUnreadCount]   = useState(0)
  const [activityLoaded, setActivityLoaded] = useState(false)
  const [mentions, setMentions]         = useState<ChatMention[]>([])
  const [unreadMentions, setUnreadMentions] = useState(0)
  const [mentionsLoaded, setMentionsLoaded] = useState(false)

  // Stored ETags (Phase 2): echoed back each tick so an unchanged file answers
  // 304 and we skip both the transfer and a needless re-render.
  const mentionsEtag = useRef<string | undefined>(undefined)

  const refreshActivity = useCallback(async () => {
    const current = projectRef.current
    if (!current) {
      setEvents([]); setFollowedShots([]); setUnreadCount(0); setFeedProject(''); setActivityLoaded(true)
      return
    }
    try {
      const r = await api.getNotifications(current, 'global', ACTIVITY_LIMIT)
      if (projectRef.current !== current) return   // project switched meanwhile
      setEvents(r.events)
      setFollowedShots(r.followed_shots)
      setUnreadCount(r.events.filter(e => e.reason && !e.read).length)
      setFeedProject(current)
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

  // Self-scheduling poller gated by window visibility and real user activity:
  //  • hidden window            → fully paused (no polling at all)
  //  • visible + recent action  → normal cadence (FEED_POLL_INTERVAL_MS)
  //  • visible + idle ≥ 20 min  → drastic slow-down (IDLE_POLL_INTERVAL_MS)
  // "Idle" is measured ONLY against genuine user input (pointerdown/keydown),
  // never mouse-move/scroll/focus and never our own polling, so it can't be
  // bypassed: a visible-but-untouched window still sleeps at 20 min. Returning
  // to the window, or the next real click/keypress, wakes it instantly with a
  // catch-up fetch.
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined
    let mode: 'active' | 'idle' | 'paused' = 'active'
    let lastActivity = Date.now()
    let stopped = false

    const refetchAll = () => { void refreshActivity(); void refreshMentions() }
    const clear = () => { if (timer) { clearTimeout(timer); timer = undefined } }

    const schedule = () => {
      clear()
      if (stopped || document.hidden) { mode = 'paused'; return }
      const idle = Date.now() - lastActivity >= IDLE_AFTER_MS
      mode = idle ? 'idle' : 'active'
      const delay = idle ? IDLE_POLL_INTERVAL_MS : FEED_POLL_INTERVAL_MS
      timer = setTimeout(() => {
        refetchAll()
        schedule()   // recompute the mode AFTER each tick (may have gone idle)
      }, delay)
    }

    const wakeFromDormant = () => {
      // Only called when we were idle or paused → catch up now and resume cadence.
      lastActivity = Date.now()
      refetchAll()
      schedule()
    }

    const onUserAction = () => {
      // Capture-phase so a stopPropagation elsewhere can't hide the action.
      if (mode === 'active') { lastActivity = Date.now(); return }  // keep the running timer
      wakeFromDormant()                                             // idle → instant resume
    }
    const onVisibility = () => {
      if (document.hidden) { clear(); mode = 'paused' }
      else wakeFromDormant()   // returning to the window = wake + catch-up
    }
    const onRefresh  = () => refetchAll()
    const onMentions = () => { void refreshMentions() }

    refetchAll()
    schedule()
    document.addEventListener('visibilitychange', onVisibility)
    window.addEventListener('pointerdown', onUserAction, true)
    window.addEventListener('keydown', onUserAction, true)
    window.addEventListener('flux:refresh', onRefresh)
    window.addEventListener('flux:mentions', onMentions)
    return () => {
      stopped = true
      clear()
      document.removeEventListener('visibilitychange', onVisibility)
      window.removeEventListener('pointerdown', onUserAction, true)
      window.removeEventListener('keydown', onUserAction, true)
      window.removeEventListener('flux:refresh', onRefresh)
      window.removeEventListener('flux:mentions', onMentions)
    }
  }, [refreshActivity, refreshMentions])

  // Another project = another feed, fetched at once.
  useEffect(() => { void refreshActivity() }, [project, refreshActivity])

  const value = useMemo<FeedsValue>(() => ({
    events, followedShots, feedProject, unreadCount, activityLoaded,
    mentions, unreadMentions, mentionsLoaded,
    refreshActivity, refreshMentions, markAllRead,
  }), [
    events, followedShots, feedProject, unreadCount, activityLoaded, mentions, unreadMentions, mentionsLoaded,
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
  const { events, followedShots, feedProject, unreadCount, activityLoaded, refreshActivity, markAllRead } = useFeeds()
  return { events, followedShots, project: feedProject, unreadCount, loaded: activityLoaded, refresh: refreshActivity, markAllRead }
}

/** Shared mentions feed (full list + unread count). */
export function useMentionsFeed() {
  const { mentions, unreadMentions, mentionsLoaded, refreshMentions } = useFeeds()
  return { mentions, unreadMentions, loaded: mentionsLoaded, refreshMentions }
}
