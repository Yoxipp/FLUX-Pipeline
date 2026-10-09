// MenuSpec — Houdini-style tabbed spec panel.
//
// Tab layout:  [Tasks | <entity · task N> | <entity · task · subtask K> | …]
//
// - The first tab is always "Tasks" and shows the CURRENTLY SELECTED entity's
//   (asset / shot / sequence) task chips. It is the only tab bound to the
//   selection.
// - A click on a task header opens a Task tab. A click on a subtask node
//   opens a Subtask tab. Both carry their own entityId and survive selection
//   changes — you can browse a different entity without losing them.
// - Each non-root tab has a pin (persisted per project on this machine) and
//   a close button. Pinned tabs come back after a restart.
//
// The entityId in a tab refers to an asset id, a shot id, or a sequence id;
// resolveEntity() looks it up across all three lists. TaskDetail is
// asset-centric — for shots and seqs we shim class/name so the component
// stays untouched.

import { useEffect, useMemo, useRef, useState } from 'react'
import { readSession, writeSession } from '../../hooks/useSessionState'
import { Pin, X, Layers, RefreshCw, Heart, Clapperboard } from 'lucide-react'
import { useFavoriteBinding } from '../../hooks/useFavorites'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { api } from '../../api/client'
import type { UsdAssetInfo } from '../../api/client'
import { OpenInMenu, projectRelPath } from '../../components/shared/OpenInMenu'
import { useProject } from '../../ProjectContext'
import { useI18n } from '../../i18n'
import { assetUsdVersions } from './MenuEdit'
import type {
  ProductionAsset as Asset, ProductionPublish, ProductionSequence,
  ProductionShot, ProductionState, ProductionTask, ProductionTaskDetail,
} from '../../types'
import { TaskDetail } from './TaskDetail'
import { TaskStatusBadge } from './TaskStatusBadge'
import { detailStatus, taskMatchesDepartment, trackingDepartments, trackingTaskStatus } from './tracking'
import { taskColorFromName } from './util'
import type { Selection } from './Production'

interface Props {
  state:              ProductionState
  setState:           (patch: (prev: ProductionState) => ProductionState) => void
  selection:          Selection
  publishesByTask:    Record<string, ProductionPublish[]>
  main?:              React.ReactNode
  workspaceMode?:     'asset' | 'shot'
  timeline?:          React.ReactNode
  settingsPane?:      React.ReactNode
  entityView?:        (entityId: string) => React.ReactNode | null
  loading?:           boolean
  initialOpen?:       { task: string; subtask?: string } | null
  onInitialOpenApplied?: () => void
}

type ResolvedEntity =
  | { kind: 'asset'; entity: Asset }
  | { kind: 'shot';  entity: ProductionShot; seq: ProductionSequence | null }
  | { kind: 'seq';   entity: ProductionSequence }

type Tab =
  | { key: string; kind: 'root' }
  | { key: string; kind: 'timeline' }
  | { key: string; kind: 'settings' }
  | { key: string; kind: 'assets' }                                        // anchored to selection (shot/seq only)
  | { key: string; kind: 'entityRoot'; entityId: string }                  // free-floating tasks-landing for a specific entity
  | { key: string; kind: 'task';    entityId: string; taskId: string }
  | { key: string; kind: 'subtask'; entityId: string; taskId: string; subtask: string }

interface PinnedRef {
  kind:    'task' | 'subtask' | 'entityRoot'
  entityId: string
  taskId?:  string
  subtask?: string
}

const ROOT_TAB:   Tab = { key: 'root',   kind: 'root' }
const ASSETS_TAB: Tab = { key: 'assets', kind: 'assets' }

// Last path segment of a publish's dest_folder (the on-disk instance directory),
// e.g. "$FLUX/…/shading/mari_b_col" -> "MARI_B_COL". This is the source of truth
// for which subtask a publish belongs to: the parsed filename INSTANCE token is
// only a single token and drifts on multi-word or nested instances, whereas the
// folder is exactly the subtask the artist published into.
function publishFolderLeaf(p: ProductionPublish): string {
  const dest = (p.dest_folder || '').replace(/\\/g, '/').replace(/\/+$/, '')
  const leaf = dest.split('/').pop() || ''
  return leaf.toUpperCase()
}

// A publish belongs to *subtask* when its parsed instance matches OR its on-disk
// folder leaf matches — the latter catches instances the filename parser mangles.
function publishMatchesSubtask(p: ProductionPublish, subtask: string): boolean {
  const sub = subtask.toUpperCase()
  return (p.instance || '').toUpperCase() === sub || publishFolderLeaf(p) === sub
}
const taskKey   = (entityId: string, taskId: string) => `task:${entityId}:${taskId}`
const subKey    = (entityId: string, taskId: string, sub: string) => `sub:${entityId}:${taskId}:${sub}`
const entityRootKey = (entityId: string) => `entityRoot:${entityId}`

const pinLsKey = (project: string) => `flux.production.pinned.${project}`

function readPinned(project: string): PinnedRef[] {
  if (!project) return []
  try {
    const raw = localStorage.getItem(pinLsKey(project))
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed
      .map((x: unknown): PinnedRef | null => {
        const p = x as PinnedRef & { assetId?: string }
        if (!p) return null
        const id = p.entityId ?? p.assetId
        if (typeof id !== 'string') return null
        if (p.kind === 'entityRoot') return { kind: 'entityRoot', entityId: id }
        if ((p.kind === 'task' || p.kind === 'subtask') && typeof p.taskId === 'string') {
          return { kind: p.kind, entityId: id, taskId: p.taskId, subtask: p.subtask }
        }
        return null
      })
      .filter((x): x is PinnedRef => x !== null)
  } catch { return [] }
}
function writePinned(project: string, list: PinnedRef[]) {
  if (!project) return
  try { localStorage.setItem(pinLsKey(project), JSON.stringify(list)) } catch { /* blocked */ }
}

// Resolve an id to its concrete entity (asset / shot / seq).
function resolveEntity(state: ProductionState, id: string): ResolvedEntity | null {
  const a = state.assets.find(x => x.id === id)
  if (a) return { kind: 'asset', entity: a }
  const sh = state.shots.find(x => x.id === id)
  if (sh) return { kind: 'shot', entity: sh, seq: state.sequences.find(q => q.id === sh.seq_id) ?? null }
  const sq = state.sequences.find(x => x.id === id)
  if (sq) return { kind: 'seq', entity: sq }
  return null
}

// Adapt a resolved entity into the Asset-shape TaskDetail understands.
function toAssetShim(res: ResolvedEntity): Asset {
  if (res.kind === 'asset') return res.entity
  if (res.kind === 'shot') {
    const s = res.entity
    return {
      id: s.id,
      class: res.seq?.name ?? '',
      name:  s.name,
      group_id: null,
      order: s.order,
      origin: s.origin,
      tasks: s.tasks,
      task_details: s.task_details ?? {},
    }
  }
  const s = res.entity
  return {
    id: s.id,
    class: 'SEQ',
    name:  s.name,
    group_id: null,
    order: s.order,
    origin: s.origin,
    tasks: s.tasks,
    task_details: s.task_details ?? {},
  }
}

type SpecSnapshot = { tabs: Tab[]; activeKey: string; entityId: string | undefined }
const specSessionKey = (project: string) => `prod.specTabs:${project}`

