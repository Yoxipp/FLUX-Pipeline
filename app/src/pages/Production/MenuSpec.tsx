// MenuSpec — Houdini-style tabbed spec panel.
//
// Tab layout:  [Tasks | <asset · task N> | <asset · task · subtask K> | …]
//
// - The first tab is always "Tasks" and shows the CURRENTLY SELECTED asset's
//   task chips.  It is the only tab bound to the selection.
// - A click on a task header opens a Task tab. A click on a subtask node
//   opens a Subtask tab. Both carry their own assetId and survive selection
//   changes — you can browse a different asset without losing them.
// - Tasks with no subtasks open the Task tab on any click.
// - Each non-root tab has a pin (persisted per project on this machine) and
//   a close button. Pinned tabs come back after a restart.

import { useEffect, useMemo, useState } from 'react'
import { Pin, X } from 'lucide-react'
import { useProject } from '../../ProjectContext'
import { useI18n } from '../../i18n'
import type { ProductionAsset as Asset, ProductionPublish, ProductionState, ProductionTask } from '../../types'
import { TaskDetail } from './TaskDetail'
import { taskColorFromName } from './util'
import type { Selection } from './Production'

interface Props {
  state:              ProductionState
  setState:           (patch: (prev: ProductionState) => ProductionState) => void
  selection:          Selection
  publishesByTask:    Record<string, ProductionPublish[]>
  // Prevents the tab GC from firing before the first successful fetch — otherwise
  // pinned tabs would be wiped on Production remount, taking their store with them.
  loading?:           boolean
  // External deep-link: open a specific task (or subtask) tab automatically.
  initialOpen?:       { task: string; subtask?: string } | null
  onInitialOpenApplied?: () => void
}

type Tab =
  | { key: string; kind: 'root' }
  | { key: string; kind: 'task';    assetId: string; taskId: string }
  | { key: string; kind: 'subtask'; assetId: string; taskId: string; subtask: string }

interface PinnedRef {
  kind:    'task' | 'subtask'
  assetId: string
  taskId:  string
  subtask?: string
}

const ROOT_TAB: Tab = { key: 'root', kind: 'root' }
const taskKey = (assetId: string, taskId: string) => `task:${assetId}:${taskId}`
const subKey  = (assetId: string, taskId: string, sub: string) => `sub:${assetId}:${taskId}:${sub}`

const pinLsKey = (project: string) => `flux.production.pinned.${project}`

function readPinned(project: string): PinnedRef[] {
  if (!project) return []
  try {
    const raw = localStorage.getItem(pinLsKey(project))
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter((x: unknown): x is PinnedRef => {
      const p = x as PinnedRef
      return !!p && (p.kind === 'task' || p.kind === 'subtask') && typeof p.assetId === 'string' && typeof p.taskId === 'string'
    })
  } catch { return [] }
}
function writePinned(project: string, list: PinnedRef[]) {
  if (!project) return
  try { localStorage.setItem(pinLsKey(project), JSON.stringify(list)) } catch { /* blocked */ }
}

