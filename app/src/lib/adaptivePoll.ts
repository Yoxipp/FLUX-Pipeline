// adaptivePoll.ts — shared helper for the polled network feeds (activity, mentions,
// calendar, team chat). One module-level store, so every feed feeds the same picture.
//
//  • jitter(base)          : random 0..30 % of the interval, added once to the first
//                            scheduled tick so machines started together desync.
//  • timed(key, promise)   : measures one poll request. > 2000 ms doubles that feed's
//                            interval (cap 8x), each fast (< 500 ms) answer halves it back.
//  • adaptiveDelay(k, ms)  : base interval times the current multiplier of the feed(s).
//  • startAdaptivePoll     : self-scheduling loop for hooks that used setInterval.
//  • useShareLatency       : rolling median of the measured durations, for the title bar
//                            badge (on above 1000 ms, off again under 700 ms).

import { useSyncExternalStore } from 'react'

const SLOW_MS = 2000
const FAST_MS = 500
const MAX_MULT = 8
const SAMPLES = 9
const BADGE_ON_MS = 1000
const BADGE_OFF_MS = 700

const mults = new Map<string, number>()
const samples: number[] = []
let badge: { slow: boolean; medianMs: number } = { slow: false, medianMs: 0 }
const listeners = new Set<() => void>()

export const jitter = (baseMs: number): number => Math.random() * baseMs * 0.3

function record(key: string, ms: number) {
  const m = mults.get(key) ?? 1
  if (ms > SLOW_MS) mults.set(key, Math.min(m * 2, MAX_MULT))
  else if (ms < FAST_MS && m > 1) mults.set(key, Math.max(m / 2, 1))

  samples.push(ms)
  if (samples.length > SAMPLES) samples.shift()
  const sorted = [...samples].sort((a, b) => a - b)
  const median = sorted[Math.floor(sorted.length / 2)]
  const slow = badge.slow ? median >= BADGE_OFF_MS : median > BADGE_ON_MS
  if (slow !== badge.slow || (slow && Math.abs(median - badge.medianMs) >= 100)) {
    badge = { slow, medianMs: median }
    listeners.forEach(l => l())
  }
}

/** Await a poll request and record how long it took (failures are not recorded). */
export async function timed<T>(key: string, p: Promise<T>): Promise<T> {
  const t0 = performance.now()
  const r = await p
  record(key, performance.now() - t0)
  return r
}

/** Base interval stretched by the slowest of the given feeds. */
export function adaptiveDelay(keys: string | string[], baseMs: number): number {
  const list = Array.isArray(keys) ? keys : [keys]
  const m = Math.max(1, ...list.map(k => mults.get(k) ?? 1))
  return baseMs * m
}

/** Self-scheduling poll: `fn` must return the request promise (timed here). Returns stop(). */
export function startAdaptivePoll(key: string, baseMs: number, fn: () => Promise<unknown>): () => void {
  let timer: ReturnType<typeof setTimeout> | undefined
  let stopped = false
  let first = true
  const arm = () => {
    if (stopped) return
    const extra = first ? jitter(baseMs) : 0
    first = false
    timer = setTimeout(() => {
      void timed(key, fn()).catch(() => {}).finally(arm)
    }, adaptiveDelay(key, baseMs) + extra)
  }
  arm()
  return () => { stopped = true; if (timer) clearTimeout(timer) }
}

const subscribe = (l: () => void) => { listeners.add(l); return () => { listeners.delete(l) } }
const snapshot = () => badge

/** { slow, medianMs } — slow flips on above 1000 ms and off under 700 ms. */
export function useShareLatency() {
  return useSyncExternalStore(subscribe, snapshot)
}
