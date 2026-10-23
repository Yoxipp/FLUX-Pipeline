// history.ts — undo / redo over immutable documents (03_EDITEUR §9). Pure functions, no
// dependency: a reducer only recreates what changes, so each entry shares the rest of the
// document with its neighbours. Cap 200 entries. Same coalesceKey within 800 ms = one
// entry (typing in one field). Selection, view, panels, issues and run states stay out.

export const HISTORY_CAP = 200
export const COALESCE_MS = 800

export interface History<T> {
  past:    T[]
  present: T
  future:  T[]
  lastKey: string | null   // coalesceKey of the last push
  lastAt:  number
}

export function initHistory<T>(present: T): History<T> {
  return { past: [], present, future: [], lastKey: null, lastAt: 0 }
}

export function pushHistory<T>(h: History<T>, next: T, opts: { coalesceKey?: string; now?: number } = {}): History<T> {
  if (next === h.present) return h
  const now = opts.now ?? Date.now()
  const key = opts.coalesceKey ?? null
  if (key !== null && key === h.lastKey && now - h.lastAt < COALESCE_MS) {
    return { ...h, present: next, future: [], lastAt: now }
  }
  const past = h.past.length >= HISTORY_CAP ? [...h.past.slice(h.past.length - HISTORY_CAP + 1), h.present] : [...h.past, h.present]
  return { past, present: next, future: [], lastKey: key, lastAt: now }
}

export const canUndo = <T>(h: History<T>) => h.past.length > 0
export const canRedo = <T>(h: History<T>) => h.future.length > 0

export function undo<T>(h: History<T>): History<T> {
  if (!h.past.length) return h
  return { past: h.past.slice(0, -1), present: h.past[h.past.length - 1], future: [h.present, ...h.future], lastKey: null, lastAt: 0 }
}

export function redo<T>(h: History<T>): History<T> {
  if (!h.future.length) return h
  return { past: [...h.past, h.present], present: h.future[0], future: h.future.slice(1), lastKey: null, lastAt: 0 }
}