export function MenuSpec({ state, setState, selection, publishesByTask, loading, initialOpen, onInitialOpenApplied }: Props) {
  const { t } = useI18n()
  const { project } = useProject()

  const [tabs, setTabs]           = useState<Tab[]>([ROOT_TAB])
  const [activeKey, setActiveKey] = useState<string>('root')

  const selectedAsset = selection.kind === 'asset' ? state.assets.find(a => a.id === selection.id) ?? null : null

  // When the current context (asset selection) changes, close every tab that
  // is not explicitly pinned. Root always stays. Runs after the pin-restore
  // effect so restored pins survive the wipe.
  useEffect(() => {
    if (!project) return
    const pinnedKeys = new Set(readPinned(project).map(refToKey))
    setTabs(prev => {
      const kept = prev.filter(tab => tab.kind === 'root' || pinnedKeys.has(tab.key))
      if (kept.length === prev.length) return prev
      if (!kept.some(x => x.key === activeKey)) setActiveKey('root')
      return kept
    })
  }, [selectedAsset?.id])   // eslint-disable-line react-hooks/exhaustive-deps

  // ── restore pinned tabs whenever the active project changes ────────────────
  useEffect(() => {
    if (!project) { setTabs([ROOT_TAB]); setActiveKey('root'); return }
    const pins = readPinned(project)
    const restored: Tab[] = pins.map(p => (
      p.kind === 'subtask' && p.subtask
        ? { key: subKey(p.assetId, p.taskId, p.subtask), kind: 'subtask', assetId: p.assetId, taskId: p.taskId, subtask: p.subtask }
        : { key: taskKey(p.assetId, p.taskId), kind: 'task', assetId: p.assetId, taskId: p.taskId }
    ))
    setTabs([ROOT_TAB, ...restored])
    setActiveKey('root')
  }, [project])

  // ── garbage-collect tabs pointing at removed asset/task ────────────────────
  // Skipped while the production store is still loading — otherwise the empty
  // initial state would wipe pinned tabs and their persisted store.
  useEffect(() => {
    if (loading) return
    setTabs(prev => {
      const kept = prev.filter(tab => {
        if (tab.kind === 'root') return true
        const a = state.assets.find(x => x.id === tab.assetId)
        if (!a) return false
        return a.tasks.some(x => x.id === tab.taskId)
      })
      if (kept.length !== prev.length) {
        // Sync pinned store — same predicate.
        if (project) {
          const stillPinned = readPinned(project).filter(p => {
            const a = state.assets.find(x => x.id === p.assetId)
            return !!a && a.tasks.some(x => x.id === p.taskId)
          })
          writePinned(project, stillPinned)
        }
        if (!kept.some(x => x.key === activeKey)) setActiveKey('root')
      }
      return kept
    })
  }, [state.assets, project, loading])   // eslint-disable-line react-hooks/exhaustive-deps

  // ── consume external deep-link (fav row click) ─────────────────────────────
  useEffect(() => {
    if (!initialOpen || !selectedAsset) return
    const target = selectedAsset.tasks.find(x => x.name.toUpperCase() === initialOpen.task.toUpperCase())
    if (!target) return
    if (initialOpen.subtask) {
      const key = subKey(selectedAsset.id, target.id, initialOpen.subtask.toUpperCase())
      setTabs(prev => (prev.some(x => x.key === key) ? prev : [...prev, {
        key, kind: 'subtask', assetId: selectedAsset.id, taskId: target.id, subtask: initialOpen.subtask!.toUpperCase(),
      }]))
      setActiveKey(key)
    } else {
      const key = taskKey(selectedAsset.id, target.id)
      setTabs(prev => (prev.some(x => x.key === key) ? prev : [...prev, {
        key, kind: 'task', assetId: selectedAsset.id, taskId: target.id,
      }]))
      setActiveKey(key)
    }
    onInitialOpenApplied?.()
  }, [initialOpen, selectedAsset?.id])   // eslint-disable-line react-hooks/exhaustive-deps

  // ── tab management helpers ─────────────────────────────────────────────────
  const openTaskTab = (assetId: string, taskId: string) => {
    const key = taskKey(assetId, taskId)
    setTabs(prev => (prev.some(x => x.key === key) ? prev : [...prev, { key, kind: 'task', assetId, taskId }]))
    setActiveKey(key)
  }
  const openSubtaskTab = (assetId: string, taskId: string, subtask: string) => {
    const key = subKey(assetId, taskId, subtask)
    setTabs(prev => (prev.some(x => x.key === key) ? prev : [...prev, { key, kind: 'subtask', assetId, taskId, subtask }]))
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
    // Un-pin if it was pinned.
    if (project) writePinned(project, readPinned(project).filter(p => refToKey(p) !== key))
  }
  // Move *fromKey* before *toKey* in the tab strip. Root stays at index 0.
  const reorderTab = (fromKey: string, toKey: string) => {
    if (fromKey === toKey) return
    setTabs(prev => {
      const from = prev.findIndex(x => x.key === fromKey)
      const to   = prev.findIndex(x => x.key === toKey)
      if (from < 0 || to < 0) return prev
      const src = prev[from]
      if (src.kind === 'root') return prev
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
    if (!project || tab.kind === 'root') return
    const cur = readPinned(project)
    const ref: PinnedRef = tab.kind === 'subtask'
      ? { kind: 'subtask', assetId: tab.assetId, taskId: tab.taskId, subtask: tab.subtask }
      : { kind: 'task',    assetId: tab.assetId, taskId: tab.taskId }
    const key = refToKey(ref)
    const next = cur.some(p => refToKey(p) === key)
      ? cur.filter(p => refToKey(p) !== key)
      : [...cur, ref]
    writePinned(project, next)
    // Force a re-render (isPinned reads from localStorage, not from state).
    setTabs(prev => [...prev])
  }

  const active = tabs.find(x => x.key === activeKey) ?? ROOT_TAB

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      {/* tab strip — shrinks browser-style when it fills up */}
      <div style={{
        display: 'flex', alignItems: 'stretch',
        borderBottom: '1px solid var(--rule)', background: 'var(--paper)',
        overflow: 'hidden', flexShrink: 0,
      }}>
        {tabs.map((tab, i) => (
          <TabChip
            key={tab.key}
            tab={tab}
            state={state}
            selectedAsset={selectedAsset}
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

      {/* content */}
      {active.kind === 'root' && (
        selectedAsset
          ? <TasksLanding
              asset={selectedAsset}
              publishesByTask={publishesByTask}
              onOpenTask={(taskId) => openTaskTab(selectedAsset.id, taskId)}
              onOpenSubtask={(taskId, sub) => openSubtaskTab(selectedAsset.id, taskId, sub)}
            />
          : <div style={_hint}>{t('prod.selectEntity')}</div>
      )}
      {active.kind !== 'root' && (() => {
        const asset = state.assets.find(a => a.id === active.assetId)
        if (!asset) return <div style={_hint}>Asset introuvable</div>
        const task = asset.tasks.find(x => x.id === active.taskId)
        if (!task) return <div style={_hint}>Tâche introuvable</div>
        const bucket = publishesByTask[`${asset.id}|${task.id}`] || []
        if (active.kind === 'task') {
          return (
            <TaskDetail
              asset={asset} task={task}
              subtaskFilter={null}
              detailKey={task.name}
              publishes={bucket}
              pinned={isPinned(active.key)}
              onTogglePin={() => togglePin(active)}
              onPatchTask={patch => patchTask(setState, asset.id, task.id, patch)}
              onPatchDetail={patch => patchDetail(setState, asset.id, task.name, patch)}
              onDeleteTask={() => {
                setState(prev => ({
                  ...prev,
                  assets: prev.assets.map(a => a.id === asset.id ? {
                    ...a, tasks: a.tasks.filter(x => x.id !== task.id),
                  } : a),
                }))
                closeTab(active.key)
              }}
            />
          )
        }
        // subtask
        return (
          <TaskDetail
            asset={asset} task={task}
            subtaskFilter={active.subtask}
            detailKey={`${task.name}|${active.subtask}`}
            publishes={bucket.filter(p => (p.instance || '').toUpperCase() === active.subtask.toUpperCase())}
            pinned={isPinned(active.key)}
            onTogglePin={() => togglePin(active)}
            onPatchTask={patch => patchTask(setState, asset.id, task.id, patch)}
            onPatchDetail={patch => patchDetail(setState, asset.id, `${task.name}|${active.subtask}`, patch)}
            onDeleteTask={() => closeTab(active.key) /* not applicable in subtask view */}
          />
        )
      })()}
    </div>
  )
}

// ── tab chip ────────────────────────────────────────────────────────────────
function TabChip({ tab, state, selectedAsset, active, pinned, onSelect, onClose, onTogglePin, onReorder, index }: {
  tab:            Tab
  state:          ProductionState
  selectedAsset:  Asset | null
  active:         boolean
  pinned:         boolean
  onSelect:       () => void
  onClose:        () => void
  onTogglePin:    () => void
  onReorder:      (fromKey: string, toKey: string) => void
  index:          number
}) {
  const { label, color, sub } = useMemo(() => {
    if (tab.kind === 'root') {
      return {
        label: selectedAsset ? `${selectedAsset.class} · ${selectedAsset.name}` : 'Tasks',
        color: 'var(--accent)', sub: '',
      }
    }
    const a = state.assets.find(x => x.id === tab.assetId)
    const tk = a?.tasks.find(x => x.id === tab.taskId)
    const name = tk?.name ?? '—'
    return {
      label: a ? `${a.name} · ${name}` : name,
      color: taskColorFromName(name),
      sub: tab.kind === 'subtask' ? tab.subtask : '',
    }
  }, [tab, state.assets, selectedAsset])

  const draggable = tab.kind !== 'root'
  const [dragOver, setDragOver] = useState(false)

  return (
    <div
      onClick={onSelect}
      draggable={draggable}
      onDragStart={e => {
        if (!draggable) return
        e.dataTransfer.effectAllowed = 'move'
        e.dataTransfer.setData('text/flux-tab-key', tab.key)
      }}
      onDragOver={e => {
        if (!e.dataTransfer.types.includes('text/flux-tab-key')) return
        if (tab.kind === 'root') return                    // never accept a drop on root
        e.preventDefault(); e.dataTransfer.dropEffect = 'move'
        setDragOver(true)
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={e => {
        setDragOver(false)
        const from = e.dataTransfer.getData('text/flux-tab-key')
        if (from && from !== tab.key && tab.kind !== 'root') {
          e.preventDefault(); e.stopPropagation()
          onReorder(from, tab.key)
        }
      }}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 6,
        padding: '7px 12px',
        borderRight: '1px solid var(--rule)',
        background: active ? 'var(--paper-2)' : dragOver ? 'color-mix(in oklch, var(--accent) 12%, transparent)' : 'transparent',
        color: active ? 'var(--ink)' : 'var(--ink-3)',
        cursor: draggable ? 'grab' : 'pointer',
        userSelect: 'none',
        borderTop: active ? `2px solid ${color}` : '2px solid transparent',
        fontSize: 11, fontFamily: 'var(--sans)',
        // browser-style shrink: root doesn't shrink so its label stays legible;
        // task/subtask tabs share the remaining width and clamp to a max.
        flex: tab.kind === 'root' ? '0 0 auto' : '1 1 100px',
        minWidth: tab.kind === 'root' ? undefined : 60,
        maxWidth: tab.kind === 'root' ? undefined : 200,
        minHeight: 0, overflow: 'hidden',
      }}
      title={label + (sub ? ` · ${sub}` : '')}
    >
      {tab.kind !== 'root' && (
        <span style={{ width: 6, height: 6, borderRadius: '50%', background: color, flexShrink: 0 }} />
      )}
      <span style={{
        fontFamily: tab.kind === 'root' ? 'var(--sans)' : 'var(--mono)',
        fontSize: tab.kind === 'root' ? 11 : 10, letterSpacing: '0.03em',
        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        flex: '1 1 auto', minWidth: 0,
      }}>
        {label}{sub ? ` · ${sub}` : ''}
      </span>
      {tab.kind !== 'root' && (
        <>
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
        </>
      )}
      {/* mute index unused-var */}
      <span style={{ display: 'none' }}>{index}</span>
    </div>
  )
}

// ── tasks landing (chips with hover-expand) ─────────────────────────────────
function TasksLanding({ asset, publishesByTask, onOpenTask, onOpenSubtask }: {
  asset:           Asset
  publishesByTask: Record<string, ProductionPublish[]>
  onOpenTask:      (taskId: string) => void
  onOpenSubtask:   (taskId: string, subtask: string) => void
}) {
  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '14px 18px' }}>
      {asset.tasks.length === 0 && (
        <div style={{ fontSize: 11, color: 'var(--ink-4)' }}>—</div>
      )}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'flex-start' }}>
        {[...asset.tasks].sort((a, b) => a.order - b.order).map(task => (
          <TaskNode
            key={task.id}
            task={task}
            publishCount={(publishesByTask[`${asset.id}|${task.id}`] || []).length}
            onOpenHeader={() => onOpenTask(task.id)}
            onOpenSubtask={(sub) => onOpenSubtask(task.id, sub)}
            completion={asset.task_details?.[task.name]?.completion ?? 0}
            subtaskCompletions={Object.fromEntries(
              task.known_subtasks.map(s => [s, asset.task_details?.[`${task.name}|${s}`]?.completion ?? 0])
            )}
          />
        ))}
      </div>
    </div>
  )
}

