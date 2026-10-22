// FlowEditor.tsx — shell of the Flows editor (route /action-graph, 03_EDITEUR §1):
// top bar (File menu), Shelf, Network, Params. P0 (prompts/P0_editeur_lisible.md): shows the
// v1 YAML actions read-only through v1_adapter.ts; no YAML is written, no new backend route.
// Open flow: deep link /action-graph?flow=<name>, else the last flow this user opened
// (user data `flows_last_open`, USER/<user>/UserSettings), else "publish".
// View prefs (background dots, wire style) are per-viewer conveniences in localStorage.
// The old editor stays at /action-graph-legacy until P8.

import { useCallback, useEffect, useMemo, useState } from 'react'
import { ReactFlowProvider } from '@xyflow/react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { api } from '../../api/client'
import { flowsApi } from '../../api/flows'
import { NetworkPane } from './NetworkPane'
import { ParamsPane } from './ParamsPane'
import { ShelfBar } from './ShelfBar'
import { TopBar, type FlowListEntry } from './TopBar'
import type { FlowView } from './types'
import { adaptV1Action, adaptV1Catalog, type CatalogEntry } from './v1_adapter'
import { useTr } from './useTr'

const DEFAULT_FLOW = 'publish'
const LAST_OPEN_KEY = 'flows_last_open'
const PREFS_KEY = 'flux.flow_editor.view'

type ViewPrefs = { dots: boolean; straight: boolean }

function readPrefs(): ViewPrefs {
  try {
    const p = JSON.parse(localStorage.getItem(PREFS_KEY) ?? '{}')
    return { dots: p.dots !== false, straight: p.straight === true }
  } catch { return { dots: true, straight: false } }
}

function writePrefs(p: ViewPrefs): void {
  try { localStorage.setItem(PREFS_KEY, JSON.stringify(p)) } catch { /* private mode: not kept */ }
}

function Editor() {
  const { tr } = useTr()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const [flows, setFlows] = useState<FlowListEntry[]>([])
  const [current, setCurrent] = useState<string | null>(params.get('flow'))
  const [view, setView] = useState<FlowView | null>(null)
  const [catalog, setCatalog] = useState<CatalogEntry[] | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [prefs, setPrefs] = useState<ViewPrefs>(readPrefs)

  useEffect(() => {
    // v1 actions are all pipe flows; project flows come with the v2 store (P1).
    flowsApi.listV1Actions()
      .then(names => setFlows(names.map(name => ({ name, category: 'pipe' as const }))))
      .catch(() => setFlows([]))
    flowsApi.getV1Catalog().then(c => setCatalog(adaptV1Catalog(c))).catch(() => setCatalog([]))
  }, [])

  // No deep link: reopen the last flow of this user.
  useEffect(() => {
    if (current) return
    api.getUserData()
      .then(d => setCurrent(typeof d[LAST_OPEN_KEY] === 'string' && d[LAST_OPEN_KEY] ? String(d[LAST_OPEN_KEY]) : DEFAULT_FLOW))
      .catch(() => setCurrent(DEFAULT_FLOW))
  }, [current])

  // A deep link opened later in this window (Electron focuses it and changes the hash).
  useEffect(() => {
    const fromUrl = params.get('flow')
    if (fromUrl && fromUrl !== current) setCurrent(fromUrl)
  }, [params])  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!current) return
    let alive = true
    setError(null)
    setSelectedId(null)
    flowsApi.getV1Action(current)
      .then(g => { if (alive) setView(adaptV1Action(g)) })
      .catch(e => { if (alive) { setView(null); setError(String(e?.message ?? e)) } })
    return () => { alive = false }
  }, [current])

  const open = useCallback((name: string) => {
    setCurrent(name)
    setParams({ flow: name }, { replace: true })
    api.setUserData({ [LAST_OPEN_KEY]: name }).catch(() => { /* not kept: reopens the default */ })
  }, [setParams])

  const updatePrefs = useCallback((patch: Partial<ViewPrefs>) => {
    setPrefs(p => { const next = { ...p, ...patch }; writePrefs(next); return next })
  }, [])
  const toggleWires = useCallback(() => setPrefs(p => { const next = { ...p, straight: !p.straight }; writePrefs(next); return next }), [])

  const selected = useMemo(() => view?.nodes.find(n => n.id === selectedId) ?? null, [view, selectedId])
  const onSelect = useCallback((id: string | null) => setSelectedId(id), [])
  const onPick = useCallback((e: CatalogEntry) => {
    toast.info(tr(`${e.label} : l'ajout de nodes arrive avec l'edition (P4)`, `${e.label}: adding nodes comes with editing (P4)`))
  }, [tr])

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', background: 'var(--paper)' }}>
      <TopBar
        flows={flows}
        current={current ?? ''}
        origin={view?.origin}
        search={search}
        dots={prefs.dots}
        straight={prefs.straight}
        onSearch={setSearch}
        onOpen={open}
        onToggleDots={() => updatePrefs({ dots: !prefs.dots })}
        onToggleWires={toggleWires}
        onLegacy={() => navigate('/action-graph-legacy')}
      />
      <ShelfBar catalog={catalog} onPick={onPick} />
      <div style={{ flex: 1, minHeight: 0, display: 'flex' }}>
        {error
          ? <div style={{ flex: 1, padding: 20, fontSize: 12, color: 'var(--ink-3)' }}>
              {tr(`Impossible de lire "${current}" : ${error}`, `Cannot read "${current}": ${error}`)}
            </div>
          : <NetworkPane
              view={view} search={search} dots={prefs.dots} straight={prefs.straight} catalog={catalog}
              onSelect={onSelect} onPick={onPick} onToggleWires={toggleWires}
            />}
        <ParamsPane view={view} selected={selected} />
      </div>
    </div>
  )
}

export function FlowEditor() {
  return (
    <ReactFlowProvider>
      <Editor />
    </ReactFlowProvider>
  )
}
