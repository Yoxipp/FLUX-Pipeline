// useBoardHistory.ts — undo / redo local to this viewer (ADR 0071 n°4). Each entry holds the
// ops to redo and the inverse ops to undo, both written to the viewer's OWN journal: nobody
// ever cancels someone else's op. Kept in memory only (a reload empties it).

import { useCallback, useRef, useState } from 'react'
import type { PageDataOp } from '../../flow_editor/types'

export interface HistoryEntry { redo: PageDataOp[]; undo: PageDataOp[] }
const LIMIT = 100

export function useBoardHistory(write: (ops: PageDataOp[]) => Promise<string[]>) {
  const past = useRef<HistoryEntry[]>([])
  const future = useRef<HistoryEntry[]>([])
  const [, bump] = useState(0)

  const push = useCallback((entry: HistoryEntry) => {
    if (!entry.redo.length || !entry.undo.length) return
    past.current = [...past.current.slice(-(LIMIT - 1)), entry]
    future.current = []
    bump(n => n + 1)
  }, [])

  // A failed step (the object was deleted by someone else meanwhile) is dropped, not retried.
  const step = useCallback(async (from: typeof past, to: typeof past, pick: (e: HistoryEntry) => PageDataOp[]) => {
    const entry = from.current[from.current.length - 1]
    if (!entry) return
    from.current = from.current.slice(0, -1)
    bump(n => n + 1)
    await write(pick(entry))
    to.current = [...to.current, entry]
    bump(n => n + 1)
  }, [write])

  const undo = useCallback(() => step(past, future, e => e.undo), [step])
  const redo = useCallback(() => step(future, past, e => e.redo), [step])
  return { push, undo, redo, canUndo: past.current.length > 0, canRedo: future.current.length > 0 }
}
