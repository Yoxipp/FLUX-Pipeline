// FlowEditor.tsx — shell of the Flows editor (route /action-graph, 03_EDITEUR §1):
// top bar (File menu), Shelf, Network, Params. P1: reads v2 flows from the store
// (GET /flows, /flows/{name}) through v2_adapter.ts; the File menu writes through the
// /flows routes (ADR 0058: Save overwrites, Save and increment freezes vNNN). The Shelf
// still lists the v1 commands (catalogue P2).
// P4: the document is edited in a DocStore (store.ts, undo / redo, history.ts) through pure
// reducers (reducers.ts); the view is derived from it. Move, delete, copy / paste
// (clipboard.ts), Layout (layout.ts). Read-only where Save is blocked (shipped, frozen
// version, no box). A save keeps the document and its undo pile.
// P4 step 4: the catalogue is GET /flows/catalog (v2 nodes); nodes are added from the Tab menu,
// the Shelf, the Catalogue drawer (NodePalette) or a link dropped in the void, linked by
// dragging (portTypes.checkLink), edited in Params.
// Open flow: deep link /action-graph?flow=<name>, else the last flow this user opened
// (user data `flows_last_open`, USER/<user>/UserSettings), else "legacy_publish".
// A v1 name kept from P0 ("publish") opens its legacy_ flow.
// View prefs (background dots, wire style) are per-viewer conveniences in localStorage.
// The old YAML action editor (/action-graph-legacy) was removed in P8 (ADR 0070).
// P2 (03_EDITEUR §7): Run = the open document (POST /flows/{name}/run with draft, TD), Essai =
// dry run of the saved file; node states arrive by WS /flows/ws (useFlowsWs) and are reread
// from GET /flows/runs/{id} after a reconnection; Notify nodes show a toast; the Runs dock lists
// the history and colours the graph with an opened run.
// Entry needs the TD box (flows_td, 01 §7): without it the route shows "Acces refuse".
// P5: Activer (ActivationDialog, 03 §5) on the frozen version `current`; WS `activation`
// of the open flow refreshes its state.
// P6a (03 §8): double click / Enter on a DCC node shipped as a locked subflow enters it (trail
// shown as a breadcrumb in the top bar, U goes back up); DccBanner: Deverrouiller (team copy) and
// Revenir au defaut. The core leaves (spec.internal) are left out of Tab / Shelf / Catalogue.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ReactFlowProvider, useReactFlow } from '@xyflow/react'
import { useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { api } from '../../api/client'
import { flowsApi } from '../../api/flows'
import { useFlowsWs } from '../../hooks/useFlowsWs'
import { useProject } from '../../ProjectContext'
import { MigrateDialog, NameDialog, START_NODE, scopeChoices, type StartKind } from './FileDialogs'
import { GROUP_PREFIX, NetworkPane, NOTE_PREFIX, type EditActions } from './NetworkPane'
import { NodePalette } from './NodePalette'
import { NodeWriterDialog } from './NodeWriterDialog'
import { ParamsPane, type NodeEdits } from './ParamsPane'
import { FlowParams } from './FlowParams'
import { RunsPanel } from './RunsPanel'
import { ShelfBar } from './ShelfBar'
import { TopBar, type FlowListEntry } from './TopBar'
import type { FlowDoc, FlowRead, FlowRights, FlowScope, FlowsWsMessage, Issue, MigrateReport, NodeRunInfo, RunIssue, RunRecord } from './types'
import { IssuesPanel, type CheckState } from './IssuesPanel'
import { VersionsDialog } from './VersionsDialog'
import { ConflictDialog, type ConflictInfo } from './ConflictDialog'
import { DestructiveDialog } from './DestructiveDialog'
import { ActivationDialog } from './ActivationDialog'
import { PageRunDialog, pageStarts, type PageClick } from './PageRunDialog'
import { FlowOpDialogs, FlowOpMenu, opBlocked, type FlowOpRequest, type FlowRef } from './FlowManage'
import { BridgesDialog } from './BridgesDialog'
import { DccBanner } from './DccBanner'
import { destructiveAdded } from './destructive'
import { registerCloseGuard } from '../../components/shared/closeGuard'
import { applyFix, autoBegin } from './fixes'
import type { CatalogEntry } from './v1_adapter'
import { adaptCatalog, adaptV2Flow, type SpecIndex } from './v2_adapter'
import { createDocStore, docOf, isDirty, useStore } from './store'
import { addNode, connect, disconnect, insertBlock, moveNodes, nextId, nextNodeId, removeGroup, removeItems, setFlowFields, setNodeFields, setParam, upsertGroup, upsertNote } from './reducers'
import { checkLink } from './portTypes'
import { clipToText, copySelection, parseClip, pasteBlock } from './clipboard'
import { layoutFlow } from './layout'
import { useTr } from './useTr'
import { useFlowRights } from './useFlowRights'

const DEFAULT_FLOW = 'legacy_publish'
const LEGACY_PREFIX = 'legacy_'
const LAST_OPEN_KEY = 'flows_last_open'
const PREFS_KEY = 'flux.flow_editor.view'
const DRAFT_PREFIX = 'flux.flow_draft.'

type ViewPrefs = { dots: boolean; straight: boolean }
type HttpError = Error & { status?: number; detail?: { by?: string; at?: string; status?: string; code?: string; issues?: RunIssue[] } }
type RunStates = Record<string, NodeRunInfo>
type RunLinks = RunRecord['links']   // value per link "a.port->b.port"

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
  const { tr, lang } = useTr()
  const { project } = useProject()
  const [params, setParams] = useSearchParams()
  const [flows, setFlows] = useState<FlowListEntry[]>([])
  const [current, setCurrent] = useState<string | null>(params.get('flow'))
  const [wantedScope, setWantedScope] = useState<FlowScope | undefined>((params.get('scope') as FlowScope) || undefined)
  const [wantedVersion, setWantedVersion] = useState<number | undefined>(undefined)   // Voir vNNN (read-only)
  const [reloadKey, setReloadKey] = useState(0)
  const [versionsOpen, setVersionsOpen] = useState(false)
  const [activationOpen, setActivationOpen] = useState(false)
  const [bridgesOpen, setBridgesOpen] = useState(false)
  const [trail, setTrail] = useState<{ name: string; scope: FlowScope }[]>([])   // DCC nodes entered
  const [conflictInfo, setConflictInfo] = useState<ConflictInfo | null>(null)
  // "!" nodes to confirm with the slider before a save; resolve(true) = confirmed.
  const [destructive, setDestructive] = useState<{ ids: string[]; resolve: (ok: boolean) => void } | null>(null)
  const askDestructive = useCallback((ids: string[]) => new Promise<boolean>(resolve => setDestructive({ ids, resolve })), [])
  const [loaded, setLoaded] = useState<FlowRead | null>(null)
  const [catalog, setCatalog] = useState<CatalogEntry[] | null>(null)
  const [nodeErrors, setNodeErrors] = useState<{ file: string; error: string }[]>([])
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [writing, setWriting] = useState(false)
  // P4 validation (03 §5): POST /flows/validate 300 ms after the last edit; the backend is the reference.
  const [issues, setIssues] = useState<Issue[]>([])
  const [check, setCheck] = useState<CheckState>('idle')
  const [issuesOpen, setIssuesOpen] = useState(true)
  const [flash, setFlash] = useState<{ id: string; n: number } | null>(null)
  // P4: the document being edited lives in the store (undo / redo); `loaded` keeps what the
  // backend answered (scope, version, state).
  const store = useMemo(() => createDocStore<FlowDoc>(), [])
  const doc = useStore(store, docOf)
  const dirty = useStore(store, isDirty)
  const rf = useReactFlow()
  const [selection, setSelection] = useState<ReadonlySet<string>>(new Set())
  const [search, setSearch] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [prefs, setPrefs] = useState<ViewPrefs>(readPrefs)
  const [dialog, setDialog] = useState<'new' | 'saveas' | null>(null)
  // ADR 0069: right-click menu of a flow in Open, and the Dupliquer / Renommer / portee / Supprimer dialogs.
  const [opMenu, setOpMenu] = useState<{ at: { x: number; y: number }; flow: FlowRef } | null>(null)
  const [opReq, setOpReq] = useState<FlowOpRequest | null>(null)
  const [migration, setMigration] = useState<MigrateReport | null>(null)
  const [busy, setBusy] = useState(false)
  // Runs: the run launched from this window (live), the node states shown, the Runs dock.
  const [liveRun, setLiveRun] = useState<{ id: string; running: boolean } | null>(null)
  const [runStates, setRunStates] = useState<RunStates>({})
  const [runLinks, setRunLinks] = useState<RunLinks>({})
  const [runsOpen, setRunsOpen] = useState(false)
  const [openRunId, setOpenRunId] = useState<string | null>(null)
  const [runsKey, setRunsKey] = useState(0)
  const runBuf = useRef<Record<string, RunStates>>({})   // states per run_id, also before POST answers
  const linkBuf = useRef<Record<string, RunLinks>>({})   // link values per run_id (link_value)
  const liveRef = useRef<string | null>(null)

  const refreshList = useCallback(() => {
    flowsApi.list(project || undefined)
      .then(list => setFlows(list.map(f => ({ name: f.name, scope: f.scope, category: f.category, legacy: f.legacy, shadowed: f.shadowed }))))
      .catch(() => setFlows([]))
  }, [project])

  useEffect(() => { refreshList() }, [refreshList])
  const loadCatalog = useCallback(() => {
    flowsApi.getCatalog()
      .then(c => { setCatalog(adaptCatalog(c)); setNodeErrors(c.node_errors ?? []) })
      .catch(() => setCatalog([]))
  }, [])
  useEffect(() => { loadCatalog() }, [loadCatalog])

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

  const load = useCallback(async (name: string, scope?: FlowScope, version?: number): Promise<FlowRead> => {
    try {
      return await flowsApi.get(name, { scope, project: project || undefined, version })
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
    setSelection(new Set())
    load(current, wantedScope, wantedVersion)
      .then(r => {
        if (!alive) return
        setLoaded(r)
        store.load(r.flow)
        if (r.version === null) offerDraft(r)
      })
      .catch(e => { if (alive) { setLoaded(null); store.load(null); setError(String(e?.message ?? e)) } })
    return () => { alive = false }
  }, [current, wantedScope, wantedVersion, load, store, reloadKey])  // eslint-disable-line react-hooks/exhaustive-deps

  // Local draft (03 §6): closing the main window closes the others without guard, so the
  // edited document is kept in localStorage (flux.flow_draft.<scope>.<name>) and offered
  // again at the next opening. Removed once saved or dropped.
  const draftKey = (scope: FlowScope, name: string) => `${DRAFT_PREFIX}${scope}.${name}`
  const offerDraft = (r: FlowRead) => {
    let draft: { doc: FlowDoc; at: string } | null = null
    try { draft = JSON.parse(localStorage.getItem(draftKey(r.scope, r.name)) ?? 'null') } catch { draft = null }
    if (!draft?.doc || JSON.stringify(draft.doc) === JSON.stringify(r.flow)) return
    const key = draftKey(r.scope, r.name)
    toast.info(tr(`Brouillon non enregistre de ${r.name} (${draft.at.slice(0, 16).replace('T', ' ')})`, `Unsaved draft of ${r.name} (${draft.at.slice(0, 16).replace('T', ' ')})`), {
      duration: 20000,
      action: { label: tr('Reprendre', 'Restore'), onClick: () => store.apply(() => draft!.doc) },
      cancel: { label: tr('Ignorer', 'Drop'), onClick: () => { try { localStorage.removeItem(key) } catch { /* nothing kept */ } } },
    })
  }
  useEffect(() => {
    if (!loaded || loaded.version !== null) return
    const key = draftKey(loaded.scope, loaded.name)
    const t = setTimeout(() => {
      try {
        if (dirty && doc) localStorage.setItem(key, JSON.stringify({ doc, at: new Date().toISOString() }))
        else localStorage.removeItem(key)
      } catch { /* private mode: no draft */ }
    }, dirty ? 1000 : 0)
    return () => clearTimeout(t)
  }, [doc, dirty, loaded?.scope, loaded?.name, loaded?.version])  // eslint-disable-line react-hooks/exhaustive-deps

  const switchTo = useCallback((name: string, scope?: FlowScope, version?: number) => {
    setCurrent(name)
    setWantedScope(scope)
    setWantedVersion(version)
    setReloadKey(k => k + 1)
    setParams(scope ? { flow: name, scope } : { flow: name }, { replace: true })
    if (version === undefined) api.setUserData({ [LAST_OPEN_KEY]: name }).catch(() => { /* not kept: reopens the default */ })
  }, [setParams])

  // After a save: the document stays (and its undo pile), only the state moves on.
  const saved = useCallback((sent: FlowDoc, state: FlowRead['state']) => {
    store.markSaved(sent)
    setLoaded(l => l ? { ...l, state } : l)
    refreshList()
  }, [store, refreshList])

  // Why Save / Increment are greyed for the open flow (null = allowed).
  const saveBlocked = !loaded ? tr('Aucun flow ouvert', 'No open flow')
    : loaded.scope === 'shipped' ? tr('Flow livre en lecture seule : Enregistrer sous en equipe', 'Shipped flow is read-only: Save as to team')
    : loaded.version !== null ? tr('Version figee ouverte : lecture seule', 'Frozen version open: read-only')
    : !rights.can[loaded.scope]?.write ? (loaded.scope === 'perso' ? tr('Case TD requise', 'TD box required') : tr('Case Team TD requise', 'Team TD box required'))
    : undefined
  // The graph is editable where it can be saved (a shipped flow: Save as first).
  useEffect(() => {
    if (!doc || !loaded) { setIssues([]); setCheck('idle'); return }
    let alive = true
    setCheck('checking')
    const t = setTimeout(() => {
      flowsApi.validate(doc, loaded.scope, project || undefined)
        .then(r => { if (alive) { setIssues(r.issues); setCheck('ok') } })
        .catch(() => { if (alive) setCheck('down') })
    }, 300)
    return () => { alive = false; clearTimeout(t) }
  }, [doc, loaded?.scope, loaded?.name, project])  // eslint-disable-line react-hooks/exhaustive-deps

  // Tab, Shelf and Catalogue never offer the core leaves of the DCC nodes (they live inside them).
  const menuCatalog = useMemo(() => catalog ? catalog.filter(e => !e.spec?.internal) : null, [catalog])
  const specs = useMemo<SpecIndex>(() => Object.fromEntries((catalog ?? []).filter(e => e.spec).map(e => [e.type, e.spec!])), [catalog])
  const view = useMemo(() => doc && loaded ? adaptV2Flow(doc, { readOnly: !!saveBlocked, origin: loaded.scope, specs }) : null, [doc, loaded, saveBlocked, specs])

  // Save core (03 §6), used by Ctrl+S, Save and increment, quit (closeGuard, flow switch).
  // Resolves true when the document is saved (or there was nothing to save), false when it
  // stays open: cancelled slider, conflict, error. Saving with errors is allowed (00 §11).
  const saveDoc = useCallback(async (kind: 'save' | 'increment', opts: { force?: boolean; confirmed?: string[]; quiet?: boolean } = {}): Promise<boolean> => {
    const s = store.get()
    const sent = docOf(s)
    if (!loaded || !sent || saveBlocked) return true
    if (kind === 'save' && !isDirty(s) && !opts.force) {
      if (!opts.quiet) toast.info(tr('Deja enregistre', 'Already saved'))
      return true
    }
    let confirmed = opts.confirmed ?? []
    const added = destructiveAdded(sent, s.saved, specs).filter(id => !confirmed.includes(id))
    if (added.length) {
      if (!(await askDestructive(added))) return false
      confirmed = [...confirmed, ...added]
    }
    const base = { project: project || undefined, base_revision: loaded.state.revision, force: opts.force, confirmed_destructive: confirmed }
    try {
      const r = kind === 'save'
        ? await flowsApi.save(sent, loaded.scope, base)
        : await flowsApi.increment(loaded.name, loaded.scope, sent, base)
      const created = 'created' in r ? (r as { created: number | null }).created : null
      const errors = r.issues.filter(i => i.level === 'error').length
      const what = kind === 'increment'
        ? created ? tr(`${loaded.name} enregistre (v${String(created).padStart(3, '0')})`, `${loaded.name} saved (v${String(created).padStart(3, '0')})`)
          : tr('Contenu identique a la derniere version : rien de fige', 'Same content as the last version: nothing frozen')
        : tr(`Flow ${loaded.name} enregistre`, `Flow ${loaded.name} saved`)
      if (errors) toast.warning(tr(`${what}, invalide (${errors} erreur(s)), non activable`, `${what}, invalid (${errors} error(s)), cannot be activated`))
      else if (!opts.quiet || kind === 'increment') toast.success(what)
      saved(sent, r.state)
      return true
    } catch (err) {
      const e = err as HttpError
      if (e.status === 409 && e.detail?.code === 'E_DESTRUCTIVE_UNCONFIRMED') {
        // The backend found `!` nodes the editor did not: ask for them, then retry once.
        const ids = (e.detail.issues ?? []).map(i => i.node).filter((x): x is string => !!x && !confirmed.includes(x))
        if (!ids.length || !(await askDestructive(ids))) return false
        return saveDoc(kind, { ...opts, confirmed: [...confirmed, ...ids] })
      }
      if (e.status === 409 && !e.detail?.code) {
        setConflictInfo({ by: e.detail?.by, at: e.detail?.at, retry: () => { void saveDoc(kind, { ...opts, force: true, confirmed }) } })
        return false
      }
      toast.error(e.message)
      return false
    }
  }, [loaded, saveBlocked, project, specs, saved, store, askDestructive, tr])  // eslint-disable-line react-hooks/exhaustive-deps

  const save = useCallback(() => { void saveDoc('save') }, [saveDoc])
  const increment = useCallback(() => { void saveDoc('increment') }, [saveDoc])

  // Quit = Ctrl+S (decision 13): closing a detached window, switching flow.
  const quit = useCallback(() => saveDoc('save', { quiet: true }), [saveDoc])
  useEffect(() => registerCloseGuard(quit), [quit])
  const open = useCallback(async (name: string, scope?: FlowScope, version?: number) => {
    if (!(await quit())) return false
    switchTo(name, scope, version)
    return true
  }, [quit, switchTo])

  // Enter a DCC node (its locked subflow, or the team copy), and back up (U, breadcrumb).
  const enter = useCallback(async (node: { spec?: { subflow?: { name: string; scope: FlowScope } | null } }) => {
    const sub = node.spec?.subflow
    if (!sub || !loaded) return
    const here = { name: loaded.name, scope: loaded.scope }
    if (await open(sub.name, sub.scope)) setTrail(t => [...t, here])
  }, [loaded, open])
  const upTo = useCallback(async (index: number) => {
    const target = trail[index]
    if (target && await open(target.name, target.scope)) setTrail(t => t.slice(0, index))
  }, [trail, open])

  const revert = useCallback((version: number) => {
    if (!loaded) return
    flowsApi.revert(loaded.name, loaded.scope, version, project || undefined)
      .then(r => {
        toast.success(r.created
          ? tr(`v${String(r.created).padStart(3, '0')} creee, identique a v${String(version).padStart(3, '0')}`, `v${String(r.created).padStart(3, '0')} created, identical to v${String(version).padStart(3, '0')}`)
          : tr('Deja la derniere version', 'Already the latest version'))
        setVersionsOpen(false)
        switchTo(loaded.name, loaded.scope)
      })
      .catch((e: Error) => toast.error(e.message))
  }, [loaded, project, switchTo, tr])

  const create = useCallback(async (name: string, scope: FlowScope, start: StartKind = 'manual') => {
    // Nouveau: an empty flow headed by the start picked in the dialog (ADR 0068 n°5). Enregistrer
    // sous: the open document renamed (a new file: every `!` node is confirmed with the slider, 01 §8).
    const next: FlowDoc = dialog === 'saveas' && doc
      ? { ...doc, name }
      : { flux_flow: 2, name, label: name, nodes: { n1: { type: START_NODE[start], pos: [0, 0], params: {} } }, links: [] }
    const bang = destructiveAdded(next, null, specs)
    if (bang.length && !(await askDestructive(bang))) return
    flowsApi.save(next, scope, { project: project || undefined, confirmed_destructive: bang })
      // switchTo, not open: Save as must not save the original document first.
      .then(() => { setDialog(null); refreshList(); switchTo(name, scope); toast.success(tr(`${name} cree`, `${name} created`)) })
      .catch((e: HttpError) => toast.error(e.status === 409 && !e.detail?.code ? tr('Un flow de ce nom existe deja dans cette categorie', 'A flow with this name already exists there') : e.message))
  }, [dialog, doc, project, specs, refreshList, switchTo, askDestructive, tr])

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
    setRunLinks({ ...(linkBuf.current[id] ?? {}) })
  }, [])

  const onWs = useCallback((msg: FlowsWsMessage) => {
    if (msg.type === 'hello' || msg.type === 'host' || msg.type === 'flow_changed') return
    if (msg.type === 'activation') {
      setLoaded(l => l && l.name === msg.flow && l.scope === msg.scope
        ? { ...l, state: { ...l.state, active: msg.active, active_version: msg.version } } : l)
      return
    }
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
    if (msg.type === 'link_value') {
      const buf = (linkBuf.current[msg.run_id] ??= {})
      buf[msg.link] = { value: msg.preview, count: msg.count }
      if (msg.run_id === liveRef.current) setRunLinks({ ...buf })
      return
    }
    if (msg.type === 'run_finished' && msg.run_id === liveRef.current) {
      setLiveRun(r => r && r.id === msg.run_id ? { ...r, running: false } : r)
      setRunsKey(k => k + 1)
      // The record has the values received of a failed node: reread it once.
      flowsApi.getRun(msg.run_id, project || undefined).then(r => { setRunStates(r.nodes); setRunLinks(r.links ?? {}) }).catch(() => { /* WS states stay */ })
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
      setRunLinks(r.links ?? {})
      setLiveRun(cur => cur && cur.id === id ? { ...cur, running: r.status === 'queued' || r.status === 'running' } : cur)
    }).catch(() => { /* run of a restarted backend: interrupted */ })
  }, [project])

  const wsUp = useFlowsWs(onWs, onWsReconnect)

  const launch = useCallback((dry: boolean, click?: PageClick) => {
    if (!loaded || !doc) return
    const base = dry
      ? { scope: loaded.scope, project: project || undefined, dry_run: true }
      : { scope: loaded.scope, project: project || undefined, draft: doc, base_revision: loaded.state.revision }
    const opts = click ? { ...base, event: click.event, button: click.button, values: click.values } : base
    flowsApi.run(loaded.name, opts)
      .then(r => { setLiveRun({ id: r.run_id, running: true }); showLive(r.run_id) })
      .catch((e: HttpError) => {
        const first = e.detail?.issues?.[0]
        toast.error(first ? `${e.message} : ${first.message_fr}` : e.message)
        if (e.detail?.status) setRunsKey(k => k + 1)
      })
  }, [loaded, doc, project, showLive])

  // A page flow (InputsPageReader with buttons): Run / Essai ask which button and the field values (T1).
  const starts = useMemo(() => pageStarts(doc), [doc])
  const [pageRun, setPageRun] = useState<{ dry: boolean } | null>(null)
  const startRun = useCallback((dry: boolean) => {
    if (starts.length) setPageRun({ dry })
    else launch(dry)
  }, [starts, launch])

  const stop = useCallback(() => {
    if (!liveRun) return
    flowsApi.cancelRun(liveRun.id, project || undefined).catch((e: Error) => toast.error(e.message))
  }, [liveRun, project])

  const openRecord = useCallback((r: RunRecord | null) => {
    if (r) { setRunStates(r.nodes); setRunLinks(r.links ?? {}) }
    else if (liveRef.current) { setRunStates({ ...(runBuf.current[liveRef.current] ?? {}) }); setRunLinks({ ...(linkBuf.current[liveRef.current] ?? {}) }) }
    else { setRunStates({}); setRunLinks({}) }
  }, [])

  // A new flow opened: no run states from the previous one.
  useEffect(() => { liveRef.current = null; setLiveRun(null); setRunStates({}); setRunLinks({}); setOpenRunId(null) }, [loaded?.name, loaded?.scope])

  const running = !!liveRun?.running
  const runBlocked = !loaded ? tr('Aucun flow ouvert', 'No open flow')
    : !rights.can[loaded.scope]?.draft ? tr('Case TD requise', 'TD box required')
    : !wsUp ? tr('Backend injoignable', 'Backend unreachable')
    : check === 'down' ? tr('Verification indisponible', 'Check unavailable')
    : undefined
  const dryBlocked = runBlocked
    ?? (loaded?.version !== null ? tr('Version figee ouverte : ouvre le fichier de travail', 'Frozen version open: open the working file')
      : dirty ? tr('Enregistre d\'abord (Ctrl+S)', 'Save first (Ctrl+S)') : undefined)

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

  // Selection ids: node ids as is, notes and group boxes prefixed (NetworkPane NOTE_PREFIX / GROUP_PREFIX).
  const picked = useMemo(() => {
    const nodes: string[] = [], notes: string[] = [], groups: string[] = []
    for (const id of selection) {
      if (id.startsWith(NOTE_PREFIX)) notes.push(id.slice(NOTE_PREFIX.length))
      else if (id.startsWith(GROUP_PREFIX)) groups.push(id.slice(GROUP_PREFIX.length))
      else nodes.push(id)
    }
    return { nodes, notes, groups }
  }, [selection])
  const selectedId = selection.size === 1 && picked.nodes.length === 1 ? picked.nodes[0] : null
  const selected = useMemo(() => view?.nodes.find(n => n.id === selectedId) ?? null, [view, selectedId])
  // xyflow reports the selection after each render: keep the same Set when nothing changed.
  const onSelect = useCallback((ids: string[]) => setSelection(cur =>
    ids.length === cur.size && ids.every(id => cur.has(id)) ? cur : new Set(ids)), [])
  const selectNode = useCallback((id: string) => onSelect([id]), [onSelect])
  // R1 retake 9: the flow panel places a FlowInput / FlowOutput, left of the graph, selected.
  const placeNode = useCallback((type: string, params: Record<string, unknown>) => {
    if (saveBlocked) { toast.info(saveBlocked); return }
    const d = docOf(store.get())
    if (!d) return
    const nodes = Object.values(d.nodes ?? {})
    const x = nodes.length ? Math.min(...nodes.map(n => n.pos?.[0] ?? 0)) - 320 : 0
    const y = nodes.length ? Math.max(...nodes.map(n => n.pos?.[1] ?? 0)) + 160 : 0
    const id = nextNodeId(d)
    store.apply(cur => addNode(cur, id, { type, pos: [x, y], params }))
    setSelection(new Set([id]))
  }, [saveBlocked, store])

  const edit = useMemo<EditActions>(() => ({
    onMove: positions => store.apply(d => moveNodes(d, positions)),
    onDelete: () => {
      if (!selection.size) return
      store.apply(d => picked.groups.reduce(removeGroup, removeItems(d, [...picked.nodes, ...picked.notes])))
      setSelection(new Set())
    },
    onUndo: store.undo,
    onRedo: store.redo,
    onSelectAll: () => { const d = docOf(store.get()); if (d) setSelection(new Set([...Object.keys(d.nodes), ...(d.notes ?? []).map(n => NOTE_PREFIX + n.id)])) },
    onCopy: () => {
      const d = docOf(store.get())
      const clip = d && copySelection(d, [...picked.nodes, ...picked.notes])
      if (clip) navigator.clipboard.writeText(clipToText(clip)).catch(() => toast.error(tr('Presse-papiers indisponible', 'Clipboard unavailable')))
    },
    onPaste: at => {
      navigator.clipboard.readText().then(text => {
        const d = docOf(store.get())
        const clip = parseClip(text)
        if (!d || !clip) return
        const block = pasteBlock(d, clip, at)
        store.apply(cur => insertBlock(cur, block))
        setSelection(new Set([...Object.keys(block.nodes), ...block.notes.map(n => NOTE_PREFIX + n.id)]))
      }).catch(() => toast.error(tr('Presse-papiers indisponible', 'Clipboard unavailable')))
    },
    // Alt + drag: a copy of the nodes (and the links between them) with its top-left at `at`.
    onDuplicate: (ids, at) => {
      const d = docOf(store.get())
      const clip = d && copySelection(d, ids)
      if (!d || !clip) return
      const block = pasteBlock(d, clip, at)
      store.apply(cur => insertBlock(cur, block))
      setSelection(new Set(Object.keys(block.nodes)))
    },
    onConnect: (from, to) => store.apply(d => connect(d, from, to)),
    onDisconnect: links => store.apply(d => disconnect(d, links)),
    // A link picked up from its input: moved to `to`, or removed (null). One undo entry.
    onRelink: (old, to) => store.apply(d => to ? connect(disconnect(d, [old]), old.from, to) : disconnect(d, [old])),
    // One undo entry: the node and, from a link dropped in the void, its link.
    onGroup: () => {
      if (!picked.nodes.length) return
      const d = docOf(store.get())
      if (!d) return
      const id = nextId((d.groups ?? []).map(g => g.id), 'g')
      store.apply(cur => upsertGroup(cur, { id, label: tr('Groupe', 'Group'), nodes: [...picked.nodes] }))
      setSelection(new Set([GROUP_PREFIX + id]))
    },
    onNote: at => {
      const d = docOf(store.get())
      if (!d) return
      const id = nextId([...(d.notes ?? []).map(n => n.id), ...Object.keys(d.nodes)], 'k')
      store.apply(cur => upsertNote(cur, { id, pos: at, text: '' }))
      setSelection(new Set([NOTE_PREFIX + id]))
    },
    onRenameGroup: (id, label) => store.apply(d => {
      const g = d.groups?.find(x => x.id === id)
      return g ? upsertGroup(d, { ...g, label }) : d
    }),
    onNoteText: (id, text) => store.apply(d => {
      const k = d.notes?.find(x => x.id === id)
      return k ? upsertNote(d, { ...k, text }) : d
    }),
    onAdd: (entry, at, link) => {
      const d = docOf(store.get())
      if (!d) return
      const id = nextNodeId(d)
      const begin = autoBegin(d, entry.type)
      let next = addNode(d, id, { type: entry.type, pos: at, params: begin ? { begin } : {} })
      if (link) {
        const nodes = Object.fromEntries(adaptV2Flow(next, { readOnly: false, specs }).nodes.map(n => [n.id, n]))
        const r = checkLink(nodes, next.links, link.end, { node: id, port: link.port, side: link.end.side === 'out' ? 'in' : 'out' })
        if (r.status === 'incompatible' || !r.from || !r.to) toast.warning(lang === 'en' ? r.reason_en : r.reason_fr)
        else next = connect(next, r.from, r.to)
      }
      store.apply(() => next)
      setSelection(new Set([id]))
    },
  }), [store, selection, picked, specs, tr, lang])

  // Layout (03 §4): the only thing that arranges the graph; one undo entry, then frames.
  const arrange = useCallback(() => {
    store.apply(d => moveNodes(d, layoutFlow(d, id => rf.getNode(id)?.measured?.height ?? 110)))
    requestAnimationFrame(() => rf.fitView({ padding: 0.15, duration: 250 }))
  }, [store, rf])

  // Shelf / Catalogue click: after the selected node (R1 audit P3.3, 2026-10-25: placed on
  // its right, its first free exec output linked to the new exec, like stacking Scratch blocks),
  // else at the centre of the view. Ctrl+Z undoes both.
  const onPick = useCallback((e: CatalogEntry) => {
    if (saveBlocked) { toast.info(saveBlocked); return }
    const d = docOf(store.get())
    const sel = selected && d?.nodes[selected.id] ? selected : null
    if (sel && d && e.spec?.inputs.some(p => p.type === 'exec')) {
      const taken = new Set(d.links.map(l => l.from))
      const out = sel.outputs.find(o => o.type === 'exec' && o.name !== 'on_error' && !taken.has(`${sel.id}.${o.name}`))
      if (out) {
        const pos = d.nodes[sel.id].pos ?? [0, 0]
        edit.onAdd(e, [pos[0] + 320, pos[1]], { end: { node: sel.id, port: out.name, side: 'out' }, port: 'exec' })
        return
      }
    }
    const r = document.querySelector('.react-flow')?.getBoundingClientRect()
    const p = r ? rf.screenToFlowPosition({ x: r.left + r.width / 2, y: r.top + r.height / 2 }) : { x: 0, y: 0 }
    edit.onAdd(e, [p.x - 120, p.y - 30])
  }, [saveBlocked, rf, edit, store, selected])

  // Problems panel: a click frames the node (250 ms), selects it, it blinks once.
  const goToNode = useCallback((id: string) => {
    if (!docOf(store.get())?.nodes[id]) return
    rf.fitView({ nodes: [{ id }], duration: 250, padding: 0.6, maxZoom: 1.4 })
    setSelection(new Set([id]))
    setFlash(f => ({ id, n: (f?.n ?? 0) + 1 }))
  }, [rf, store])
  const zoomTo = useCallback((i: Issue) => { if (i.node) goToNode(i.node) }, [goToNode])
  const closeDestructive = (ok: boolean) => { destructive?.resolve(ok); setDestructive(null) }
  const destructiveNodes = useMemo(() => destructive ? (view?.nodes ?? []).filter(n => destructive.ids.includes(n.id)) : null, [destructive, view])
  const canFix = useCallback((i: Issue) => !!i.fix && !saveBlocked, [saveBlocked])
  const fixIssue = useCallback((i: Issue) => {
    const d = docOf(store.get())
    const r = d && applyFix(d, i, specs)
    if (!r) { toast.info(tr('Correction impossible ici (node pas encore disponible ?)', 'Cannot fix here (node not available yet?)')); return }
    store.apply(() => r.doc)
    if (r.select) setSelection(new Set([r.select]))
  }, [store, specs, tr])
  const labels = useMemo(() => Object.fromEntries((view?.nodes ?? []).map(n => [n.id, n.label])), [view])
  const errorCount = issues.filter(i => i.level === 'error').length

  const nodeEdits = useMemo<NodeEdits>(() => ({
    onParam: (id, name, value) => store.apply(d => setParam(d, id, name, value), `param:${id}:${name}`),
    onFields: (id, patch) => store.apply(d => setNodeFields(d, id, patch), `node:${id}:${Object.keys(patch).join(',')}`),
  }), [store])
  const onFlowFields = useCallback((patch: Partial<FlowDoc>, key: string) => store.apply(d => setFlowFields(d, patch), key), [store])

  const choices = scopeChoices(rights, project, tr)

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', background: 'var(--paper)' }}>
      <TopBar
        flows={flows}
        current={loaded?.name ?? current ?? ''}
        scope={loaded?.scope}
        version={loaded?.version ?? (loaded?.state.current || undefined)}
        legacy={!!loaded?.legacy}
        dirty={dirty}
        showPerso={rights.td}
        saveBlocked={saveBlocked}
        canMigrate={rights.team_td}
        search={search}
        dots={prefs.dots}
        straight={prefs.straight}
        actions={{
          onNew: () => setDialog('new'),
          onOpen: f => { void open(f.name, f.scope).then(ok => { if (ok) setTrail([]) }) },
          onSave: () => save(),
          onSaveAs: () => setDialog('saveas'),
          onIncrement: () => increment(),
          onMigrate: () => migrate(true),
          onFlowMenu: (f, x, y) => setOpMenu({ at: { x, y }, flow: { name: f.name, scope: f.scope } }),
          onManage: op => { if (loaded) setOpReq({ op, flow: { name: loaded.name, scope: loaded.scope } }) },
          manageBlocked: op => loaded ? opBlocked(op, loaded, rights, tr) : tr('Aucun flow ouvert', 'No open flow'),
        }}
        run={{
          running, runBlocked, dryBlocked, runsOpen,
          onRun: () => startRun(false), onDry: () => startRun(true), onStop: stop,
          onToggleRuns: () => setRunsOpen(v => !v),
        }}
        problems={{
          errors: errorCount, warnings: issues.length - errorCount, state: check, open: issuesOpen,
          onToggle: () => setIssuesOpen(v => !v),
        }}
        onSearch={setSearch}
        onToggleDots={() => updatePrefs({ dots: !prefs.dots })}
        onToggleWires={toggleWires}
        onLayout={arrange}
        onBackdrop={edit.onGroup}
        onNote={() => {
          const r = document.querySelector('.react-flow')?.getBoundingClientRect()
          const p = r ? rf.screenToFlowPosition({ x: r.left + r.width / 2, y: r.top + r.height / 2 }) : { x: 0, y: 0 }
          edit.onNote([p.x, p.y])
        }}
        onVersions={() => setVersionsOpen(true)}
        onBridges={() => setBridgesOpen(true)}
        trail={trail.map(t => t.name)}
        onCrumb={i => { void upTo(i) }}
        activation={loaded && !loaded.dcc ? {
          active: loaded.state.active, activeVersion: loaded.state.active_version, current: loaded.state.current,
          onOpen: () => setActivationOpen(true),
        } : undefined}
      />
      {loaded && loaded.version !== null && (
        <div className="flow-banner">
          {tr(`Lecture v${String(loaded.version).padStart(3, '0')} (version figee, lecture seule)`, `Reading v${String(loaded.version).padStart(3, '0')} (frozen version, read-only)`)}
          <button type="button" className="flow-tool" onClick={() => switchTo(loaded.name, loaded.scope)}>
            {tr('Retour au fichier de travail', 'Back to the working file')}
          </button>
        </div>
      )}
      {loaded?.dcc && (
        <DccBanner
          name={loaded.name} locked={loaded.dcc.locked} teamCopy={loaded.dcc.team_copy} canUnlock={rights.team_td}
          onUnlock={() => {
            flowsApi.unlock(loaded.name, project || undefined)
              .then(() => { toast.success(tr(`${loaded.name} deverrouille : copie d'equipe creee`, `${loaded.name} unlocked: team copy created`)); refreshList(); loadCatalog(); switchTo(loaded.name, 'team') })
              .catch((e: Error) => toast.error(e.message))
          }}
          onRevert={() => {
            flowsApi.remove(loaded.name, 'team', project || undefined)
              .then(() => { toast.success(tr(`${loaded.name} : node livre retabli`, `${loaded.name}: shipped node restored`)); refreshList(); loadCatalog(); switchTo(loaded.name, 'shipped') })
              .catch((e: Error) => toast.error(e.message))
          }}
        />
      )}
      {loaded?.legacy && (
        <div className="flow-banner">
          {tr('Flow migre des actions v1. Le publish tourne encore sur les actions v1 (jusqu\'a P8) : ce flow ne s\'active pas.',
              'Flow migrated from the v1 actions. Publishing still runs on the v1 actions (until P8): this flow does not activate.')}
        </div>
      )}
      <ShelfBar catalog={menuCatalog} paletteOpen={paletteOpen} onPick={onPick} onTogglePalette={() => setPaletteOpen(v => !v)}
                flowKey={loaded ? `${loaded.scope}/${loaded.name}` : undefined}
                startFamily={doc && Object.values(doc.nodes ?? {}).every(n => n.type.startsWith('event.')) ? 'event' : 'flux'} />
      <div style={{ flex: 1, minHeight: 0, display: 'flex' }}>
        {paletteOpen && <NodePalette catalog={menuCatalog} errors={nodeErrors} canWriteNode={rights.team_td} onNewNode={() => setWriting(true)}
                                     onPick={onPick} onClose={() => setPaletteOpen(false)} />}
        {error
          ? <div style={{ flex: 1, padding: 20, fontSize: 12, color: 'var(--ink-3)' }}>
              {tr(`Impossible de lire "${current}" : ${error}`, `Cannot read "${current}": ${error}`)}
            </div>
          : <NetworkPane
              view={view} flowKey={loaded ? `${loaded.scope}:${loaded.name}:${loaded.version ?? ''}` : ''}
              selection={selection} edit={edit}
              search={search} dots={prefs.dots} straight={prefs.straight} catalog={menuCatalog} runStates={runStates} runLinks={runLinks}
              onEnter={n => { void enter(n) }} onUp={trail.length ? () => { void upTo(trail.length - 1) } : undefined}
              issues={issues} flash={flash}
              onSelect={onSelect} onToggleWires={toggleWires}
            />}
        <ParamsPane
          selected={selected} params={(selected && doc?.nodes[selected.id]?.params) || {}}
          editable={!saveBlocked} edits={nodeEdits} flowName={doc?.name}
          iface={{ inputs: (doc?.interface?.inputs ?? []).map(x => x.id), outputs: (doc?.interface?.outputs ?? []).map(x => x.id),
                   variables: (doc?.variables ?? []).map(v => v.name) }}
          flowPart={<FlowParams doc={doc} editable={!saveBlocked} onFields={onFlowFields} onPlaceNode={placeNode} onSelectNode={selectNode} />}
        />
      </div>
      {issuesOpen && loaded && (
        <IssuesPanel issues={issues} state={check} labels={labels} canFix={canFix} onZoom={zoomTo} onFix={fixIssue} onClose={() => setIssuesOpen(false)} />
      )}
      {runsOpen && loaded && (
        <RunsPanel
          flow={loaded.name} project={project || undefined} refreshKey={runsKey} openRunId={openRunId}
          onOpen={setOpenRunId} onRecord={openRecord} onSelectNode={selectNode} onClose={() => setRunsOpen(false)}
        />
      )}
      <NameDialog
        open={dialog !== null}
        title={dialog === 'saveas' ? tr('Enregistrer sous', 'Save as') : tr('Nouveau flow', 'New flow')}
        initialName={dialog === 'saveas' && loaded ? `${loaded.name.replace(LEGACY_PREFIX, '')}_copy`.slice(0, 41) : ''}
        initialScope={loaded?.scope === 'shipped' ? 'team' : loaded?.scope}
        choices={choices}
        askStart={dialog === 'new'}
        onClose={() => setDialog(null)}
        onConfirm={create}
      />
      <NodeWriterDialog open={writing} onClose={() => setWriting(false)} onSaved={loadCatalog} />
      {loaded && (
        <VersionsDialog
          open={versionsOpen} name={loaded.name} scope={loaded.scope} project={project || undefined}
          canRevert={loaded.scope === 'shipped' || !rights.can[loaded.scope]?.write ? tr('Droits d\'ecriture requis', 'Write rights required')
            : dirty ? tr('Enregistre d\'abord (Ctrl+S)', 'Save first (Ctrl+S)') : undefined}
          onView={v => { setVersionsOpen(false); void open(loaded.name, loaded.scope, v) }}
          onRevert={revert} onClose={() => setVersionsOpen(false)}
        />
      )}
      <BridgesDialog open={bridgesOpen} canCreate={rights.team_td} onClose={() => setBridgesOpen(false)}
                     onNodes={() => { refreshList(); loadCatalog() }} />
      {loaded && (
        <ActivationDialog
          open={activationOpen} name={loaded.name} scope={loaded.scope} project={project || undefined} dirty={dirty}
          starts={starts}
          blocked={loaded.scope === 'shipped' ? tr('Flow livre : Deverrouiller (copie equipe) pour l\'activer', 'Shipped flow: Unlock (team copy) to activate it')
            : loaded.legacy ? tr('Flow legacy : publish v1 jusqu\'a P8', 'Legacy flow: v1 publish until P8')
            : !rights.can[loaded.scope]?.write ? (loaded.scope === 'perso' ? tr('Case TD requise', 'TD box required') : tr('Case Team TD requise', 'Team TD box required'))
            : undefined}
          onClose={() => setActivationOpen(false)}
          onChanged={state => setLoaded(l => l ? { ...l, state: { ...l.state, ...state } } : l)}
        />
      )}
      <PageRunDialog request={pageRun} starts={starts} project={project || undefined}
                     onLaunch={launch} onClose={() => setPageRun(null)} />
      <ConflictDialog
        conflict={conflictInfo} onClose={() => setConflictInfo(null)}
        onTheirs={() => {
          // Keep this document as the local draft (offered at the reopening), then load theirs.
          if (loaded && doc) {
            try { localStorage.setItem(`${DRAFT_PREFIX}${loaded.scope}.${loaded.name}`, JSON.stringify({ doc, at: new Date().toISOString() })) } catch { /* no draft */ }
          }
          setConflictInfo(null)
          if (loaded) switchTo(loaded.name, loaded.scope)
        }}
      />
      <DestructiveDialog
        nodes={destructiveNodes} params={Object.fromEntries(Object.entries(doc?.nodes ?? {}).map(([id, n]) => [id, n.params ?? {}]))}
        onGoTo={goToNode} onConfirm={() => closeDestructive(true)} onCancel={() => closeDestructive(false)}
      />
      <FlowOpMenu at={opMenu?.at ?? null} flow={opMenu?.flow ?? null} rights={rights}
                  onClose={() => setOpMenu(null)} onPick={op => { if (opMenu) setOpReq({ op, flow: opMenu.flow }) }}
                  onOpen={() => { if (opMenu) void open(opMenu.flow.name, opMenu.flow.scope).then(ok => { if (ok) setTrail([]) }) }} />
      <FlowOpDialogs
        request={opReq} choices={choices} project={project || undefined} dirty={dirty}
        openFlow={loaded ? { name: loaded.name, scope: loaded.scope } : null}
        onClose={() => setOpReq(null)}
        onDone={(next, removedOpen) => {
          const gone = opReq?.flow
          setOpReq(null)
          refreshList()
          if (next) { setTrail([]); switchTo(next.name, next.scope) }
          else if (removedOpen) {
            // The open flow went to the trash: show another one (the first listed, else an example).
            const other = flows.find(f => !f.shadowed && !(f.name === gone?.name && f.scope === gone?.scope))
            setTrail([])
            switchTo(other?.name ?? 'example_daily_render', other?.scope)
          }
        }}
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
