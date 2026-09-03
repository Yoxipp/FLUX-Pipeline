// MenuSpec — Houdini-style tabbed spec panel.
//
// Tab layout:  [Tasks | <task N> | <task N · subtask K> | …]
//
// - The first tab is always "Tasks" and shows the asset's task chips.
// - A click on a task header opens a Task tab.
// - A click on a subtask node (nested inside a task chip) opens a Subtask tab.
// - Tasks with no subtasks open the Task tab on any click.
// - Each tab except the first can be closed with an X.

import { useEffect, useState } from 'react'
import { X } from 'lucide-react'
import { useI18n } from '../../i18n'
import type { ProductionAsset as Asset, ProductionPublish, ProductionState, ProductionTask } from '../../types'
import { TaskDetail } from './TaskDetail'
import { taskColorFromName } from './util'
import type { Selection } from './Production'

interface Props {
  state:           ProductionState
  setState:        (patch: (prev: ProductionState) => ProductionState) => void
  selection:       Selection
  publishesByTask: Record<string, ProductionPublish[]>
}

type Tab =
  | { key: string; kind: 'root' }
  | { key: string; kind: 'task';    taskId: string }
  | { key: string; kind: 'subtask'; taskId: string; subtask: string }

const ROOT_TAB: Tab = { key: 'root', kind: 'root' }

