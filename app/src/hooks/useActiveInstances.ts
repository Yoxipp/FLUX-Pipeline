// useActiveInstances.ts — per-DCC "active instance" selection (cluster C, phase 4).
//
// Multi-instance: a DCC can expose several running instances (each on its own
// port). This hook remembers which instance the user targets for each DCC, keeps
// that choice valid as instances come and go, and persists it across reloads.
// One hook for the whole status map (never one per row) so hook order is stable.

import { useCallback, useEffect, useState } from 'react'
import type { DccStatusMap } from '../types'
import { api } from '../api/client'

const LS_KEY = 'flux.activeInstance'   // { [dccStatusKey]: port }

function readMap(): Record<string, number> {
  try {
    const raw = localStorage.getItem(LS_KEY)
    return raw ? (JSON.parse(raw) as Record<string, number>) : {}
  } catch {
    return {}   // private window / blocked storage — start empty
  }
}

function writeMap(m: Record<string, number>): void {
  try { localStorage.setItem(LS_KEY, JSON.stringify(m)) } catch { /* blocked */ }
}

/**
 * Read the currently-selected instance port for a DCC without a hook or the
 * status map — for callers (Publisher, Importer) that only need to route a
 * command to the active instance. The Sidebar's useActiveInstances keeps this
 * value valid as instances change. Returns null when nothing is selected (single
 * instance), so the caller omits the port and the backend uses the base port.
 */
export function readActiveInstancePort(dccKey: string): number | null {
  try {
    const raw = localStorage.getItem(LS_KEY)
    const m = raw ? (JSON.parse(raw) as Record<string, number>) : {}
    return typeof m[dccKey] === 'number' ? m[dccKey] : null
  } catch {
    return null
  }
}

/** Store the chosen instance port of a DCC (localStorage + backend, so the Houdini
 *  client follows it). Used by the publish picker outside the sidebar hook. */
export function writeActiveInstancePort(dccKey: string, port: number): void {
  writeMap({ ...readMap(), [dccKey]: port })
  void api.setActiveInstance(dccKey, port).catch(() => { /* backend down: next push */ })
}

export interface ActiveInstances {
  /** port currently targeted for a DCC, or null when it has no instance up. */
  activePort: (dccKey: string) => number | null
  /** choose the active instance port for a DCC. */
  setActivePort: (dccKey: string, port: number) => void
}

export function useActiveInstances(status: DccStatusMap): ActiveInstances {
  const [map, setMap] = useState<Record<string, number>>(readMap)

  // Reconcile the stored choice against what is actually running: if the chosen
  // port disappeared (instance closed) or none was chosen, fall back to the
  // lowest open instance. Runs each status tick but only writes when it changes,
  // so it never loops. `status` is a fresh object every WS message, hence the dep.
  useEffect(() => {
    let changed = false
    const next = { ...map }
    for (const [dccKey, entry] of Object.entries(status)) {
      const insts = entry.instances ?? []
      if (insts.length === 0) continue
      const cur = next[dccKey]
      if (cur == null || !insts.some((i) => i.port === cur)) {
        next[dccKey] = insts[0].port   // instances are sorted ascending by port
        changed = true
      }
    }
    if (changed) {
      setMap(next)
      writeMap(next)
    }
  }, [status])   // eslint-disable-line react-hooks/exhaustive-deps

  const activePort = useCallback(
    (dccKey: string): number | null => {
      const insts = status[dccKey]?.instances ?? []
      if (insts.length === 0) return null
      const cur = map[dccKey]
      return cur != null && insts.some((i) => i.port === cur) ? cur : insts[0].port
    },
    [status, map],
  )

  // The backend keeps the choice in memory (restart = base port): push it on every
  // change, and once on mount.
  useEffect(() => {
    for (const [dccKey, port] of Object.entries(map)) {
      void api.setActiveInstance(dccKey, port).catch(() => { /* backend down */ })
    }
  }, [map])

  const setActivePort = useCallback((dccKey: string, port: number) => {
    setMap((prev) => {
      const nextMap = { ...prev, [dccKey]: port }
      writeMap(nextMap)
      return nextMap
    })
  }, [])

  return { activePort, setActivePort }
}
