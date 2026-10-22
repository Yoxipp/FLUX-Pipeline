// FlowEditor.tsx — shell of the Flows editor (route /action-graph, 03_EDITEUR §1):
// top bar, Shelf, Network, Params. P0 (prompts/P0_editeur_lisible.md): shows the v1 YAML
// actions read-only through v1_adapter.ts; no YAML is written, no new backend route.
// Deep link: /action-graph?flow=<name>. The old editor stays at /action-graph-legacy until P8.

import { useCallback, useEffect, useMemo, useState } from 'react'
import { ReactFlowProvider, useReactFlow } from '@xyflow/react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { flowsApi } from '../../api/flows'
import { NetworkPane } from './NetworkPane'
import { ParamsPane } from './ParamsPane'
import { ShelfBar } from './ShelfBar'
import { TopBar } from './TopBar'
import type { FlowView } from './types'
import { adaptV1Action, adaptV1Catalog, type CatalogEntry } from './v1_adapter'
import { useTr } from './useTr'

const DEFAULT_FLOW = 'publish'

function Editor() {
  const { tr } = useTr()
  const navigate = useNavigate()
  const { fitView } = useReactFlow()
  const [params, setParams] = useSearchParams()
  const [flows, setFlows] = useState<string[]>([])
  const [view, setView] = useState<FlowView | null>(null)
  const [catalog, setCatalog] = useState<CatalogEntry[] | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [error, setError] = useState<string | null>(null)
  const current = params.get('flow') || DEFAULT_FLOW

  useEffect(() => {
    flowsApi.listV1Actions().then(setFlows).catch(() => setFlows([]))
    flowsApi.getV1Catalog().then(c => setCatalog(adaptV1Catalog(c))).catch(() => setCatalog([]))
  }, [])

  useEffect(() => {
    let alive = true
    setError(null)
    setSelectedId(null)
    flowsApi.getV1Action(current)
      .then(g => { if (alive) setView(adaptV1Action(g)) })
      .catch(e => { if (alive) { setView(null); setError(String(e?.message ?? e)) } })
    return () => { alive = false }
  }, [current])

  const selected = useMemo(() => view?.nodes.find(n => n.id === selectedId) ?? null, [view, selectedId])
  const onSelect = useCallback((id: string | null) => setSelectedId(id), [])
  const onPick = useCallback((e: CatalogEntry) => {
    toast.info(tr(`${e.label} : l'ajout de nodes arrive avec l'edition (phase P4)`, `${e.label}: adding nodes comes with editing (phase P4)`))
  }, [tr])

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', background: 'var(--paper)' }}>
      <TopBar
        flows={flows}
        current={current}
        origin={view?.origin}
        search={search}
        onSearch={setSearch}
        onChoose={name => setParams({ flow: name }, { replace: true })}
        onFrame={() => fitView({ padding: 0.15 })}
        onLegacy={() => navigate('/action-graph-legacy')}
      />
      <ShelfBar catalog={catalog} onPick={onPick} />
      <div style={{ flex: 1, minHeight: 0, display: 'flex' }}>
        {error
          ? <div style={{ flex: 1, padding: 20, fontSize: 12, color: 'var(--ink-3)' }}>
              {tr(`Impossible de lire "${current}" : ${error}`, `Cannot read "${current}": ${error}`)}
            </div>
          : <NetworkPane view={view} search={search} catalog={catalog} onSelect={onSelect} onPick={onPick} />}
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
