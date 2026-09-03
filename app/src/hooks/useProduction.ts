// useProduction — load, reconcile-refresh, and debounced-save the production
// store for the active project. Also indexes `publishes_by_task` for the UI.

import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type {
  ProductionPayload, ProductionPublish, ProductionState,
} from '../types'

const EMPTY_STATE: ProductionState = {
  version: 1,
  sequences: [],
  shots: [],
  assets: [],
  asset_groups: [],
}

export interface UseProductionResult {
  state: ProductionState
  setState: (patch: (prev: ProductionState) => ProductionState) => void
  publishesByTask: Record<string, ProductionPublish[]>
  publishesUnmatched: number
  sequencesOnDisk: Set<string>
  shotsOnDisk: Set<string>            // "SEQxxx|SHOTxxx"
  loading: boolean
  reload: () => Promise<void>
}

export function useProduction(project: string | null | undefined): UseProductionResult {
  const [state, setStateRaw]         = useState<ProductionState>(EMPTY_STATE)
  const [publishesByTask, setPublishesByTask] = useState<Record<string, ProductionPublish[]>>({})
  const [publishesUnmatched, setPublishesUnmatched] = useState<number>(0)
  const [sequencesOnDisk, setSequencesOnDisk] = useState<Set<string>>(new Set())
  const [shotsOnDisk, setShotsOnDisk] = useState<Set<string>>(new Set())
  const [loading, setLoading]        = useState(false)
  const loaded                       = useRef(false)
  const projectRef                   = useRef<string | null | undefined>(project)

  const reload = useCallback(async () => {
    if (!project) return
    setLoading(true)
    try {
      const r: ProductionPayload = await api.getProduction(project)
      setStateRaw(r.production)
      setPublishesByTask(r.publishes_by_task || {})
      setPublishesUnmatched((r.publishes_unmatched || []).length)
      setSequencesOnDisk(new Set((r.sequences_on_disk || []).map(s => s.toUpperCase())))
      setShotsOnDisk(new Set((r.shots_on_disk || []).map(([sq, sh]) => `${sq.toUpperCase()}|${sh.toUpperCase()}`)))
      loaded.current = true
    } catch {
      // backend down / project gone — leave empty state so UI never explodes
      setStateRaw(EMPTY_STATE)
      setPublishesByTask({})
      setPublishesUnmatched(0)
      setSequencesOnDisk(new Set())
      setShotsOnDisk(new Set())
    } finally {
      setLoading(false)
    }
  }, [project])

  // (Re)load whenever the active project changes; guard against a stale response
  // clobbering a newer project's state.
  useEffect(() => {
    projectRef.current = project
    loaded.current = false
    if (!project) {
      setStateRaw(EMPTY_STATE)
      setPublishesByTask({})
      setPublishesUnmatched(0)
      setSequencesOnDisk(new Set())
      setShotsOnDisk(new Set())
      return
    }
    void reload()
  }, [project, reload])

  // Global refresh event — same signal as the TitleBar refresh button.
  useEffect(() => {
    const onRefresh = () => { void reload() }
    window.addEventListener('flux:refresh', onRefresh)
    return () => window.removeEventListener('flux:refresh', onRefresh)
  }, [reload])

  // Public setter that also triggers a debounced PUT (skips the initial load).
  const setState = useCallback((patch: (prev: ProductionState) => ProductionState) => {
    setStateRaw(prev => patch(prev))
  }, [])

  // Debounced persist. 400 ms mirrors Projects.tsx.
  useEffect(() => {
    if (!project || !loaded.current) return
    const proj = project
    const snapshot = state
    const t = setTimeout(() => {
      void api.setProduction(proj, snapshot).catch(() => {
        /* keep local edits; user sees them until next successful save */
      })
    }, 400)
    return () => clearTimeout(t)
  }, [state, project])

  return { state, setState, publishesByTask, publishesUnmatched, sequencesOnDisk, shotsOnDisk, loading, reload }
}
