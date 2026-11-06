// activeInstance.ts: which running instance of a DCC FLUX works with (pure rules).
//
// 2026-11-06: one instance connects alone; with several the choice is made in the
// launcher and FLUX never guesses. A choice is (port, pid): a port taken back by another
// process is a closed instance (A1). A DCC the user disconnected is left alone until it
// is chosen again or all its instances are closed.

export interface ActiveChoice { port: number; pid: number | null }

export interface InstanceLite { port: number; pid?: number | null; label?: string }

export type Choices = Record<string, ActiveChoice>

/** The chosen instance closed: `taken` is the one FLUX moved to, null when several remain. */
export interface LostChoice { dcc: string; lost: ActiveChoice; taken: InstanceLite | null; remaining: number }

export interface Reconciled {
  choices: Choices
  disconnected: Record<string, boolean>
  changed: boolean
  lost: LostChoice[]
}

export function reconcileChoices(
  current: Choices,
  status: Record<string, { instances?: InstanceLite[] }>,
  disconnected: Record<string, boolean>,
): Reconciled {
  const choices = { ...current }
  const nextDisconnected = { ...disconnected }
  const lost: LostChoice[] = []
  let changed = false
  for (const [dcc, entry] of Object.entries(status)) {
    const insts = entry.instances ?? []
    if (insts.length === 0) {
      // Everything closed: the next launch connects again.
      if (nextDisconnected[dcc]) { delete nextDisconnected[dcc]; changed = true }
      continue
    }
    if (nextDisconnected[dcc]) continue
    const cur = choices[dcc]
    const same = cur ? insts.find(i => i.port === cur.port) : undefined
    const gone = !!cur && (!same || (cur.pid != null && same.pid != null && same.pid !== cur.pid))
    if (cur && !gone) {
      if (cur.pid == null && same?.pid != null) {        // learn the pid of an old choice
        choices[dcc] = { port: cur.port, pid: same.pid }
        changed = true
      }
      continue
    }
    const only = insts.length === 1 ? insts[0] : null
    if (gone) lost.push({ dcc, lost: cur!, taken: only, remaining: insts.length })
    if (only) {
      choices[dcc] = { port: only.port, pid: only.pid ?? null }
      changed = true
    } else if (cur) {
      delete choices[dcc]                                // several: the launcher decides
      changed = true
    }
  }
  return { choices, disconnected: nextDisconnected, changed, lost }
}

/** Port FLUX targets now: the valid choice, else the only instance, else none. */
export function targetPort(
  dcc: string, choices: Choices, insts: InstanceLite[], disconnected: Record<string, boolean>,
): number | null {
  if (disconnected[dcc] || insts.length === 0) return null
  const cur = choices[dcc]
  if (cur && insts.some(i => i.port === cur.port)) return cur.port
  return insts.length === 1 ? insts[0].port : null
}
