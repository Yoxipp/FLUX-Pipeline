// useMentions.ts — thin subscriber to the shared mentions feed (see useFeeds).
//
// Polling now lives in FeedsProvider (one poller for the whole app); this
// wrapper exposes just the unread count + a manual refresh so existing call
// sites (Sidebar badge) are unchanged.

import { useMentionsFeed } from './useFeeds'

export function useMentions() {
  const { unreadMentions, refreshMentions } = useMentionsFeed()
  return { unreadMentions, refreshMentions }
}
