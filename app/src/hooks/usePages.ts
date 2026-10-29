// usePages.ts — TOOL pages hooks (P7, ADR 0066).
// usePageList: the pages of team + project (TOOL tab, sidebar entry), reread on WS page_changed.
// usePageData: the records of one collection. Writes of this machine arrive by WS page_data;
// the other machines write in their own journal on the share, seen by a conditional read
// (etag) every 5 s while the widget is mounted (ADR 0066 n°4): an unchanged etag costs a stat.

import { useCallback, useEffect, useRef, useState } from 'react'
import { flowsApi } from '../api/flows'
import type { FlowsWsMessage, PageDataOp, PageList, PageRecord } from '../pages/flow_editor/types'
import { useFlowsWs } from './useFlowsWs'

const DATA_REFRESH_MS = 5000

export function usePageList(project: string | null | undefined) {
  const [list, setList] = useState<PageList | null>(null)
  const [error, setError] = useState<string | null>(null)
  const reload = useCallback(() => {
    flowsApi.listPages(project || undefined)
      .then(l => { setList(l); setError(null) })
      .catch(err => setError((err as Error).message))
  }, [project])
  useEffect(() => { reload() }, [reload])
  useFlowsWs(useCallback((msg: FlowsWsMessage) => { if (msg.type === 'page_changed') reload() }, [reload]), reload)
  return { list, error, reload }
}

export interface PageData {
  records: PageRecord[]
  loaded: boolean
  error: string | null
  canWrite: boolean
  me: string | null
  write: (ops: PageDataOp[]) => Promise<string[]>
  put: (fields: Record<string, unknown>, rid?: string) => Promise<string | undefined>
  del: (rid: string) => Promise<void>
}

export function usePageData(page: string, collection: string, project: string | null | undefined, enabled = true): PageData {
  const [records, setRecords] = useState<PageRecord[]>([])
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [mode, setMode] = useState<'all' | 'team_td'>('all')
  const [rights, setRights] = useState<{ user: string | null; team_td: boolean } | null>(null)
  const etag = useRef<string | undefined>(undefined)

  const refresh = useCallback(() => {
    if (!enabled) return
    flowsApi.pageData(page, collection, { project: project || undefined, etag: etag.current })
      .then(r => {
        etag.current = r.etag
        if (r.write) setMode(r.write)
        if (!r.unchanged) setRecords(r.records)
        setLoaded(true)
        setError(null)
      })
      .catch(err => { setError((err as Error).message); setLoaded(true) })
  }, [page, collection, project, enabled])

  useEffect(() => {
    etag.current = undefined
    setRecords([])
    setLoaded(false)
    refresh()
    if (!enabled) return
    const t = setInterval(refresh, DATA_REFRESH_MS)
    return () => clearInterval(t)
  }, [refresh, enabled])

  useEffect(() => {
    flowsApi.getRights().then(r => setRights({ user: r.user ?? null, team_td: !!r.team_td })).catch(() => setRights(null))
  }, [])

  useFlowsWs(useCallback((msg: FlowsWsMessage) => {
    if (msg.type === 'page_data' && msg.page === page && msg.collection === collection && msg.etag !== etag.current) refresh()
  }, [page, collection, refresh]), refresh)

  const write = useCallback(async (ops: PageDataOp[]) => {
    const r = await flowsApi.writePageData(page, collection, ops, project || undefined)
    refresh()
    return r.rids
  }, [page, collection, project, refresh])

  const put = useCallback(async (fields: Record<string, unknown>, rid?: string) => {
    // Optimistic: the record moves at once (a board drag must not jump back for a round trip).
    if (rid) setRecords(rs => rs.map(r => r.rid === rid ? { ...r, ...fields } : r))
    const rids = await write([rid ? { op: 'put', rid, fields } : { op: 'put', fields }])
    return rids[0]
  }, [write])

  const del = useCallback(async (rid: string) => {
    setRecords(rs => rs.filter(r => r.rid !== rid))
    await write([{ op: 'del', rid }])
  }, [write])

  return { records, loaded, error, canWrite: mode === 'all' || !!rights?.team_td, me: rights?.user ?? null, write, put, del }
}