export function MenuSpec({ state, setState, selection, publishesByTask, loading, initialOpen, onInitialOpenApplied, main, timeline, workspaceMode, settingsPane, entityView }: Props) {
  const { t } = useI18n()
  const { project } = useProject()

  // Session snapshot (U3): open tabs come back when returning to Production.
  const snap = useRef(project ? readSession<SpecSnapshot>(specSessionKey(project)) : undefined).current
  const [tabs, setTabs]           = useState<Tab[]>(snap?.tabs ?? [ROOT_TAB])
  const [activeKey, setActiveKey] = useState<string>(snap?.activeKey ?? 'root')
  const previousTab = useRef(activeKey)
  useEffect(() => {
    if (previousTab.current === activeKey) return
    previousTab.current = activeKey
    window.dispatchEvent(new Event('flux:production-tab-change'))
  }, [activeKey])
  const lastEntityRef = useRef<string | undefined>(snap?.entityId)
  const skipPinRestoreRef = useRef(Boolean(snap))
  const previousMode = useRef(workspaceMode)
  useEffect(() => {
    if (previousMode.current === workspaceMode) return
    previousMode.current = workspaceMode
    setActiveKey('root')
  }, [workspaceMode])

  const selectedRes: ResolvedEntity | null = useMemo(() => {
    if (selection.kind === 'asset' || selection.kind === 'shot' || selection.kind === 'seq') {
      return resolveEntity(state, selection.id)
    }
    return null
  }, [selection, state])

  // Anchored tabs (root, assets) are not stored — they are prepended at render
  // time from the current selection. Only free-floating tabs (task/subtask/
  // entityRoot) live in state; those get culled unless pinned when the
  // selection changes.
  useEffect(() => {
    if (!project) return
    const id = selectedRes?.entity.id
    // Store not loaded yet (selection set, entity unresolved) or same entity: keep tabs.
    if (id === undefined && selection.kind !== 'none') return
    if (id === lastEntityRef.current) return
    lastEntityRef.current = id
    if (main) return
    const pinnedKeys = new Set(readPinned(project).map(refToKey))
    setTabs(prev => {
      const kept = prev.filter(tab => tab.kind === 'root' || pinnedKeys.has(tab.key))
      if (kept.length === prev.length) return prev
      if (!kept.some(x => x.key === activeKey)) setActiveKey('root')
      return kept
    })
  }, [selectedRes?.entity.id])   // eslint-disable-line react-hooks/exhaustive-deps

  const showAssetsTab = !main && (selectedRes?.kind === 'shot' || selectedRes?.kind === 'seq')
  const displayedTabs: Tab[] = useMemo(() => {
    const others = tabs.filter(t => t.kind !== 'root' && t.kind !== 'assets' && t.kind !== 'timeline')
    if (main) return [ROOT_TAB, ...(timeline ? [{ key: 'timeline', kind: 'timeline' as const }] : []), ...others]
    return showAssetsTab ? [ROOT_TAB, ASSETS_TAB, ...others] : [ROOT_TAB, ...others]
  }, [tabs, showAssetsTab, main, timeline])

  // If the active tab is 'assets' but the selection loses shot/seq context,
  // fall back to root so the strip stays consistent.
  useEffect(() => {
    if ((activeKey === 'assets' && !showAssetsTab) || (activeKey === 'timeline' && !timeline)) setActiveKey('root')
  }, [showAssetsTab, activeKey, timeline])

  // Restore pinned tabs when the active project changes.
  useEffect(() => {
    if (!project) { setTabs([]); setActiveKey('root'); return }
    if (skipPinRestoreRef.current) { skipPinRestoreRef.current = false; return }   // session snapshot wins
    const pins = readPinned(project)
    const restored: Tab[] = pins.flatMap((p): Tab[] => {
      if (p.kind === 'entityRoot') {
        return [{ key: entityRootKey(p.entityId), kind: 'entityRoot', entityId: p.entityId }]
      }
      if (!p.taskId) return []
      if (p.kind === 'subtask' && p.subtask) {
        return [{ key: subKey(p.entityId, p.taskId, p.subtask), kind: 'subtask', entityId: p.entityId, taskId: p.taskId, subtask: p.subtask }]
      }
      return [{ key: taskKey(p.entityId, p.taskId), kind: 'task', entityId: p.entityId, taskId: p.taskId }]
    })
    setTabs(restored)
    setActiveKey('root')
  }, [project])

  useEffect(() => {
    if (project) writeSession<SpecSnapshot>(specSessionKey(project), { tabs, activeKey, entityId: lastEntityRef.current })
  }, [project, tabs, activeKey, selectedRes?.entity.id])

  // Garbage-collect tabs pointing at a removed entity/task.
  //
  // CRITICAL: never run against a not-yet-loaded store. On (re)mount the parent
  // starts at an EMPTY_STATE with loading=false for one commit before its fetch
  // flips loading→true; this child effect fires first, so without this guard it
  // would "resolve" every pinned entity as missing and rewrite localStorage to
  // [] — silently wiping valid pins on every visit to the Production tab. An
  // empty store means "not loaded" (a genuinely empty project has nothing to GC
  // anyway), so we skip entirely rather than prune.
  useEffect(() => {
    if (loading) return
    const hasData = state.assets.length > 0 || state.shots.length > 0 || state.sequences.length > 0
    if (!hasData) return
    setTabs(prev => {
      const kept = prev.filter(tab => {
        if (tab.kind === 'root' || tab.kind === 'assets' || tab.kind === 'timeline' || tab.kind === 'settings') return true
        const res = resolveEntity(state, tab.entityId)
        if (!res) return false
        if (tab.kind === 'entityRoot') return true
        return res.entity.tasks.some(x => x.id === tab.taskId)
      })
      if (kept.length !== prev.length) {
        if (project) {
          const stillPinned = readPinned(project).filter(p => {
            const res = resolveEntity(state, p.entityId)
            if (!res) return false
            if (p.kind === 'entityRoot') return true
            return res.entity.tasks.some(x => x.id === p.taskId)
          })
          writePinned(project, stillPinned)
        }
        if (!kept.some(x => x.key === activeKey)) setActiveKey('root')
      }
      return kept
    })
  }, [state, project, loading])   // eslint-disable-line react-hooks/exhaustive-deps

  // Consume external deep-link (fav row click) — asset-only for now.
  useEffect(() => {
    if (!initialOpen) return
    if (initialOpen.task === 'SETTINGS') {
      setTabs(prev => prev.some(t => t.kind === 'settings') ? prev : [...prev, { key: 'settings', kind: 'settings' }])
      setActiveKey('settings'); onInitialOpenApplied?.(); return
    }
    if (!selectedRes) return
    if (initialOpen.task.toUpperCase() === 'ENTITY') {
      openEntityRootTab(selectedRes.entity.id)
      onInitialOpenApplied?.()
      return
    }
    // "USD": the asset's tasks landing with its "USD assemble" task open (USD page link).
    if (initialOpen.task.toUpperCase() === 'USD') {
      try { sessionStorage.setItem(USD_OPEN_KEY, selectedRes.entity.name) } catch { /* blocked */ }
      if (main) openEntityRootTab(selectedRes.entity.id)
      else setActiveKey('root')
      onInitialOpenApplied?.()
      return
    }
    const target = selectedRes.entity.tasks.find(x => x.name.toUpperCase() === initialOpen.task.toUpperCase())
    if (!target) return
    const entityId = selectedRes.entity.id
    if (initialOpen.subtask) {
      const key = subKey(entityId, target.id, initialOpen.subtask.toUpperCase())
      setTabs(prev => (prev.some(x => x.key === key) ? prev : [...prev, {
        key, kind: 'subtask', entityId, taskId: target.id, subtask: initialOpen.subtask!.toUpperCase(),
      }]))
      setActiveKey(key)
    } else {
      const key = taskKey(entityId, target.id)
      setTabs(prev => (prev.some(x => x.key === key) ? prev : [...prev, {
        key, kind: 'task', entityId, taskId: target.id,
      }]))
      setActiveKey(key)
    }
    onInitialOpenApplied?.()
  }, [initialOpen, selectedRes])   // eslint-disable-line react-hooks/exhaustive-deps

  // Tab management helpers
  // One tab per task (2026-09-26): opening a subtask, or the whole task, reuses the
  // tab of that task when one is open (same place, pin kept) and switches what it shows.
  const showTaskTab = (entityId: string, taskId: string, subtask: string | null) => {
    const next: Tab = subtask
      ? { key: subKey(entityId, taskId, subtask), kind: 'subtask', entityId, taskId, subtask }
      : { key: taskKey(entityId, taskId), kind: 'task', entityId, taskId }
    // A pinned tab of the task is never repurposed (2026-09-26): the same subtask
    // just goes to it, another one opens a second tab of the task.
    const pinned = new Set(project ? readPinned(project).map(refToKey) : [])
    setTabs(prev => {
      if (prev.some(x => x.key === next.key)) return prev
      const i = prev.findIndex(x => (x.kind === 'task' || x.kind === 'subtask')
        && x.entityId === entityId && x.taskId === taskId && !pinned.has(x.key))
      if (i < 0) return [...prev, next]
      const out = prev.slice()
      out[i] = next
      return out
    })
    setActiveKey(next.key)
  }
  const openTaskTab = (entityId: string, taskId: string) => showTaskTab(entityId, taskId, null)
  const openSubtaskTab = (entityId: string, taskId: string, subtask: string) => showTaskTab(entityId, taskId, subtask)
  const openEntityRootTab = (entityId: string) => {
    const key = entityRootKey(entityId)
    setTabs(prev => (prev.some(x => x.key === key) ? prev : [...prev, { key, kind: 'entityRoot', entityId }]))
    setActiveKey(key)
  }
  const closeTab = (key: string) => {
    setTabs(prev => {
      const next = prev.filter(x => x.key !== key)
      if (activeKey === key) {
        const idx = prev.findIndex(x => x.key === key)
        const fallback = next[Math.max(0, idx - 1)]?.key ?? 'root'
        setActiveKey(fallback)
      }
      return next
    })
    if (project) writePinned(project, readPinned(project).filter(p => refToKey(p) !== key))
  }
  const reorderTab = (fromKey: string, toKey: string) => {
    if (fromKey === toKey) return
    setTabs(prev => {
      const from = prev.findIndex(x => x.key === fromKey)
      const to   = prev.findIndex(x => x.key === toKey)
      if (from < 0 || to < 0) return prev
      const src = prev[from]
      if (src.kind === 'root' || src.kind === 'assets' || src.kind === 'timeline' || src.kind === 'settings') return prev
      const next = prev.slice()
      next.splice(from, 1)
      const insertAt = Math.max(1, next.findIndex(x => x.key === toKey))
      next.splice(insertAt, 0, src)
      return next
    })
  }

  const isPinned = (key: string): boolean => {
    if (!project) return false
    return readPinned(project).some(p => refToKey(p) === key)
  }
  const togglePin = (tab: Tab) => {
    if (!project || tab.kind === 'root' || tab.kind === 'assets' || tab.kind === 'timeline' || tab.kind === 'settings') return
    const cur = readPinned(project)
    const ref: PinnedRef =
      tab.kind === 'entityRoot'
        ? { kind: 'entityRoot', entityId: tab.entityId }
        : tab.kind === 'subtask'
          ? { kind: 'subtask', entityId: tab.entityId, taskId: tab.taskId, subtask: tab.subtask }
          : { kind: 'task',    entityId: tab.entityId, taskId: tab.taskId }
    const key = refToKey(ref)
    const next = cur.some(p => refToKey(p) === key)
      ? cur.filter(p => refToKey(p) !== key)
      : [...cur, ref]
    writePinned(project, next)
    setTabs(prev => [...prev])
  }

  const active = displayedTabs.find(x => x.key === activeKey) ?? ROOT_TAB

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, minWidth: 0 }}>
      <div role="tablist" aria-label="Onglets de production" style={{
        display: 'flex', alignItems: 'flex-end',
        padding: '2px 6px 0',
        borderBottom: '1px solid var(--rule)', background: 'var(--paper)',
        overflowX: 'auto', flexShrink: 0,
      }}>
        {displayedTabs.map((tab, i) => (
          <TabChip
            key={tab.key}
            tab={tab}
            entityTable={Boolean(entityView)}
            rootLabel={main ? 'Main' : undefined}
            state={state}
            selectedRes={selectedRes}
            active={tab.key === activeKey}
            pinned={isPinned(tab.key)}
            onSelect={() => setActiveKey(tab.key)}
            onClose={() => closeTab(tab.key)}
            onTogglePin={() => togglePin(tab)}
            onReorder={(fromKey, toKey) => reorderTab(fromKey, toKey)}
            index={i}
          />
        ))}
      </div>

      {main && <div style={{ display: active.kind === 'root' ? 'flex' : 'none', flex: 1, minHeight: 0, minWidth: 0, flexDirection: 'column' }}>{main}</div>}
      {timeline && <div style={{ display: active.kind === 'timeline' ? 'flex' : 'none', flex: 1, minHeight: 0, minWidth: 0, flexDirection: 'column' }}>{timeline}</div>}
      {active.kind === 'root' && !main && (
        selectedRes
          ? <TasksLanding
              res={selectedRes}
              state={state}
              setState={setState}
              publishesByTask={publishesByTask}
              onOpenTask={(taskId) => openTaskTab(selectedRes.entity.id, taskId)}
              onOpenSubtask={(taskId, sub) => openSubtaskTab(selectedRes.entity.id, taskId, sub)}
            />
          : <div style={_hint}>{t('prod.selectEntity')}</div>
      )}
      {active.kind === 'assets' && selectedRes && (selectedRes.kind === 'shot' || selectedRes.kind === 'seq') && (
        <AssetsLanding
          state={state}
          entity={selectedRes.entity as ProductionShot | ProductionSequence}
          entityKind={selectedRes.kind}
          seqOfShot={selectedRes.kind === 'shot' ? selectedRes.seq : null}
          onOpenAsset={(assetId) => openEntityRootTab(assetId)}
        />
      )}
      {displayedTabs.some(tab => tab.kind === 'settings') && <div style={{ display: active.kind === 'settings' ? 'flex' : 'none', flex: 1, minHeight: 0, minWidth: 0, flexDirection: 'column' }}>{settingsPane}</div>}
      {active.kind === 'entityRoot' && (() => {
        const res = resolveEntity(state, active.entityId)
        if (!res) return <div style={_hint}>Entité introuvable</div>
        const view = entityView?.(active.entityId)
        if (view) return view
        return (
          <TasksLanding
            res={res}
            state={state}
            setState={setState}
            publishesByTask={publishesByTask}
            onOpenTask={(taskId) => openTaskTab(res.entity.id, taskId)}
            onOpenSubtask={(taskId, sub) => openSubtaskTab(res.entity.id, taskId, sub)}
          />
        )
      })()}
      {(active.kind === 'task' || active.kind === 'subtask') && (() => {
        const res = resolveEntity(state, active.entityId)
        if (!res) return <div style={_hint}>Entité introuvable</div>
        const task = res.entity.tasks.find(x => x.id === active.taskId)
        if (!task) return <div style={_hint}>Tâche introuvable</div>
        const shim = toAssetShim(res)
        const bucket = publishesByTask[`${res.entity.id}|${task.id}`] || []
        const department = trackingDepartments(state, res.kind === 'asset' ? 'asset' : 'shot').find(d => taskMatchesDepartment(task, d))
        const subtask = active.kind === 'subtask' ? active.subtask : ''
        const subdetail = shim.task_details?.[`${task.name.toUpperCase()}|${subtask.toUpperCase()}`]
        const status = department ? subtask
          ? subdetail?.status === '' ? '' : department.fixed || subdetail?.status || (subdetail?.completion ?? 0) > 0 ? detailStatus(subdetail) : ''
          : trackingTaskStatus(shim, task, department) : undefined
        const statusBadge = <TaskStatusBadge project={project || ''} state={state} setState={setState} entity={res.entity} task={task} subtask={subtask} statuses={department?.statuses} status={status} />
        const renderHeader = (actions: React.ReactNode) => <TaskStrip
          task={task} asset={shim}
          activeSub={active.kind === 'subtask' ? active.subtask : null}
          publishCount={bucket.length}
          onOpenTask={() => openTaskTab(res.entity.id, task.id)}
          onOpenSubtask={sub => openSubtaskTab(res.entity.id, task.id, sub)}
          actions={actions}
        />
        if (active.kind === 'task') {
          return (
            <TaskDetail
              asset={shim} task={task}
              headerActions={statusBadge}
              renderHeader={renderHeader}
              entityKind={res.kind}
              subtaskFilter={null}
              detailKey={task.name}
              publishes={bucket}
              pinned={isPinned(active.key)}
              onTogglePin={() => togglePin(active)}
              onPatchTask={patch => patchEntityTask(setState, res, task.id, patch)}
              onPatchDetail={patch => patchEntityDetail(setState, res, task.name, patch)}
            />
          )
        }
        return (
          <TaskDetail
            asset={shim} task={task}
            entityKind={res.kind}
            headerActions={statusBadge}
            renderHeader={renderHeader}
            subtaskFilter={active.subtask}
            detailKey={`${task.name}|${active.subtask}`}
            publishes={bucket.filter(p => publishMatchesSubtask(p, active.subtask))}
            pinned={isPinned(active.key)}
            onTogglePin={() => togglePin(active)}
            onPatchTask={patch => patchEntityTask(setState, res, task.id, patch)}
            onPatchDetail={patch => patchEntityDetail(setState, res, `${task.name}|${active.subtask}`, patch)}
          />
        )
      })()}
    </div>
  )
}

