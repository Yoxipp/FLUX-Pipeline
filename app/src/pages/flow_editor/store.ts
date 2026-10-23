// store.ts — small external store read through useSyncExternalStore (React 18.3, no
// dependency, 03_EDITEUR §9). Generic: the flow editor keeps its document here, the page
// editor (04) will reuse it. The document is the only source of truth; xyflow nodes and
// edges are derived from it. dirty = present !== saved (reference compare: a reducer that
// changes nothing returns the same object).

import { useSyncExternalStore } from 'react'
import { canRedo, canUndo, initHistory, pushHistory, redo, undo, type History } from './history'

export interface Store<S> {
  get: () => S
  set: (next: S | ((s: S) => S)) => void
  subscribe: (fn: () => void) => () => void
}

export function createStore<S>(initial: S): Store<S> {
  let state = initial
  const subs = new Set<() => void>()
  return {
    get: () => state,
    set: next => {
      const value = typeof next === 'function' ? (next as (s: S) => S)(state) : next
      if (value === state) return
      state = value
      subs.forEach(fn => fn())
    },
    subscribe: fn => { subs.add(fn); return () => { subs.delete(fn) } },
  }
}

// The selector must return a stable value (a slice of the state, not a new object).
export function useStore<S, R>(store: Store<S>, selector: (s: S) => R): R {
  return useSyncExternalStore(store.subscribe, () => selector(store.get()))
}

// -- document store with undo / redo -------------------------------------------

export interface DocState<D> {
  history: History<D> | null
  saved:   D | null
}

export interface DocStore<D> extends Store<DocState<D>> {
  load: (doc: D | null) => void                                    // clears the pile
  apply: (fn: (doc: D) => D, coalesceKey?: string) => void          // one undo entry
  undo: () => void
  redo: () => void
  markSaved: (doc?: D) => void                                     // after a save
}

export function createDocStore<D>(): DocStore<D> {
  const base = createStore<DocState<D>>({ history: null, saved: null })
  return {
    ...base,
    load: doc => base.set({ history: doc === null ? null : initHistory(doc), saved: doc }),
    apply: (fn, coalesceKey) => base.set(s => {
      if (!s.history) return s
      const next = fn(s.history.present)
      return next === s.history.present ? s : { ...s, history: pushHistory(s.history, next, { coalesceKey }) }
    }),
    undo: () => base.set(s => s.history && canUndo(s.history) ? { ...s, history: undo(s.history) } : s),
    redo: () => base.set(s => s.history && canRedo(s.history) ? { ...s, history: redo(s.history) } : s),
    markSaved: doc => base.set(s => s.history ? { ...s, saved: doc ?? s.history.present } : s),
  }
}

export const docOf = <D>(s: DocState<D>): D | null => s.history?.present ?? null
export const isDirty = <D>(s: DocState<D>): boolean => !!s.history && s.history.present !== s.saved
