// useActiveInstances.ts — per-DCC "active instance" selection (cluster C, phase 4).
//
// Multi-instance: a DCC can expose several running instances (each on its own
// port). This hook remembers which instance the user targets for each DCC, keeps
// that choice valid as instances come and go, and persists it across reloads.
// One hook for the whole status map (never one per row) so hook order is stable.
//
// A1 (2026-09-27): the choice is (port, pid). A port taken back by another process
// (the chosen Houdini closed, a new one opened) is NOT the chosen instance: with one
// instance left FLUX switches to it and says so, with several it asks.

import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import type { DccStatusMap } from '../types'
import { api } from '../api/client'

const LS_KEY = 'flux.activeInstance'   // { [dccStatusKey]: {port, pid} } (old: port only)

export interface ActiveChoice { port: number; pid: number | null }

function normalize(v: unknown): ActiveChoice | null {
  if (typeof v === 'number') return { port: v, pid: null }          // stored before A1
  if (v && typeof v === 'object' && typeof (v as ActiveChoice).port === 'number') {
    const c = v as ActiveChoice
    return { port: c.port, pid: typeof c.pid === 'number' ? c.pid : null }
  }
  return null
}

function readMap(): Record<string, ActiveChoice> {
  try {
    const raw = localStorage.getItem(LS_KEY)
    const m = raw ? (JSON.parse(raw) as Record<string, unknown>) : {}
    const out: Record<string, ActiveChoice> = {}
    for (const [k, v] of Object.entries(m)) {
      const c = normalize(v)
      if (c) out[k] = c
    }
    return out
  } catch {
    return {}   // private window / blocked storage — start empty
  }
}

function writeMap(m: Record<string, ActiveChoice>): void {
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
  return readMap()[dccKey]?.port ?? null
}

/** The chosen instance of a DCC with the process it was chosen on. */
export function readActiveInstance(dccKey: string): ActiveChoice | null {
  return readMap()[dccKey] ?? null
}

/** Store the chosen instance of a DCC (localStorage + backend, so the Houdini
 *  client follows it). Used by the publish picker outside the sidebar hook. */
export function writeActiveInstancePort(dccKey: string, port: number, pid: number | null = null): void {
  writeMap({ ...readMap(), [dccKey]: { port, pid } })
  void api.setActiveInstance(dccKey, port, pid).catch(() => { /* backend down: next push */ })
}

export interface ActiveInstances {
  /** port currently targeted for a DCC, or null when it has no instance up. */
  activePort: (dccKey: string) => number | null
  /** choose the active instance port for a DCC. */
  setActivePort: (dccKey: string, port: number) => void
}

export function useActiveInstances(status: DccStatusMap): ActiveInstances {
  const [map, setMap] = useState<Record<string, ActiveChoice>>(readMap)
  // One warning per lost choice, not one per status tick.
  const warned = useRef<Record<string, string>>({})

  // Reconcile the stored choice against what is actually running: a chosen port gone
  // or held by another pid is a closed instance. One instance left: take it (said);
  // several: keep none chosen, the Publisher asks before publishing.
  useEffect(() => {
    let changed = false
    const next = { ...map }
    for (const [dccKey, entry] of Object.entries(status)) {
      const insts = entry.instances ?? []
      if (insts.length === 0) continue
      const cur = next[dccKey]
      const same = cur ? insts.find((i) => i.port === cur.port) : undefined
      const gone = !!cur && (!same || (cur.pid != null && same.pid != null && same.pid !== cur.pid))
      if (cur && same && !gone && cur.pid == null && same.pid != null) {
        next[dccKey] = { port: cur.port, pid: same.pid }           // learn the pid of an old choice
        changed = true
        continue
      }
      if (cur && !gone) continue
      if (gone) {
        const key = `${cur!.port}:${cur!.pid}`
        if (warned.current[dccKey] !== key) {
          warned.current[dccKey] = key
          if (insts.length === 1) {
            toast.warning(`${dccKey} choisi (port ${cur!.port}) ferme : FLUX travaille maintenant avec ${insts[0].label}`)
          } else {
            toast.warning(`${dccKey} choisi (port ${cur!.port}) ferme : ${insts.length} autres ouverts, choisis celui qui travaille`)
          }
        }
        if (insts.length > 1) {
          delete next[dccKey]
          changed = true
          continue
        }
      }
      next[dccKey] = { port: insts[0].port, pid: insts[0].pid ?? null }   // sorted ascending by port
      changed = true
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
      return cur != null && insts.some((i) => i.port === cur.port) ? cur.port : insts[0].port
    },
    [status, map],
  )

  // The backend keeps the choice in memory (restart = base port): push it on every
  // change, and once on mount.
  useEffect(() => {
    for (const [dccKey, c] of Object.entries(map)) {
      void api.setActiveInstance(dccKey, c.port, c.pid).catch(() => { /* backend down */ })
    }
  }, [map])

  const setActivePort = useCallback((dccKey: string, port: number) => {
    const pid = status[dccKey]?.instances?.find((i) => i.port === port)?.pid ?? null
    setMap((prev) => {
      const nextMap = { ...prev, [dccKey]: { port, pid } }
      writeMap(nextMap)
      return nextMap
    })
  }, [status])

  return { activePort, setActivePort }
}