// ── tab chip ────────────────────────────────────────────────────────────────
function TabChip({ tab, state, selectedRes, active, pinned, onSelect, onClose, onTogglePin, onReorder, index, rootLabel, entityTable }: {
  entityTable?:   boolean
  rootLabel?:     string
  tab:            Tab
  state:          ProductionState
  selectedRes:    ResolvedEntity | null
  active:         boolean
  pinned:         boolean
  onSelect:       () => void
  onClose:        () => void
  onTogglePin:    () => void
  onReorder:      (fromKey: string, toKey: string) => void
  index:          number
}) {
  const { label, color, sub } = useMemo(() => {
    if (tab.kind === 'settings') return { label: 'Settings', color: 'var(--accent)', sub: '' }
    if (tab.kind === 'timeline') return { label: 'Timeline', color: 'var(--accent)', sub: '' }
    if (tab.kind === 'root') {
      if (rootLabel) return { label: rootLabel, color: 'var(--accent)', sub: '' }
      if (!selectedRes) return { label: 'Tasks', color: 'var(--accent)', sub: '' }
      const shim = toAssetShim(selectedRes)
      return {
        label: `${shim.class}${shim.class ? ' · ' : ''}${shim.name}`,
        color: 'var(--accent)', sub: '',
      }
    }
    if (tab.kind === 'assets') {
      const n = selectedRes && (selectedRes.kind === 'shot' || selectedRes.kind === 'seq')
        ? (selectedRes.entity.assets?.length ?? 0) : 0
      return { label: `ASSETS · ${n}`, color: 'var(--prod-shot)', sub: '' }
    }
    if (tab.kind === 'entityRoot') {
      const res = resolveEntity(state, tab.entityId)
      const shim = res ? toAssetShim(res) : null
      return {
        label: shim ? `${shim.class}${shim.class ? ' · ' : ''}${shim.name}` : '—',
        color: 'var(--accent)', sub: entityTable && res && res.kind !== 'seq' ? res.kind : 'tasks',
      }
    }
    const res = resolveEntity(state, tab.entityId)
    const shim = res ? toAssetShim(res) : null
    const tk = res?.entity.tasks.find(x => x.id === tab.taskId)
    const name = tk?.name ?? '—'
    return {
      label: shim ? `${shim.name} · ${name}` : name,
      color: taskColorFromName(name),
      sub: tab.kind === 'subtask' ? tab.subtask : '',
    }
  }, [tab, state, selectedRes, rootLabel, entityTable])

  const draggable = tab.kind !== 'root' && tab.kind !== 'assets' && tab.kind !== 'timeline' && tab.kind !== 'settings'
  const closable = tab.kind !== 'root' && tab.kind !== 'assets' && tab.kind !== 'timeline'
  const pinnable = tab.kind !== 'root' && tab.kind !== 'assets' && tab.kind !== 'timeline' && tab.kind !== 'settings'
  const [dragOver, setDragOver] = useState(false)

  return (
    <div
      role="tab"
      aria-selected={active}
      tabIndex={0}
      onKeyDown={e => { if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); onSelect() } }}
      onClick={onSelect}
      draggable={draggable}
      onDragStart={e => {
        if (!draggable) return
        e.dataTransfer.effectAllowed = 'move'
        e.dataTransfer.setData('text/flux-tab-key', tab.key)
      }}
      onDragOver={e => {
        if (!e.dataTransfer.types.includes('text/flux-tab-key')) return
        if (!draggable) return
        e.preventDefault(); e.dataTransfer.dropEffect = 'move'
        setDragOver(true)
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={e => {
        setDragOver(false)
        const from = e.dataTransfer.getData('text/flux-tab-key')
        if (from && from !== tab.key && draggable) {
          e.preventDefault(); e.stopPropagation()
          onReorder(from, tab.key)
        }
      }}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 6,
        padding: '6px 12px 5px',
        marginRight: 2, marginBottom: -1,
        borderTopLeftRadius: 8, borderTopRightRadius: 8,
        borderTop: `3px solid ${active ? color : 'transparent'}`,
        borderLeft: '1px solid var(--rule)',
        borderRight: '1px solid var(--rule)',
        borderBottom: active ? '1px solid var(--paper-2)' : '1px solid var(--rule)',
        background: active
          ? 'var(--paper-2)'
          : dragOver ? 'color-mix(in oklch, var(--accent) 12%, transparent)' : 'var(--paper)',
        color: active ? 'var(--ink)' : 'var(--ink-3)',
        cursor: draggable ? 'grab' : 'pointer',
        userSelect: 'none',
        fontFamily: 'var(--sans)', fontSize: 11, fontWeight: active ? 600 : 500,
        flex: (tab.kind === 'root' || tab.kind === 'assets' || tab.kind === 'timeline' || tab.kind === 'settings') ? '0 0 auto' : '1 1 100px',
        minWidth: (tab.kind === 'root' || tab.kind === 'assets' || tab.kind === 'timeline' || tab.kind === 'settings') ? undefined : 70,
        maxWidth: (tab.kind === 'root' || tab.kind === 'assets' || tab.kind === 'timeline' || tab.kind === 'settings') ? undefined : 200,
        minHeight: 0, overflow: 'hidden',
        position: 'relative', zIndex: active ? 2 : 1,
      }}
      title={label + (sub ? ` · ${sub}` : '')}
    >
      {tab.kind !== 'root' && tab.kind !== 'assets' && tab.kind !== 'timeline' && (
        <span style={{ width: 6, height: 6, borderRadius: '50%', background: color, flexShrink: 0 }} />
      )}
      <span style={{
        fontFamily: 'var(--sans)', fontSize: 11, letterSpacing: '0.02em',
        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        flex: '1 1 auto', minWidth: 0,
      }}>
        {label}{sub ? ` · ${sub}` : ''}
      </span>
      {pinnable && (
        <button
          onClick={e => { e.stopPropagation(); onTogglePin() }}
          title={pinned ? 'Désépingler' : 'Épingler'}
          style={{
            width: 15, height: 15, borderRadius: 3, border: 'none',
            background: 'transparent',
            color: pinned ? 'var(--accent-hi)' : 'var(--ink-4)',
            cursor: 'pointer', flexShrink: 0,
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          <Pin size={9} strokeWidth={2} fill={pinned ? 'var(--accent)' : 'none'} />
        </button>
      )}
      {closable && (
        <button
          onClick={e => { e.stopPropagation(); onClose() }}
          title="Fermer"
          style={{
            width: 15, height: 15, borderRadius: 3, border: 'none',
            background: 'transparent', color: 'var(--ink-3)', cursor: 'pointer',
            flexShrink: 0,
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          <X size={9} strokeWidth={2} />
        </button>
      )}
      <span style={{ display: 'none' }}>{index}</span>
    </div>
  )
}

// ── assets landing (for shot/seq: chips grouped by category) ────────────────
function AssetsLanding({ state, entity, entityKind, seqOfShot, onOpenAsset }: {
  state:       ProductionState
  entity:      ProductionShot | ProductionSequence
  entityKind:  'shot' | 'seq'
  seqOfShot:   ProductionSequence | null
  onOpenAsset: (assetId: string) => void
}) {
  // For a shot with inherit_assets, present the seq's assets as inherited.
  const own = entity.assets ?? []
  const inherited = useMemo(() => {
    if (entityKind !== 'shot') return []
    const s = entity as ProductionShot
    if (!s.inherit_assets || !seqOfShot) return []
    const ownIds = new Set(own.map(x => x.id))
    return (seqOfShot.assets ?? []).filter(x => !ownIds.has(x.id))
  }, [entityKind, entity, seqOfShot, own])

  const buckets = useMemo(() => {
    // Merge own + inherited (tagged) into a class → items map.
    const m = new Map<string, Array<{ asset: Asset; inherited: boolean }>>()
    const push = (id: string, inh: boolean) => {
      const a = state.assets.find(x => x.id === id)
      if (!a) return
      const cls = a.class.toUpperCase()
      const arr = m.get(cls) ?? []
      arr.push({ asset: a, inherited: inh })
      m.set(cls, arr)
    }
    for (const l of own) push(l.id, false)
    for (const l of inherited) push(l.id, true)
    for (const arr of m.values()) arr.sort((a, b) => a.asset.name.localeCompare(b.asset.name))
    return m
  }, [own, inherited, state.assets])

  // Pinned USD version per asset id (ADR 0048): the shot's pin wins over the sequence's.
  const { t } = useI18n()
  const { project } = useProject()
  const pins = useMemo(() => {
    const out = new Map<string, string>()
    const seqLinks = entityKind === 'shot' && (entity as ProductionShot).inherit_assets ? (seqOfShot?.assets ?? []) : []
    for (const l of seqLinks) if (l.version) out.set(l.id, l.version)
    for (const l of own) if (l.version) out.set(l.id, l.version)
    return out
  }, [entityKind, entity, seqOfShot, own])
  // Newest published version of each pinned asset, to signal a newer one.
  const [newest, setNewest] = useState<Record<string, string>>({})
  useEffect(() => {
    if (!project) return
    let alive = true
    for (const id of pins.keys()) {
      const a = state.assets.find(x => x.id === id)
      if (!a) continue
      assetUsdVersions(project, a.name).then(vs => {
        if (alive && vs.length) setNewest(prev => ({ ...prev, [id]: vs[vs.length - 1] }))
      })
    }
    return () => { alive = false }
  }, [project, pins, state.assets])

  const total = own.length + inherited.length
  if (total === 0) {
    return (
      <div style={{ flex: 1, overflowY: 'auto', padding: '18px 20px', color: 'var(--ink-4)', fontSize: 11 }}>
        Aucun asset lié à ce {entityKind === 'shot' ? 'shot' : 'seq'}. Ajoute-en depuis le menu Edit.
      </div>
    )
  }

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '14px 18px' }}>
      {[...buckets.entries()].map(([cls, arr]) => {
        // classColor: use categoryColor from util, but we don't have direct import here.
        // Fallback to a class-based CSS var if available.
        const color = classColor(cls)
        return (
          <div key={cls} style={{ marginBottom: 14 }}>
            <div style={{
              display: 'inline-flex', alignItems: 'center', gap: 6, marginBottom: 8,
              padding: '3px 10px', borderRadius: 5,
              background: color, color: 'var(--paper)',
              fontFamily: 'var(--mono)', fontSize: 10.5, letterSpacing: '0.08em',
            }}>
              <span style={{ width: 5, height: 5, borderRadius: '50%', background: 'var(--paper)' }} />
              {cls}
              <span style={{ opacity: 0.75 }}>· {arr.length}</span>
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {arr.map(({ asset, inherited: inh }) => (
                <button
                  key={asset.id}
                  onClick={() => onOpenAsset(asset.id)}
                  title={inh ? `${asset.class}/${asset.name} (hérité de ${seqOfShot?.name ?? 'seq'})` : `${asset.class}/${asset.name}`}
                  style={{
                    display: 'inline-flex', alignItems: 'center', gap: 6,
                    padding: '7px 14px', borderRadius: 10,
                    background: color, color: 'var(--paper)',
                    border: `1px ${inh ? 'dashed' : 'solid'} ${color}`,
                    opacity: inh ? 0.8 : 1,
                    fontFamily: 'var(--sans)', fontSize: 12, fontWeight: 600,
                    cursor: 'pointer',
                    boxShadow: '0 2px 6px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,0.15)',
                    transition: 'transform 0.12s',
                  }}
                  onMouseEnter={e => (e.currentTarget.style.transform = 'scale(1.04)')}
                  onMouseLeave={e => (e.currentTarget.style.transform = 'scale(1)')}
                >
                  {asset.name}
                  {inh && (
                    <span style={{
                      fontSize: 10, padding: '1px 5px', borderRadius: 3,
                      background: 'rgba(0,0,0,0.25)', letterSpacing: '0.05em',
                    }}>hérité</span>
                  )}
                  {(() => {
                    const pin = pins.get(asset.id)
                    const last = newest[asset.id]
                    const newer = !!(pin && last && parseInt(last.slice(1), 10) > parseInt(pin.slice(1), 10))
                    return (
                      <span title={pin ? (newer ? t('prod.versionNewer').replace('{v}', last) : t('prod.versionPinned').replace('{v}', pin))
                                       : t('prod.versionLast')}
                            style={{
                              fontSize: 10, padding: '1px 5px', borderRadius: 3, letterSpacing: '0.05em',
                              background: pin ? 'var(--paper)' : 'rgba(0,0,0,0.25)',
                              color: pin ? 'var(--ink)' : 'var(--paper)',
                            }}>
                        {pin ? t('prod.versionPinned').replace('{v}', pin) : 'LAST'}
                        {newer && <span style={{ marginLeft: 4, fontWeight: 700 }}>↑ {last}</span>}
                      </span>
                    )
                  })()}
                </button>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// Map CLASS token to its CSS var (mirrors util.categoryColor without importing).
function classColor(cls: string): string {
  switch (cls.toUpperCase()) {
    case 'CHAR':  return 'var(--prod-chara)'
    case 'PROPS': return 'var(--prod-props)'
    case 'ENV':   return 'var(--prod-env)'
    case 'FXRIG': return 'var(--prod-fx)'
    default:      return 'var(--ink-3)'
  }
}

// ── tasks landing (chips with hover-expand) ─────────────────────────────────
function TasksLanding({ res, setState, publishesByTask, onOpenTask, onOpenSubtask }: {
  res:             ResolvedEntity
  state:           ProductionState
  setState:        (patch: (prev: ProductionState) => ProductionState) => void
  publishesByTask: Record<string, ProductionPublish[]>
  onOpenTask:      (taskId: string) => void
  onOpenSubtask:   (taskId: string, subtask: string) => void
}) {
  // For a shot with inherit_tasks, mirror the seq's tasks into shot.tasks as
  // fresh independent copies (idempotent — only adds missing ones by name).
  // Once copied, each task lives on the shot and behaves like any other task.
  useEffect(() => {
    if (res.kind !== 'shot' || !res.entity.inherit_tasks || !res.seq) return
    const shot = res.entity; const seq = res.seq
    const ownNames = new Set(shot.tasks.map(t => t.name.toUpperCase()))
    const missing = seq.tasks.filter(t => !ownNames.has(t.name.toUpperCase()))
    if (missing.length === 0) return
    setState(prev => ({
      ...prev,
      shots: prev.shots.map(s => s.id !== shot.id ? s : {
        ...s,
        tasks: [
          ...s.tasks,
          ...missing.map((t, i) => ({
            id: `t_${Math.random().toString(36).slice(2, 12)}`,
            name: t.name,
            order: s.tasks.length + i,
            type_tokens: [...(t.type_tokens || [])],
            known_subtasks: [...(t.known_subtasks || [])],
            origin: 'auto' as const,
          })),
        ],
      }),
    }))
  }, [res.kind === 'shot' ? res.entity.id : null, res.kind === 'shot' ? res.entity.inherit_tasks : null, res.kind === 'shot' ? res.seq?.tasks.length : null])   // eslint-disable-line react-hooks/exhaustive-deps

  const shim = toAssetShim(res)

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '14px 18px' }}>
      {res.entity.tasks.length === 0 && (
        <div style={{ fontSize: 11, color: 'var(--ink-4)' }}>—</div>
      )}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'flex-start' }}>
        {[...res.entity.tasks].sort((a, b) => a.order - b.order).map(task => (
          <TaskNode
            key={task.id}
            task={task}
            asset={shim}
            publishCount={(publishesByTask[`${res.entity.id}|${task.id}`] || []).length}
            onOpenHeader={() => onOpenTask(task.id)}
            onOpenSubtask={(sub) => onOpenSubtask(task.id, sub)}
            completion={shim.task_details?.[task.name]?.completion ?? 0}
            subtaskCompletions={Object.fromEntries(
              task.known_subtasks.map(s => [s, shim.task_details?.[`${task.name}|${s}`]?.completion ?? 0])
            )}
            inherited={false}
          />
        ))}
        {/* The assembled USD of the asset (component / assembly), 2026-09-26. */}
        {res.kind === 'asset' && <UsdAssembledNode name={res.entity.name} />}
        {/* The Houdini render scene of the sequence (ADR 0036), 2026-09-27. */}
        {res.kind === 'seq' && <SeqRenderSceneNode seq={res.entity.name} />}
      </div>
    </div>
  )
}

// ── "USD assemblé" task: the component or the assembly of the asset ─────────────
const USD_OPEN_KEY = 'flux.production.openUsd'

function UsdAssembledNode({ name }: { name: string }) {
  const { project } = useProject()
  const navigate = useNavigate()
  const [info, setInfo] = useState<UsdAssetInfo | null>(null)
  const [err, setErr] = useState('')
  // Opened unfolded when the USD page sent us here for this asset.
  const [open, setOpen] = useState(() => {
    try {
      if (sessionStorage.getItem(USD_OPEN_KEY) === name) {
        sessionStorage.removeItem(USD_OPEN_KEY)
        return true
      }
    } catch { /* blocked */ }
    return false
  })
  const [busy, setBusy] = useState(false)

  const load = useMemo(() => async () => {
    if (!project || !name) return
    setBusy(true)
    try {
      setInfo(await api.getUsdAsset(project, name))
      setErr('')
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }, [project, name])
  useEffect(() => { void load() }, [load])
  useEffect(() => {
    const h = () => { void load() }
    window.addEventListener('flux:refresh', h)
    return () => window.removeEventListener('flux:refresh', h)
  }, [load])

  const comp = info?.component ?? null
  const asm = info?.assembly ?? null
  const version = comp?.version ?? asm?.version ?? null
  const stateLabel = comp
    ? (comp.state === 'stale' ? 'à régénérer' : comp.state === 'empty' ? 'vide' : 'à jour')
    : asm ? (asm.broken ? `${asm.broken} lien(s) cassé(s)` : 'à jour') : 'non créé'
  const color = 'var(--accent)'
  const line: React.CSSProperties = {
    display: 'flex', alignItems: 'center', gap: 8, minWidth: 0,
    fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-2)', lineHeight: '18px',
  }
  const dim: React.CSSProperties = { color: 'var(--ink-4)', flexShrink: 0 }
  const cut: React.CSSProperties = { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1, minWidth: 0 }

  return (
    <div style={{
      minWidth: open ? 300 : 160, maxWidth: 420, borderRadius: 8,
      border: `1px solid ${open ? color : 'var(--rule-2)'}`,
      background: 'var(--paper-2)', boxShadow: 'var(--shadow-xs)', fontFamily: 'var(--sans)',
      transition: 'min-width 0.22s ease',
    }}>
      <div
        onClick={() => setOpen(o => !o)}
        title="Component / assembly USD de l'asset"
        style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '9px 14px', cursor: 'pointer' }}
      >
        <Layers size={12} strokeWidth={2} style={{ color, flexShrink: 0 }} />
        <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--ink)' }}>USD assemblé</span>
        <span style={{ flex: 1 }} />
        <span style={{
          fontFamily: 'var(--mono)', fontSize: 10.5, fontWeight: 600, padding: '1px 6px', borderRadius: 3,
          background: version ? 'var(--accent-soft)' : 'var(--paper)', color: version ? 'var(--accent-hi)' : 'var(--ink-4)',
        }}>{version ?? '—'}</span>
      </div>
      {open && (
        <div style={{ padding: '0 14px 12px', display: 'flex', flexDirection: 'column', gap: 8 }}>
          {err && <div style={{ fontSize: 11, color: 'var(--err)' }}>{err}</div>}
          {!err && info && !comp && !asm && (
            <div style={{ fontSize: 11, color: 'var(--ink-4)', lineHeight: 1.5 }}>
              Pas encore de component pour {name} : il se crée dans la page USD (Bibliothèque).
            </div>
          )}
          {comp && (
            <div>
              <div style={{ ...line, color: 'var(--ink-3)' }}>
                <span style={{ fontWeight: 600 }}>Component</span>
                <span style={dim}>{comp.version} · {comp.versions.length} version(s) · {stateLabel}</span>
              </div>
              {comp.files.length === 0 && <div style={{ ...line, ...dim }}>aucun département lié</div>}
              {comp.files.map(f => (
                <div key={f.id} style={{ ...line, paddingLeft: 10 }} title={f.base}>
                  <span style={{ width: 52, flexShrink: 0, color: 'var(--accent-hi)' }}>{f.department}</span>
                  <span style={cut}>{f.label || f.base}</span>
                  <span style={{ ...dim, color: f.found ? 'var(--ink-4)' : 'var(--err)' }}>
                    {!f.found ? 'introuvable'
                      : f.composed_version && f.composed_version !== f.resolved_version
                        ? `${f.composed_version} → ${f.resolved_version}` : (f.resolved_version ?? '')}
                  </span>
                </div>
              ))}
              {comp.proposed.length > 0 && (
                <div style={{ ...line, paddingLeft: 10, color: 'var(--warn, var(--ink-3))' }}>
                  <span style={cut}>{comp.proposed.length} publish(s) pas encore dans le component : {comp.proposed.map(p => p.department).join(', ')}</span>
                </div>
              )}
            </div>
          )}
          {asm && (
            <div>
              <div style={{ ...line, color: 'var(--ink-3)' }}>
                <span style={{ fontWeight: 600 }}>Assembly</span>
                <span style={dim}>{asm.version} · {asm.versions.length} version(s) · {asm.instances.length} instance(s) · {stateLabel}</span>
              </div>
            </div>
          )}
          {info && info.used_by.length > 0 && (
            <div style={line}>
              <span style={{ fontWeight: 600, color: 'var(--ink-3)', flexShrink: 0 }}>Utilisé dans</span>
              <span style={cut}>{info.used_by.join(', ')}</span>
            </div>
          )}
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {project && (comp?.last || asm?.file) && (
              <OpenInMenu project={project} relPath={projectRelPath(project, (comp?.last || asm?.file) as string)} />
            )}
            <button onClick={() => navigate('/usd', { state: { openUsd: name } })} style={_miniBtn}>Ouvrir la page USD</button>
            <button onClick={() => { void load() }} disabled={busy} style={{ ..._miniBtn, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              <RefreshCw size={10} strokeWidth={2} />{busy ? 'Lecture…' : 'Relire'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ── "Scène de rendu" of a sequence: <SEQ>_render.hip, opened in Houdini ──────────
// Made by FLUX when the sequence is created; built on the spot when it is missing.
const RENDER_PRESET = 'builtin:sequence_render:'

function SeqRenderSceneNode({ seq }: { seq: string }) {
  const { project } = useProject()
  const [file, setFile] = useState<string | null>(null)
  const [exists, setExists] = useState(false)
  const [busy, setBusy] = useState(false)

  const load = useMemo(() => async () => {
    if (!project || !seq) return
    try {
      const pr = await api.listPresets(project, true)
      const p = pr.presets.find(x => x.id === RENDER_PRESET + seq.toUpperCase())
      setFile(p?.file ?? null)
      setExists(!!p?.exists)
    } catch { setFile(null) }
  }, [project, seq])
  useEffect(() => { void load() }, [load])
  useEffect(() => {
    const h = () => { void load() }
    window.addEventListener('flux:refresh', h)
    return () => window.removeEventListener('flux:refresh', h)
  }, [load])

  const open = async () => {
    if (!project) return
    setBusy(true)
    const id = toast.loading(exists ? `Ouverture de ${file} dans Houdini…` : `Création de la scène de rendu ${seq}…`)
    try {
      const r = await api.launchPreset(project, RENDER_PRESET + seq.toUpperCase(), 'houdini')
      if (r.launched) toast.success(`Houdini lancé · ${r.scene.split(/[\/]/).pop()}`, { id, duration: 4000 })
      else toast.error('Houdini introuvable', { id, duration: 6000 })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e), { id, duration: 6000 })
    } finally {
      setBusy(false)
      void load()
    }
  }

  return (
    <div style={{
      minWidth: 220, maxWidth: 420, borderRadius: 8, border: '1px solid var(--rule-2)',
      background: 'var(--paper-2)', boxShadow: 'var(--shadow-xs)', fontFamily: 'var(--sans)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '9px 14px' }}>
        <Clapperboard size={12} strokeWidth={2} style={{ color: 'var(--accent)', flexShrink: 0 }} />
        <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--ink)' }}>Scène de rendu</span>
        <span style={{ flex: 1 }} />
        <span style={{
          fontFamily: 'var(--mono)', fontSize: 10.5, fontWeight: 600, padding: '1px 6px', borderRadius: 3,
          background: exists ? 'var(--accent-soft)' : 'var(--paper)', color: exists ? 'var(--accent-hi)' : 'var(--ink-4)',
        }}>{exists ? 'prête' : 'à créer'}</span>
      </div>
      <div style={{ padding: '0 14px 12px', display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-3)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
          title={file ?? ''}>{file ?? `${seq}_render.hip`}</div>
        <div style={{ display: 'flex', gap: 6 }}>
          <button onClick={() => { void open() }} disabled={busy || !project} style={_miniBtn}>
            {busy ? (exists ? 'Ouverture…' : 'Création…') : 'Ouvrir dans Houdini'}
          </button>
        </div>
      </div>
    </div>
  )
}

const _miniBtn: React.CSSProperties = {
  padding: '4px 10px', borderRadius: 6, border: '1px solid var(--rule-2)', background: 'var(--paper)',
  color: 'var(--ink-2)', fontFamily: 'var(--sans)', fontSize: 11, cursor: 'pointer',
}

// ── one task node ────────────────────────────────────────────────────────────
function TaskNode({ task, asset, publishCount, onOpenHeader, onOpenSubtask, completion, subtaskCompletions, inherited }: {
  task:               ProductionTask
  asset:              Asset
  publishCount:       number
  onOpenHeader:       () => void
  onOpenSubtask:      (sub: string) => void
  completion:         number
  subtaskCompletions: Record<string, number>
  inherited?:         boolean
}) {
  const [expanded, setExpanded] = useState(false)
  const [hoveredSub, setHoveredSub] = useState<string | null>(null)
  // Collapsed footprint kept in the row while the card is open: the open card floats
  // over its neighbours instead of growing in the flow (2026-09-26: the last card
  // of a full row wrapped to the next line, lost the hover, closed, came back: jitter).
  const [slot, setSlot] = useState<{ w: number; h: number; alignRight: boolean } | null>(null)
  // Right click: whole-task favorite (notifications), 2026-09-26.
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null)
  const fav = useFavoriteBinding(asset, task, null)
  const color = taskColorFromName(task.name)
  const hasSubs = task.known_subtasks.length > 0
  const floating = expanded && !!slot
  const isOpen = expanded

  useEffect(() => {
    if (!menu) return
    const off = () => setMenu(null)
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') setMenu(null) }
    window.addEventListener('click', off)
    window.addEventListener('keydown', key)
    window.addEventListener('scroll', off, true)
    return () => {
      window.removeEventListener('click', off)
      window.removeEventListener('keydown', key)
      window.removeEventListener('scroll', off, true)
    }
  }, [menu])

  const onClickBody: React.MouseEventHandler = (e) => {
    if (inherited) return
    if (!hasSubs) { e.stopPropagation(); onOpenHeader() }
  }

  function open(e: React.MouseEvent<HTMLDivElement>) {
    const r = e.currentTarget.getBoundingClientRect()
    const box = e.currentTarget.parentElement?.getBoundingClientRect()
    // Open towards the left when the widest open card would leave the row on the right.
    setSlot({ w: r.width, h: r.height, alignRight: !!box && r.left + 360 > box.right })
    setExpanded(true)
  }
  function close() { setExpanded(false); setSlot(null) }

  return (
    <div
      onMouseEnter={open}
      onMouseLeave={close}
      onContextMenu={e => { e.preventDefault(); e.stopPropagation(); setMenu({ x: e.clientX, y: e.clientY }) }}
      style={{ position: 'relative', flexShrink: 0,
               ...(floating && slot ? { width: slot.w, height: slot.h, zIndex: 20 } : {}),
               ...(menu ? { zIndex: 30 } : {}) }}
    >
    {menu && (
      <div
        onClick={e => e.stopPropagation()}
        style={{
          position: 'fixed', left: menu.x, top: menu.y, zIndex: 1000, minWidth: 220,
          padding: 4, borderRadius: 8, border: '1px solid var(--rule-2)', background: 'var(--paper-2)',
          boxShadow: 'var(--shadow-md)', fontFamily: 'var(--sans)',
        }}>
        <button style={_menuItem} onClick={() => { void fav.toggle(); setMenu(null) }}>
          <Heart size={12} strokeWidth={1.75} color={fav.isFavorite ? 'var(--accent-hi)' : 'var(--ink-3)'}
                 fill={fav.isFavorite ? 'var(--accent)' : 'none'} />
          {fav.isFavorite ? 'Retirer des favoris' : 'Ajouter aux favoris (notifications)'}
        </button>
        {!inherited && (
          <button style={_menuItem} onClick={() => { setMenu(null); onOpenHeader() }}>
            <Layers size={12} strokeWidth={1.75} color="var(--ink-3)" />
            Ouvrir la tâche
          </button>
        )}
      </div>
    )}
    <div
      onClick={onClickBody}
      style={{
        ...(floating && slot ? { position: 'absolute', top: 0, ...(slot.alignRight ? { right: 0 } : { left: 0 }) } : {}),
        minWidth: isOpen ? Math.max(220, slot?.w ?? 0) : 160,
        maxWidth: 360,
        padding: isOpen ? '10px 12px 12px' : '9px 14px',
        borderRadius: 8,
        border: `1px solid color-mix(in oklch, ${color} 70%, black 20%)`,
        // Solid fill but visibly duller than the subtask chips below.
        background: `color-mix(in oklch, ${color} 58%, var(--paper-2) 42%)`,
        color: 'var(--paper)',
        opacity: inherited && !isOpen ? 0.85 : 1,
        boxShadow: floating ? 'var(--shadow-md)' : 'var(--shadow-xs)',
        cursor: inherited ? 'default' : (hasSubs ? 'default' : 'pointer'),
        transition: 'min-width 0.22s ease, padding 0.22s ease',
        fontFamily: 'var(--sans)',
      }}
    >
      <div
        onClick={(e) => { if (inherited) return; e.stopPropagation(); onOpenHeader() }}
        style={{
          display: 'flex', alignItems: 'center', gap: 8,
          cursor: inherited ? 'default' : 'pointer',
          paddingBottom: isOpen ? 6 : 0,
        }}
        title={inherited ? 'Hérité de la séquence' : 'Ouvrir la tâche (tous les subtasks). Clic droit : favoris'}
      >
        <span style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--paper)', flexShrink: 0, opacity: 0.9 }} />
        <span style={{ fontFamily: 'var(--sans)', fontSize: 12, fontWeight: 600, color: 'var(--paper)' }}>{task.name}</span>
        {inherited && (
          <span style={{
            fontFamily: 'var(--sans)', fontSize: 10.5, fontWeight: 500,
            padding: '1px 6px', borderRadius: 3,
            background: 'rgba(255,255,255,0.18)', color: 'var(--paper)',
          }}>hérité</span>
        )}
        <span style={{ flex: 1 }} />
        {fav.isFavorite && (
          <Heart size={11} strokeWidth={1.75} color="var(--paper)" fill="var(--paper)" style={{ flexShrink: 0 }} />
        )}
        {publishCount > 0 && (
          <span style={{
            fontFamily: 'var(--sans)', fontSize: 10.5, fontWeight: 600,
            padding: '1px 6px', borderRadius: 3,
            background: 'rgba(0,0,0,0.3)', color: 'var(--paper)',
          }}>{publishCount}</span>
        )}
      </div>

      <div style={{
        height: isOpen ? 5 : 3, marginTop: isOpen ? 8 : 6, borderRadius: 3,
        background: 'rgba(0,0,0,0.28)',
        overflow: 'hidden', transition: 'height 0.2s',
      }}>
        <div style={{
          width: `${Math.max(0, Math.min(100, completion))}%`, height: '100%',
          background: 'var(--accent)', transition: 'width 0.25s',
        }} />
      </div>

      {isOpen && hasSubs && (
        <div style={{
          marginTop: 10,
          display: 'grid',
          gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
          gap: 8,
        }}>
          {task.known_subtasks.map(sub => {
            const subDone = subtaskCompletions[sub] ?? 0
            const isHovered = hoveredSub === sub
            return (
              <div
                key={sub}
                onMouseEnter={() => setHoveredSub(sub)}
                onMouseLeave={() => setHoveredSub(prev => (prev === sub ? null : prev))}
                style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0 }}
              >
                <button
                  onClick={(e) => { if (inherited) return; e.stopPropagation(); onOpenSubtask(sub) }}
                  style={{
                    display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 5,
                    padding: '5px 10px', borderRadius: 6,
                    border: `1px solid color-mix(in oklch, ${color} 75%, black 25%)`,
                    background: color, color: 'var(--paper)',
                    fontFamily: 'var(--sans)', fontSize: 11, fontWeight: 600,
                    cursor: inherited ? 'default' : 'pointer',
                    transition: 'filter 0.12s',
                    minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}
                >
                  {sub}
                </button>
                <div style={{
                  height: 3, borderRadius: 2, width: '100%',
                  background: 'color-mix(in oklch, var(--paper) 60%, transparent)',
                  overflow: 'hidden',
                  opacity: isHovered ? 1 : 0,
                  transition: 'opacity 0.15s',
                }}>
                  <div style={{
                    width: `${Math.max(0, Math.min(100, subDone))}%`, height: '100%',
                    background: color, transition: 'width 0.25s',
                  }} />
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
    </div>
  )
}

// ── task strip: thin bar on top of a task tab ───────────────────────────────
function TaskStrip({ task, activeSub, publishCount, onOpenTask, onOpenSubtask, actions }: {
  task:          ProductionTask
  asset:         Asset
  actions:       React.ReactNode
  activeSub:     string | null
  publishCount:  number
  onOpenTask:    () => void
  onOpenSubtask: (sub: string) => void
}) {
  const color = taskColorFromName(task.name)
  const chip = (label: string, on: boolean, onClick: () => void, title?: string) => (
    <button key={label} onClick={onClick} title={title}
      style={{
        flexShrink: 0, padding: '3px 9px', borderRadius: 5, cursor: 'pointer',
        fontFamily: 'var(--sans)', fontSize: 11, fontWeight: 600, whiteSpace: 'nowrap',
        border: on ? '1px solid var(--paper)' : `1px solid color-mix(in oklch, ${color} 70%, black 25%)`,
        background: on ? color : `color-mix(in oklch, ${color} 45%, var(--paper-2) 55%)`,
        color: 'var(--paper)',
      }}>{label}</button>
  )
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0,
      padding: '6px 14px', flexWrap: 'wrap', borderBottom: '1px solid var(--rule)',
      background: `color-mix(in oklch, ${color} 14%, var(--paper) 86%)`,
    }}>
      <span style={{ width: 7, height: 7, borderRadius: '50%', background: color, flexShrink: 0 }} />
      <span style={{ fontFamily: 'var(--sans)', fontSize: 12, fontWeight: 600, color: 'var(--ink)', flexShrink: 0 }}>{task.name}</span>
      {publishCount > 0 && (
        <span style={{ fontFamily: 'var(--mono)', fontSize: 10.5, color: 'var(--ink-3)', flexShrink: 0 }}>{publishCount}</span>
      )}
      {task.known_subtasks.length > 0 && (
        <>
          <span style={{ width: 1, alignSelf: 'stretch', background: 'var(--rule-2)', flexShrink: 0 }} />
          <div
            onWheel={e => { if (e.deltaY && !e.deltaX) e.currentTarget.scrollLeft += e.deltaY }}
            className="chip-row" style={{ gap: 5, flex: 1 }}>
            {chip('Tout', activeSub === null, onOpenTask, 'La tâche entière')}
            {task.known_subtasks.map(sub => chip(sub, sub === activeSub, () => onOpenSubtask(sub)))}
          </div>
        </>
      )}
      <span style={{ flex: 1 }} />
      {actions}
    </div>
  )
}

const _menuItem: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 8, width: '100%', padding: '6px 10px',
  border: 'none', borderRadius: 5, background: 'transparent', color: 'var(--ink)',
  fontFamily: 'var(--sans)', fontSize: 11, textAlign: 'left', cursor: 'pointer',
}

// ── helpers ──────────────────────────────────────────────────────────────────
function refToKey(p: PinnedRef): string {
  if (p.kind === 'entityRoot') return entityRootKey(p.entityId)
  if (p.kind === 'subtask' && p.subtask && p.taskId) return subKey(p.entityId, p.taskId, p.subtask)
  return taskKey(p.entityId, p.taskId ?? '')
}

function patchEntityTask(
  setState: (patch: (prev: ProductionState) => ProductionState) => void,
  res: ResolvedEntity, taskId: string, patch: Partial<ProductionTask>,
) {
  setState(prev => {
    const mapTasks = (tasks: ProductionTask[]) => tasks.map(x => x.id === taskId ? { ...x, ...patch } : x)
    if (res.kind === 'asset') {
      return { ...prev, assets: prev.assets.map(a => a.id === res.entity.id ? { ...a, tasks: mapTasks(a.tasks) } : a) }
    }
    if (res.kind === 'shot') {
      return { ...prev, shots: prev.shots.map(s => s.id === res.entity.id ? { ...s, tasks: mapTasks(s.tasks) } : s) }
    }
    return { ...prev, sequences: prev.sequences.map(s => s.id === res.entity.id ? { ...s, tasks: mapTasks(s.tasks) } : s) }
  })
}

function patchEntityDetail(
  setState: (patch: (prev: ProductionState) => ProductionState) => void,
  res: ResolvedEntity, key: string, patch: Partial<ProductionTaskDetail>,
) {
  setState(prev => {
    const merge = (details: Record<string, ProductionTaskDetail> | undefined) => ({
      ...(details || {}),
      [key]: { ...(details?.[key] || {}), ...patch },
    })
    if (res.kind === 'asset') {
      return { ...prev, assets: prev.assets.map(a => a.id === res.entity.id ? { ...a, task_details: merge(a.task_details) } : a) }
    }
    if (res.kind === 'shot') {
      return { ...prev, shots: prev.shots.map(s => s.id === res.entity.id ? { ...s, task_details: merge(s.task_details) } : s) }
    }
    return { ...prev, sequences: prev.sequences.map(s => s.id === res.entity.id ? { ...s, task_details: merge(s.task_details) } : s) }
  })
}

const _hint: React.CSSProperties = {
  flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
  color: 'var(--ink-4)', fontSize: 11,
}
