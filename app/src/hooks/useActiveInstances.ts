// useActiveInstances.ts — per-DCC "active instance" selection (cluster C, phase 4).
//
// Multi-instance: a DCC can expose several running instances (each on its own
// port). This hook remembers which instance the user targets for each DCC, keeps
// that choice valid as instances come and go, and persists it across reloads.
// One hook for the whole status map (never one per row) so hook order is stable.
//
// Rules (pure, tested) in lib/activeInstance.ts: one instance connects alone, with several
// the choice is made in the launcher (2026-11-06).

import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import type { DccStatusMap } from '../types'
import { api } from '../api/client'
import { reconcileChoices, targetPort, type ActiveChoice, type Choices } from '../lib/activeInstance'

const LS_KEY = 'flux.activeInstance'   // { [dccStatusKey]: {port, pid} } (old: port only)
const LS_OFF_KEY = 'flux.disconnectedInstances'   // { [dccStatusKey]: true }

export type { ActiveChoice }

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

function readOff(): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(LS_OFF_KEY)
    return raw ? (JSON.parse(raw) as Record<string, boolean>) : {}
  } catch {
    return {}
  }
}

function writeOff(m: Record<string, boolean>): void {
  try { localStorage.setItem(LS_OFF_KEY, JSON.stringify(m)) } catch { /* blocked */ }
}

/** True when the user disconnected this DCC from FLUX in the launcher. */
export function isInstanceDisconnected(dccKey: string): boolean {
  return !!readOff()[dccKey]
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
 *  client follows it). Used by the Publisher outside the sidebar hook. */
export function writeActiveInstancePort(dccKey: string, port: number, pid: number | null = null): void {
  writeMap({ ...readMap(), [dccKey]: { port, pid } })
  void api.setActiveInstance(dccKey, port, pid).catch(() => { /* backend down: next push */ })
}

export interface ActiveInstances {
  /** port currently targeted for a DCC, or null when none is (none up, several without a choice, disconnected). */
  activePort: (dccKey: string) => number | null
  /** choose the active instance port for a DCC (reconnects it). */
  setActivePort: (dccKey: string, port: number) => void
  /** stop working with this DCC until it is chosen again. Does not close it. */
  disconnect: (dccKey: string) => void
  isDisconnected: (dccKey: string) => boolean
}

export function useActiveInstances(status: DccStatusMap): ActiveInstances {
  const [map, setMap] = useState<Choices>(readMap)
  const [off, setOff] = useState<Record<string, boolean>>(readOff)
  // One warning per lost choice, not one per status tick.
  const warned = useRef<Record<string, string>>({})

  // Reconcile the stored choices against what is actually running.
  useEffect(() => {
    const r = reconcileChoices(map, status, off)
    for (const l of r.lost) {
      const key = `${l.lost.port}:${l.lost.pid}`
      if (warned.current[l.dcc] === key) continue
      warned.current[l.dcc] = key
      toast.warning(l.taken
        ? `${l.dcc} choisi (port ${l.lost.port}) fermé : FLUX travaille maintenant avec ${l.taken.label ?? `le port ${l.taken.port}`}`
        : `${l.dcc} choisi (port ${l.lost.port}) fermé : ${l.remaining} autres ouverts, choisis celui qui travaille dans le launcher`)
    }
    if (r.changed) {
      setMap(r.choices)
      writeMap(r.choices)
      setOff(r.disconnected)
      writeOff(r.disconnected)
    }
  }, [status])   // eslint-disable-line react-hooks/exhaustive-deps

  const activePort = useCallback(
    (dccKey: string): number | null => targetPort(dccKey, map, status[dccKey]?.instances ?? [], off),
    [status, map, off],
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
    setOff((prev) => {
      const next = { ...prev }
      delete next[dccKey]
      writeOff(next)
      return next
    })
  }, [status])

  const disconnect = useCallback((dccKey: string) => {
    setMap((prev) => {
      const nextMap = { ...prev }
      delete nextMap[dccKey]
      writeMap(nextMap)
      return nextMap
    })
    setOff((prev) => {
      const next = { ...prev, [dccKey]: true }
      writeOff(next)
      return next
    })
    void api.setActiveInstance(dccKey, null).catch(() => { /* backend down */ })
  }, [])

  const isDisconnected = useCallback((dccKey: string) => !!off[dccKey], [off])

  return { activePort, setActivePort, disconnect, isDisconnected }
}