// ── one task node ────────────────────────────────────────────────────────────
function TaskNode({ task, publishCount, onOpenHeader, onOpenSubtask, completion, subtaskCompletions }: {
  task:               ProductionTask
  publishCount:       number
  onOpenHeader:       () => void
  onOpenSubtask:      (sub: string) => void
  completion:         number
  subtaskCompletions: Record<string, number>
}) {
  const [expanded, setExpanded] = useState(false)
  const [hoveredSub, setHoveredSub] = useState<string | null>(null)
  const color = taskColorFromName(task.name)
  const hasSubs = task.known_subtasks.length > 0

  const onClickBody: React.MouseEventHandler = (e) => {
    if (!hasSubs) { e.stopPropagation(); onOpenHeader() }
  }

  return (
    <div
      onMouseEnter={() => setExpanded(true)}
      onMouseLeave={() => setExpanded(false)}
      onClick={onClickBody}
      style={{
        minWidth: expanded ? 220 : 160,
        maxWidth: 360,
        padding: expanded ? '10px 12px 12px' : '9px 14px',
        borderRadius: 12,
        border: `1px solid ${color}`,
        background: `color-mix(in oklch, ${color} 16%, var(--paper))`,
        color: 'var(--ink)',
        boxShadow: '0 2px 8px rgba(0,0,0,0.35)',
        cursor: hasSubs ? 'default' : 'pointer',
        transition: 'min-width 0.22s ease, padding 0.22s ease, transform 0.22s ease, box-shadow 0.22s ease',
        transform: expanded ? 'scale(1.02)' : 'scale(1)',
      }}
    >
      <div
        onClick={(e) => { e.stopPropagation(); onOpenHeader() }}
        style={{
          display: 'flex', alignItems: 'center', gap: 8,
          cursor: 'pointer', paddingBottom: expanded ? 8 : 0,
          borderBottom: expanded ? '1px solid color-mix(in oklch, ' + color + ' 30%, transparent)' : 'none',
        }}
        title="Ouvrir la tâche"
      >
        <span style={{ width: 6, height: 6, borderRadius: '50%', background: color, flexShrink: 0 }} />
        <span style={{ fontFamily: 'var(--mono)', fontSize: 11, letterSpacing: '0.05em', color: 'var(--ink)' }}>{task.name}</span>
        <span style={{ flex: 1 }} />
        {publishCount > 0 && (
          <span style={{
            fontFamily: 'var(--mono)', fontSize: 8, padding: '1px 6px', borderRadius: 3,
            background: 'var(--accent-soft)', color: 'var(--accent-hi)',
          }}>{publishCount}</span>
        )}
      </div>

      <div style={{
        height: expanded ? 5 : 3, marginTop: expanded ? 8 : 6, borderRadius: 3,
        background: 'color-mix(in oklch, var(--paper) 60%, transparent)',
        overflow: 'hidden', transition: 'height 0.2s',
      }}>
        <div style={{
          width: `${Math.max(0, Math.min(100, completion))}%`, height: '100%',
          background: color, transition: 'width 0.25s',
        }} />
      </div>

      {expanded && hasSubs && (
        <div style={{ marginTop: 10, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {task.known_subtasks.map(sub => {
            const subDone = subtaskCompletions[sub] ?? 0
            const isHovered = hoveredSub === sub
            return (
              <div
                key={sub}
                onMouseEnter={() => setHoveredSub(sub)}
                onMouseLeave={() => setHoveredSub(prev => (prev === sub ? null : prev))}
                style={{ display: 'flex', flexDirection: 'column', gap: 4 }}
              >
                <button
                  onClick={(e) => { e.stopPropagation(); onOpenSubtask(sub) }}
                  style={{
                    display: 'inline-flex', alignItems: 'center', gap: 5,
                    padding: '4px 10px', borderRadius: 8,
                    border: `1px solid ${color}`,
                    background: color, color: 'var(--paper)',
                    fontFamily: 'var(--mono)', fontSize: 9, letterSpacing: '0.05em',
                    cursor: 'pointer',
                    boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.15)',
                    transition: 'transform 0.12s, filter 0.12s',
                  }}
                  onMouseEnter={e => { e.currentTarget.style.transform = 'scale(1.05)'; e.currentTarget.style.filter = 'brightness(1.08)' }}
                  onMouseLeave={e => { e.currentTarget.style.transform = 'scale(1)'; e.currentTarget.style.filter = 'brightness(1)' }}
                >
                  {sub}
                </button>
                <div style={{
                  height: 3, borderRadius: 2, width: 68,
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
  )
}

// ── helpers ──────────────────────────────────────────────────────────────────
function refToKey(p: PinnedRef): string {
  return p.kind === 'subtask' && p.subtask
    ? subKey(p.assetId, p.taskId, p.subtask)
    : taskKey(p.assetId, p.taskId)
}

function patchTask(
  setState: (patch: (prev: ProductionState) => ProductionState) => void,
  assetId: string, taskId: string, patch: Partial<ProductionTask>,
) {
  setState(prev => ({
    ...prev,
    assets: prev.assets.map(a => a.id === assetId ? {
      ...a, tasks: a.tasks.map(x => x.id === taskId ? { ...x, ...patch } : x),
    } : a),
  }))
}

function patchDetail(
  setState: (patch: (prev: ProductionState) => ProductionState) => void,
  assetId: string, taskName: string, patch: Record<string, unknown>,
) {
  setState(prev => ({
    ...prev,
    assets: prev.assets.map(a => a.id === assetId ? {
      ...a,
      task_details: {
        ...(a.task_details || {}),
        [taskName]: { ...(a.task_details?.[taskName] || {}), ...patch },
      },
    } : a),
  }))
}

const _hint: React.CSSProperties = {
  flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
  color: 'var(--ink-4)', fontSize: 11,
}
