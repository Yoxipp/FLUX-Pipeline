// FlowEditor.tsx — shell of the Flows editor (route /action-graph, 03_EDITEUR §1):
// top bar (File menu), Shelf, Network, Params. P1: reads v2 flows from the store
// (GET /flows, /flows/{name}) through v2_adapter.ts; the File menu writes through the
// /flows routes (ADR 0058: Save overwrites, Save and increment freezes vNNN). The graph
// itself stays read-only until P4. The Shelf still lists the v1 commands (catalogue P2).
// Open flow: deep link /action-graph?flow=<name>, else the last flow this user opened
// (user data `flows_last_open`, USER/<user>/UserSettings), else "legacy_publish".
// A v1 name kept from P0 ("publish") opens its legacy_ flow.
// View prefs (background dots, wire style) are per-viewer conveniences in localStorage.
// The old editor stays at /action-graph-legacy until P8.
// P2 (03_EDITEUR §7): Run = the open document (POST /flows/{name}/run with draft, TD), Essai =
// dry run of the saved file; node states arrive by WS /flows/ws (useFlowsWs) and are reread
// from GET /flows/runs/{id} after a reconnection; Notify nodes show a toast; the Runs dock lists
// the history and colours the graph with an opened run.
// Entry needs the TD box (flows_td, 01 §7): without it the route shows "Acces refuse".

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ReactFlowProvider } from '@xyflow/react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { api } from '../../api/client'
import { flowsApi } from '../../api/flows'
import { useFlowsWs } from '../../hooks/useFlowsWs'
import { useProject } from '../../ProjectContext'
import { MigrateDialog, NameDialog, scopeChoices } from './FileDialogs'
import { NetworkPane } from './NetworkPane'
import { ParamsPane } from './ParamsPane'
import { RunsPanel } from './RunsPanel'
import { ShelfBar } from './ShelfBar'
import { TopBar, type FlowListEntry } from './TopBar'
import type { FlowDoc, FlowRead, FlowRights, FlowScope, FlowsWsMessage, MigrateReport, NodeRunInfo, RunIssue, RunRecord } from './types'
import { adaptV1Catalog, type CatalogEntry } from './v1_adapter'
import { adaptV2Flow } from './v2_adapter'
import { useTr } from './useTr'
import { useFlowRights } from './useFlowRights'

const DEFAULT_FLOW = 'legacy_publish'
const LEGACY_PREFIX = 'legacy_'
const LAST_OPEN_KEY = 'flows_last_open'
const PREFS_KEY = 'flux.flow_editor.view'

type ViewPrefs = { dots: boolean; straight: boolean }
type HttpError = Error & { status?: number; detail?: { by?: string; at?: string; status?: string; issues?: RunIssue[] } }
type RunStates = Record<string, NodeRunInfo>

function readPrefs(): ViewPrefs {
  try {
    const p = JSON.parse(localStorage.getItem(PREFS_KEY) ?? '{}')
    return { dots: p.dots !== false, straight: p.straight === true }
  } catch { return { dots: true, straight: false } }
}

function writePrefs(p: ViewPrefs): void {
  try { localStorage.setItem(PREFS_KEY, JSON.stringify(p)) } catch { /* private mode: not kept */ }
}

