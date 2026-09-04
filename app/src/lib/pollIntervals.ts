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

// ── Activity/idle gating of the shared poller (FeedsProvider) ────────────────
// After IDLE_AFTER_MS with no real user action (pointerdown / keydown — NOT
// mouse-move, scroll or focus, so a visible-but-untouched window still sleeps
// and the idle state cannot be trivially bypassed), the poller drops to
// IDLE_POLL_INTERVAL_MS. The next genuine user action (or the window being
// re-shown) wakes it instantly back to FEED_POLL_INTERVAL_MS with an immediate
// catch-up fetch. While the window is hidden the poller is fully paused.
export const IDLE_AFTER_MS = 20 * 60_000          // 20 min without a click/keypress
export const IDLE_POLL_INTERVAL_MS = 10 * 60_000  // drastic slow-down while idle (20× rarer)
