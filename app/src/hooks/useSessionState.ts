// useSessionState.ts — useState that survives a page unmount (U3, 2026-09-24).
//
// Leaving Production or the Folder Manager unmounts the page; coming back used to
// reset it to its root. Values live in a module-level map: kept while FLUX runs,
// forgotten at restart (a stale folder path is never restored after a relaunch).

import { useCallback, useState } from 'react'

const memory = new Map<string, unknown>()

/** Last value stored under *key* this session, or undefined. */
export function readSession<T>(key: string): T | undefined {
  return memory.get(key) as T | undefined
}

export function writeSession<T>(key: string, value: T): void {
  memory.set(key, value)
}

/**
 * Like useState, but the value is remembered under *key* for the whole session.
 * The key is read at mount only: a page keyed by project remounts or resets itself.
 */
export function useSessionState<T>(key: string, initial: T | (() => T)): [T, (v: T | ((prev: T) => T)) => void] {
  const [value, setValue] = useState<T>(() => {
    if (memory.has(key)) return memory.get(key) as T
    return typeof initial === 'function' ? (initial as () => T)() : initial
  })
  const set = useCallback((v: T | ((prev: T) => T)) => {
    setValue(prev => {
      const next = typeof v === 'function' ? (v as (p: T) => T)(prev) : v
      memory.set(key, next)
      return next
    })
  }, [key])
  return [value, set]
}

/** Forget every session value whose key starts with *prefix* (a page's "Reset"). */
export function clearSession(prefix: string): void {
  for (const key of [...memory.keys()]) if (key.startsWith(prefix)) memory.delete(key)
}
