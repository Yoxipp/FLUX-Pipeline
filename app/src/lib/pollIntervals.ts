// pollIntervals.ts — single source of truth for the app's polling cadences.
//
// The shared network files (activite.json, chatMentions.json, teamChat.json) are
// hit by every FLUX instance; keeping the intervals here makes the load per
// instance easy to reason about and tune in one place.

// Activity feed + @mentions — the two hot shared feeds, driven by FeedsProvider.
// Raised from 10s to 30s (Phase 1 of the server-load optimisation): notification
// latency stays ≤30s while idle read traffic drops ~3×. `flux:refresh` still
// forces an immediate refetch, so user-triggered updates are not delayed.
export const FEED_POLL_INTERVAL_MS = 30_000

// Team chat (Hub page only, mounted while the Hub is open). Left at its original
// cadence — the chat is a foreground, actively-watched view — but centralised
// here so it is never accidentally sped up.
export const HUB_CHAT_POLL_INTERVAL_MS = 10_000