function Editor({ rights }: { rights: FlowRights }) {
  const { tr } = useTr()
  const navigate = useNavigate()
  const { project } = useProject()
  const [params, setParams] = useSearchParams()
  const [flows, setFlows] = useState<FlowListEntry[]>([])
  const [current, setCurrent] = useState<string | null>(params.get('flow'))
  const [wantedScope, setWantedScope] = useState<FlowScope | undefined>((params.get('scope') as FlowScope) || undefined)
  const [loaded, setLoaded] = useState<FlowRead | null>(null)
  const [catalog, setCatalog] = useState<CatalogEntry[] | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [prefs, setPrefs] = useState<ViewPrefs>(readPrefs)
  const [dialog, setDialog] = useState<'new' | 'saveas' | null>(null)
  const [migration, setMigration] = useState<MigrateReport | null>(null)
  const [busy, setBusy] = useState(false)
  // Runs: the run launched from this window (live), the node states shown, the Runs dock.
  const [liveRun, setLiveRun] = useState<{ id: string; running: boolean } | null>(null)
  const [runStates, setRunStates] = useState<RunStates>({})
  const [runsOpen, setRunsOpen] = useState(false)
  const [openRunId, setOpenRunId] = useState<string | null>(null)
  const [runsKey, setRunsKey] = useState(0)
  const runBuf = useRef<Record<string, RunStates>>({})   // states per run_id, also before POST answers
  const liveRef = useRef<string | null>(null)

  const refreshList = useCallback(() => {
    flowsApi.list(project || undefined)
      .then(list => setFlows(list.map(f => ({ name: f.name, scope: f.scope, category: f.category, legacy: f.legacy, shadowed: f.shadowed }))))
      .catch(() => setFlows([]))
  }, [project])

  useEffect(() => { refreshList() }, [refreshList])
  useEffect(() => {
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
    if (fromUrl && fromUrl !== current) { setCurrent(fromUrl); setWantedScope((params.get('scope') as FlowScope) || undefined) }
  }, [params])  // eslint-disable-line react-hooks/exhaustive-deps

  const load = useCallback(async (name: string, scope?: FlowScope): Promise<FlowRead> => {
    try {
      return await flowsApi.get(name, { scope, project: project || undefined })
    } catch (e) {
      // P0 kept v1 action names: "publish" is now the shipped flow "legacy_publish".
      if ((e as HttpError).status === 404 && !scope && !name.startsWith(LEGACY_PREFIX)) {
        return flowsApi.get(LEGACY_PREFIX + name, { project: project || undefined })
      }
      throw e
    }
  }, [project])

  useEffect(() => {
    if (!current) return
    let alive = true
    setError(null)
    setSelectedId(null)
    load(current, wantedScope)
      .then(r => { if (alive) setLoaded(r) })
      .catch(e => { if (alive) { setLoaded(null); setError(String(e?.message ?? e)) } })
    return () => { alive = false }
  }, [current, wantedScope, load])

  const open = useCallback((name: string, scope?: FlowScope) => {
    setCurrent(name)
    setWantedScope(scope)
    setParams(scope ? { flow: name, scope } : { flow: name }, { replace: true })
    api.setUserData({ [LAST_OPEN_KEY]: name }).catch(() => { /* not kept: reopens the default */ })
  }, [setParams])

  const reload = useCallback(() => {
    if (!loaded) return
    refreshList()
    load(loaded.name, loaded.scope).then(setLoaded).catch(() => { /* keeps the last view */ })
  }, [loaded, load, refreshList])

  const view = useMemo(() => loaded ? adaptV2Flow(loaded.flow, { readOnly: true, origin: loaded.scope }) : null, [loaded])

  // Why Save / Increment are greyed for the open flow (null = allowed).
  const saveBlocked = !loaded ? tr('Aucun flow ouvert', 'No open flow')
    : loaded.scope === 'shipped' ? tr('Flow livre en lecture seule : Enregistrer sous en equipe', 'Shipped flow is read-only: Save as to team')
    : loaded.version !== null ? tr('Version figee ouverte : lecture seule', 'Frozen version open: read-only')
    : !rights.can[loaded.scope]?.write ? (loaded.scope === 'perso' ? tr('Case TD requise', 'TD box required') : tr('Case Team TD requise', 'Team TD box required'))
    : undefined

  const conflict = (e: HttpError, retry: () => void) => {
    if (e.status !== 409) { toast.error(e.message); return }
    const who = e.detail?.by ? tr(` par ${e.detail.by}`, ` by ${e.detail.by}`) : ''
    toast.warning(tr(`Enregistre entre-temps${who}.`, `Saved in the meantime${who}.`), {
      action: { label: tr('Ecraser', 'Overwrite'), onClick: retry }, duration: 10000,
    })
  }

  const save = useCallback((force = false) => {
    if (!loaded || saveBlocked) return
    flowsApi.save(loaded.flow, loaded.scope, { project: project || undefined, base_revision: loaded.state.revision, force })
      .then(() => { toast.success(tr('Enregistre', 'Saved')); reload() })
      .catch(e => conflict(e, () => save(true)))
  }, [loaded, saveBlocked, project, reload])  // eslint-disable-line react-hooks/exhaustive-deps

  const increment = useCallback((force = false) => {
    if (!loaded || saveBlocked) return
    flowsApi.increment(loaded.name, loaded.scope, loaded.flow, { project: project || undefined, base_revision: loaded.state.revision, force })
      .then(r => {
        toast.success(r.created
          ? tr(`Version v${String(r.created).padStart(3, '0')} figee`, `Version v${String(r.created).padStart(3, '0')} frozen`)
          : tr('Contenu identique a la derniere version : rien de fige', 'Same content as the last version: nothing frozen'))
        reload()
      })
      .catch(e => conflict(e, () => increment(true)))
  }, [loaded, saveBlocked, project, reload])  // eslint-disable-line react-hooks/exhaustive-deps

  const create = useCallback((name: string, scope: FlowScope) => {
    // Nouveau: an empty flow headed by event.manual. Enregistrer sous: the open document renamed.
    const doc: FlowDoc = dialog === 'saveas' && loaded
      ? { ...loaded.flow, name }
      : { flux_flow: 2, name, label: name, nodes: { n1: { type: 'event.manual', pos: [0, 0], params: {} } }, links: [] }
    flowsApi.save(doc, scope, { project: project || undefined })
      .then(() => { setDialog(null); refreshList(); open(name, scope); toast.success(tr(`${name} cree`, `${name} created`)) })
      .catch((e: HttpError) => toast.error(e.status === 409 ? tr('Un flow de ce nom existe deja dans cette categorie', 'A flow with this name already exists there') : e.message))
  }, [dialog, loaded, project, refreshList, open, tr])

  const migrate = useCallback((dryRun: boolean) => {
    setBusy(true)
    flowsApi.migrate(dryRun)
      .then(r => { setMigration(r); if (!dryRun) refreshList() })
      .catch((e: Error) => toast.error(e.message))
      .finally(() => setBusy(false))
  }, [refreshList])

  const showLive = useCallback((id: string) => {
    liveRef.current = id
    setOpenRunId(null)
    setRunStates({ ...(runBuf.current[id] ?? {}) })
  }, [])

  const onWs = useCallback((msg: FlowsWsMessage) => {
    if (msg.type === 'hello') return
    if (msg.type === 'notify') {
      const text = `${msg.flow} : ${msg.text}`
      if (msg.level === 'error') toast.error(text)
      else if (msg.level === 'warn') toast.warning(text)
      else toast.info(text)
      return
    }
    if (msg.type === 'node_state') {
      const buf = (runBuf.current[msg.run_id] ??= {})
      buf[msg.node] = { ...buf[msg.node], state: msg.state, started: msg.started, ended: msg.ended, count: msg.count,
                        ...(msg.error ? { error: msg.error } : {}) }
      if (msg.run_id === liveRef.current) setRunStates({ ...buf })
      return
    }
    if (msg.type === 'run_finished' && msg.run_id === liveRef.current) {
      setLiveRun(r => r && r.id === msg.run_id ? { ...r, running: false } : r)
      setRunsKey(k => k + 1)
      // The record has the values received of a failed node: reread it once.
      flowsApi.getRun(msg.run_id, project || undefined).then(r => setRunStates(r.nodes)).catch(() => { /* WS states stay */ })
      const secs = msg.duration_ms !== null ? ` (${(msg.duration_ms / 1000).toFixed(1)} s)` : ''
      const what = msg.mode === 'dry' ? tr('Essai a blanc', 'Dry run') : 'Run'
      if (msg.status === 'ok') toast.success(tr(`${what} fini${secs}`, `${what} done${secs}`))
      else if (msg.status === 'cancelled') toast.info(tr(`${what} annule`, `${what} cancelled`))
      else toast.error(`${what} : ${msg.error ?? msg.status}`)
    }
  }, [project, tr])

  const onWsReconnect = useCallback(() => {
    const id = liveRef.current
    if (!id) return
    flowsApi.getRun(id, project || undefined).then(r => {
      setRunStates(r.nodes)
      setLiveRun(cur => cur && cur.id === id ? { ...cur, running: r.status === 'queued' || r.status === 'running' } : cur)
    }).catch(() => { /* run of a restarted backend: interrupted */ })
  }, [project])

  const wsUp = useFlowsWs(onWs, onWsReconnect)

  const launch = useCallback((dry: boolean) => {
    if (!loaded) return
    const opts = dry
      ? { scope: loaded.scope, project: project || undefined, dry_run: true }
      : { scope: loaded.scope, project: project || undefined, draft: loaded.flow, base_revision: loaded.state.revision }
    flowsApi.run(loaded.name, opts)
      .then(r => { setLiveRun({ id: r.run_id, running: true }); showLive(r.run_id) })
      .catch((e: HttpError) => {
        const first = e.detail?.issues?.[0]
        toast.error(first ? `${e.message} : ${first.message_fr}` : e.message)
        if (e.detail?.status) setRunsKey(k => k + 1)
      })
  }, [loaded, project, showLive])

  const stop = useCallback(() => {
    if (!liveRun) return
    flowsApi.cancelRun(liveRun.id, project || undefined).catch((e: Error) => toast.error(e.message))
  }, [liveRun, project])

  const openRecord = useCallback((r: RunRecord | null) => {
    if (r) setRunStates(r.nodes)
    else if (liveRef.current) setRunStates({ ...(runBuf.current[liveRef.current] ?? {}) })
    else setRunStates({})
  }, [])

  // A new flow opened: no run states from the previous one.
  useEffect(() => { liveRef.current = null; setLiveRun(null); setRunStates({}); setOpenRunId(null) }, [loaded?.name, loaded?.scope])

  const running = !!liveRun?.running
  const runBlocked = !loaded ? tr('Aucun flow ouvert', 'No open flow')
    : !rights.can[loaded.scope]?.draft ? tr('Case TD requise', 'TD box required')
    : !wsUp ? tr('Backend injoignable', 'Backend unreachable')
    : undefined
  const dryBlocked = runBlocked ?? (loaded?.version !== null ? tr('Version figee ouverte : ouvre le fichier de travail', 'Frozen version open: open the working file') : undefined)

  // Shortcuts of the File menu (Shift+S alone toggles the wires, NetworkPane).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const k = e.key.toLowerCase()
      const ctrl = e.ctrlKey || e.metaKey
      if (ctrl && !e.shiftKey && k === 'n') { e.preventDefault(); setDialog('new') }
      else if (ctrl && e.shiftKey && k === 's') { e.preventDefault(); if (loaded) setDialog('saveas') }
      else if (ctrl && !e.shiftKey && k === 's') { e.preventDefault(); save() }
      else if (e.altKey && e.shiftKey && k === 's') { e.preventDefault(); increment() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [loaded, save, increment])

  const updatePrefs = useCallback((patch: Partial<ViewPrefs>) => {
    setPrefs(p => { const next = { ...p, ...patch }; writePrefs(next); return next })
  }, [])
  const toggleWires = useCallback(() => setPrefs(p => { const next = { ...p, straight: !p.straight }; writePrefs(next); return next }), [])

  const selected = useMemo(() => view?.nodes.find(n => n.id === selectedId) ?? null, [view, selectedId])
  const onSelect = useCallback((id: string | null) => setSelectedId(id), [])
  const onPick = useCallback((e: CatalogEntry) => {
    toast.info(tr(`${e.label} : l'ajout de nodes arrive avec l'edition (P4)`, `${e.label}: adding nodes comes with editing (P4)`))
  }, [tr])

  const choices = scopeChoices(rights, project, tr)

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', background: 'var(--paper)' }}>
      <TopBar
        flows={flows}
        current={loaded?.name ?? current ?? ''}
        scope={loaded?.scope}
        version={loaded?.version ?? (loaded?.state.current || undefined)}
        legacy={!!loaded?.legacy}
        showPerso={rights.td}
        saveBlocked={saveBlocked}
        canMigrate={rights.team_td}
        search={search}
        dots={prefs.dots}
        straight={prefs.straight}
        actions={{
          onNew: () => setDialog('new'),
          onOpen: f => open(f.name, f.scope),
          onSave: () => save(),
          onSaveAs: () => setDialog('saveas'),
          onIncrement: () => increment(),
          onMigrate: () => migrate(true),
        }}
        run={{
          running, runBlocked, dryBlocked, runsOpen,
          onRun: () => launch(false), onDry: () => launch(true), onStop: stop,
          onToggleRuns: () => setRunsOpen(v => !v),
        }}
        onSearch={setSearch}
        onToggleDots={() => updatePrefs({ dots: !prefs.dots })}
        onToggleWires={toggleWires}
        onLegacy={() => navigate('/action-graph-legacy')}
      />
      {loaded?.legacy && (
        <div className="flow-banner">
          {tr('Flow migre des actions v1. Le publish tourne encore sur les actions v1 (jusqu\'a P8) : ce flow ne s\'active pas.',
              'Flow migrated from the v1 actions. Publishing still runs on the v1 actions (until P8): this flow does not activate.')}
        </div>
      )}
      <ShelfBar catalog={catalog} onPick={onPick} />
      <div style={{ flex: 1, minHeight: 0, display: 'flex' }}>
        {error
          ? <div style={{ flex: 1, padding: 20, fontSize: 12, color: 'var(--ink-3)' }}>
              {tr(`Impossible de lire "${current}" : ${error}`, `Cannot read "${current}": ${error}`)}
            </div>
          : <NetworkPane
              view={view} search={search} dots={prefs.dots} straight={prefs.straight} catalog={catalog} runStates={runStates}
              onSelect={onSelect} onPick={onPick} onToggleWires={toggleWires}
            />}
        <ParamsPane view={view} selected={selected} />
      </div>
      {runsOpen && loaded && (
        <RunsPanel
          flow={loaded.name} project={project || undefined} refreshKey={runsKey} openRunId={openRunId}
          onOpen={setOpenRunId} onRecord={openRecord} onSelectNode={setSelectedId} onClose={() => setRunsOpen(false)}
        />
      )}
      <NameDialog
        open={dialog !== null}
        title={dialog === 'saveas' ? tr('Enregistrer sous', 'Save as') : tr('Nouveau flow', 'New flow')}
        initialName={dialog === 'saveas' && loaded ? `${loaded.name.replace(LEGACY_PREFIX, '')}_copy`.slice(0, 41) : ''}
        initialScope={loaded?.scope === 'shipped' ? 'team' : loaded?.scope}
        choices={choices}
        onClose={() => setDialog(null)}
        onConfirm={create}
      />
      <MigrateDialog report={migration} busy={busy} onClose={() => setMigration(null)} onConfirm={() => migrate(false)} />
    </div>
  )
}

export function FlowEditor() {
  const { tr } = useTr()
  const rights = useFlowRights()
  if (rights === undefined) return null
  if (!rights?.td) {
    return (
      <div style={{ flex: 1, padding: 24, display: 'flex', flexDirection: 'column', gap: 6, background: 'var(--paper)' }}>
        <div style={{ fontSize: 13, color: 'var(--ink)' }}>{tr('Acces refuse', 'Access denied')}</div>
        <div style={{ fontSize: 11, color: 'var(--ink-3)' }}>
          {rights === null
            ? tr('Droits illisibles : le backend ne repond pas.', 'Rights unreadable: the backend does not answer.')
            : tr('Coche TD dans ton profil (Parametres > User > Flows).', 'Tick TD in your profile (Settings > User > Flows).')}
        </div>
      </div>
    )
  }
  return (
    <ReactFlowProvider>
      <Editor rights={rights} />
    </ReactFlowProvider>
  )
}
