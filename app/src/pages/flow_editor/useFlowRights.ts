// useFlowRights.ts — TD / Team TD boxes of the current user (GET /flows/rights, 01 §7).
// undefined while loading, null when the backend could not answer. Re-read when a box
// changes in Settings > User (FLOW_RIGHTS_EVENT). A guard, not security: the backend
// refuses too.

import { useEffect, useState } from 'react'
import { FLOW_RIGHTS_EVENT, flowsApi } from '../../api/flows'
import type { FlowRights } from './types'

export function useFlowRights(): FlowRights | null | undefined {
  const [rights, setRights] = useState<FlowRights | null | undefined>(undefined)
  useEffect(() => {
    let alive = true
    const load = () => { flowsApi.getRights().then(r => { if (alive) setRights(r) }).catch(() => { if (alive) setRights(null) }) }
    load()
    window.addEventListener(FLOW_RIGHTS_EVENT, load)
    return () => { alive = false; window.removeEventListener(FLOW_RIGHTS_EVENT, load) }
  }, [])
  return rights
}