export function MenuSpec({ state, setState, selection, publishesByTask }: Props) {
  const { t } = useI18n()
  const [tabs, setTabs]         = useState<Tab[]>([ROOT_TAB])
  const [activeKey, setActiveKey] = useState<string>('root')

  const asset = selection.kind === 'asset' ? state.assets.find(a => a.id === selection.id) ?? null : null

  // Reset tabs when the active asset changes.
  useEffect(() => {
    setTabs([ROOT_TAB])
    setActiveKey('root')
  }, [asset?.id])

  if (!asset) {
    return <div style={_hint}>{t('prod.selectEntity')}</div>
  }

  // ── tab management helpers ─────────────────────────────────────────────────
  const openTaskTab = (taskId: string) => {
    const key = `task:${taskId}`
    setTabs(prev => (prev.some(x => x.key === key) ? prev : [...prev, { key, kind: 'task', taskId }]))
    setActiveKey(key)
  }
  const openSubtaskTab = (taskId: string, subtask: string) => {
    const key = `sub:${taskId}:${subtask}`
    setTabs(prev => (prev.some(x => x.key === key) ? prev : [...prev, { key, kind: 'subtask', taskId, subtask }]))
    setActiveKey(key)
  }
  const closeTab = (key: string) => {
    setTabs(prev => {
      const next = prev.filter(x => x.key !== key)
      if (activeKey === key) {
        // fall back to the tab immediately left of the closed one, else root
        const idx = prev.findIndex(x => x.key === key)
        const fallback = next[Math.max(0, idx - 1)]?.key ?? 'root'
        setActiveKey(fallback)
      }
      return next
    })
  }

  const active = tabs.find(x => x.key === activeKey) ?? ROOT_TAB

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      {/* tab strip */}
      <div style={{
        display: 'flex', alignItems: 'stretch',
        borderBottom: '1px solid var(--rule)', background: 'var(--paper)',
        overflowX: 'auto', flexShrink: 0,
      }}>
        {tabs.map(tab => {
          const label = labelForTab(tab, asset)
          const color = tabColor(tab, asset)
          const isActive = tab.key === activeKey
          return (
            <div
              key={tab.key}
              onClick={() => setActiveKey(tab.key)}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 8,
                padding: '7px 14px',
                borderRight: '1px solid var(--rule)',
                background: isActive ? 'var(--paper-2)' : 'transparent',
                color: isActive ? 'var(--ink)' : 'var(--ink-3)',
                cursor: 'pointer', userSelect: 'none',
                borderTop: isActive ? `2px solid ${color}` : '2px solid transparent',
                fontSize: 11, fontFamily: 'var(--sans)',
                flexShrink: 0,
              }}
            >
              {tab.kind !== 'root' && (
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: color }} />
              )}
              <span style={{
                fontFamily: tab.kind === 'root' ? 'var(--sans)' : 'var(--mono)',
                fontSize: tab.kind === 'root' ? 11 : 10, letterSpacing: '0.03em',
              }}>{label}</span>
              {tab.kind !== 'root' && (
                <button
                  onClick={e => { e.stopPropagation(); closeTab(tab.key) }}
                  title="Fermer"
                  style={{
                    width: 15, height: 15, borderRadius: 3, border: 'none',
                    background: 'transparent', color: 'var(--ink-3)', cursor: 'pointer',
                    display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                  }}
                >
                  <X size={9} strokeWidth={2} />
                </button>
              )}
            </div>
          )
        })}
      </div>

      {/* content */}
      {active.kind === 'root' && (
        <TasksLanding
          asset={asset}
          publishesByTask={publishesByTask}
          onOpenTask={openTaskTab}
          onOpenSubtask={openSubtaskTab}
        />
      )}
      {active.kind === 'task' && (
        <TaskDetail
          asset={asset}
          task={requireTask(asset, active.taskId)}
          subtaskFilter={null}
          detailKey={requireTask(asset, active.taskId).name}
          publishes={publishesByTask[`${asset.id}|${active.taskId}`] || []}
          onPatchTask={patch => patchTask(setState, asset.id, active.taskId, patch)}
          onPatchDetail={patch => patchDetail(setState, asset.id, requireTask(asset, active.taskId).name, patch)}
          onDeleteTask={() => {
            setState(prev => ({
              ...prev,
              assets: prev.assets.map(a => a.id === asset.id ? {
                ...a, tasks: a.tasks.filter(x => x.id !== active.taskId),
              } : a),
            }))
            closeTab(active.key)
          }}
        />
      )}
      {active.kind === 'subtask' && (
        <TaskDetail
          asset={asset}
          task={requireTask(asset, active.taskId)}
          subtaskFilter={active.subtask}
          detailKey={`${requireTask(asset, active.taskId).name}|${active.subtask}`}
          publishes={(publishesByTask[`${asset.id}|${active.taskId}`] || []).filter(
            p => (p.instance || '').toUpperCase() === active.subtask.toUpperCase()
          )}
          onPatchTask={patch => patchTask(setState, asset.id, active.taskId, patch)}
          onPatchDetail={patch => patchDetail(setState, asset.id, `${requireTask(asset, active.taskId).name}|${active.subtask}`, patch)}
          onDeleteTask={() => closeTab(active.key) /* not applicable in subtask view */}
        />
      )}
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

  // If no subtasks, any click opens the task tab directly.
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
      {/* header — always clickable to open Task tab */}
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
        {task.origin === 'auto' && (
          <span style={{
            fontFamily: 'var(--mono)', fontSize: 8, padding: '1px 5px', borderRadius: 3,
            background: 'color-mix(in oklch, var(--warn) 18%, transparent)',
            color: 'var(--warn)', letterSpacing: '0.06em', textTransform: 'uppercase',
          }}>auto</span>
        )}
        <span style={{ flex: 1 }} />
        {publishCount > 0 && (
          <span style={{
            fontFamily: 'var(--mono)', fontSize: 8, padding: '1px 6px', borderRadius: 3,
            background: 'var(--accent-soft)', color: 'var(--accent-hi)',
          }}>{publishCount}</span>
        )}
      </div>

      {/* completion mini-bar (always visible; hover just makes it larger) */}
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

      {/* subtasks nested boxes — visible only when expanded */}
      {expanded && hasSubs && (
        <div style={{
          marginTop: 10, display: 'flex', flexWrap: 'wrap', gap: 8,
        }}>
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
                {/* subtask completion — hidden by default, shown at hover */}
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
function requireTask(asset: Asset, taskId: string): ProductionTask {
  const t = asset.tasks.find(x => x.id === taskId)
  if (!t) {
    // Fallback shell so React never crashes if the tab briefly outlives the task
    return { id: taskId, name: '—', order: 0, type_tokens: [], known_subtasks: [] }
  }
  return t
}

function labelForTab(tab: Tab, asset: Asset): string {
  if (tab.kind === 'root') return 'Tasks'
  const task = asset.tasks.find(x => x.id === tab.taskId)
  const base = task?.name ?? '—'
  return tab.kind === 'subtask' ? `${base} · ${tab.subtask}` : base
}

function tabColor(tab: Tab, asset: Asset): string {
  if (tab.kind === 'root') return 'var(--accent)'
  const task = asset.tasks.find(x => x.id === tab.taskId)
  return taskColorFromName(task?.name ?? '—')
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
