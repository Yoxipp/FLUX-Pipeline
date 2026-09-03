// MenuEdit — contextual right-side panel. Branches on the current selection
// (nothing / asset / group) and on which category is currently entered.

import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { Copy, FolderPlus, HardDriveDownload, Plus, Trash2 } from 'lucide-react'
import { api } from '../../api/client'
import { useI18n } from '../../i18n'
import type {
  ProductionAsset as Asset,
  ProductionAssetGroup, ProductionPublish, ProductionState, ProductionTask,
} from '../../types'
import { CATEGORY_ORDER, categoryColor } from './util'
import { ProdBtn } from './ProdButtons'
import type { Selection } from './Production'

interface Props {
  project:         string
  state:           ProductionState
  setState:        (patch: (prev: ProductionState) => ProductionState) => void
  selection:       Selection
  setSelection:    (s: Selection) => void
  mode:            'asset' | 'shot'
  activeCategory:  string | null
  publishesByTask: Record<string, ProductionPublish[]>
}

const nid = (prefix: string) => `${prefix}_${Math.random().toString(36).slice(2, 12)}`

export function MenuEdit({
  project, state, setState, selection, setSelection, mode,
  activeCategory, publishesByTask,
}: Props) {
  // Load TASK/TYPE tokens from the project (defaults + custom in tokens.json).
  const [projectTaskTokens, setProjectTaskTokens] = useState<string[]>([])
  useEffect(() => {
    let alive = true
    api.getTokens(project)
      .then(r => { if (alive) setProjectTaskTokens(Object.keys(r.tokens?.TYPE ?? {}).map(s => s.toUpperCase()).sort()) })
      .catch(() => { if (alive) setProjectTaskTokens([]) })
    return () => { alive = false }
  }, [project])

  const selectedAsset = selection.kind === 'asset'
    ? state.assets.find(a => a.id === selection.id) ?? null
    : null
  const selectedGroup = selection.kind === 'group'
    ? state.asset_groups.find(g => g.id === selection.id) ?? null
    : null

  if (mode === 'shot') {
    return <div style={_pad}><div style={_hint}>Éditeur SHOT — Phase 2</div></div>
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      <div style={{ padding: '10px 12px 6px', borderBottom: '1px solid var(--rule)' }}>
        <div className="cap" style={{ fontSize: 9, letterSpacing: '0.09em', color: 'var(--ink-3)' }}>Edit</div>
      </div>

      {selection.kind === 'none' && (
        <CreateSection
          setState={setState}
          setSelection={setSelection}
          activeCategory={activeCategory}
        />
      )}

      {selectedAsset && (
        <AssetSection
          project={project}
          asset={selectedAsset}
          state={state}
          setState={setState}
          setSelection={setSelection}
          projectTaskTokens={projectTaskTokens}
          publishesByTask={publishesByTask}
        />
      )}

      {selectedGroup && (
        <GroupSection group={selectedGroup} setState={setState} setSelection={setSelection} />
      )}
    </div>
  )
}

// ── create asset / group ─────────────────────────────────────────────────────
function CreateSection({ setState, setSelection, activeCategory }: {
  setState:       (patch: (prev: ProductionState) => ProductionState) => void
  setSelection:   (s: Selection) => void
  activeCategory: string | null
}) {
  const { t } = useI18n()
  const [cls, setCls] = useState<string>(activeCategory ?? 'CHAR')
  useEffect(() => { if (activeCategory) setCls(activeCategory) }, [activeCategory])

  const [name, setName]           = useState('')
  const [groupName, setGroupName] = useState('')

  const createAsset = () => {
    const n = name.trim().toUpperCase()
    if (!n) return
    const id = nid('asset')
    setState(prev => ({
      ...prev,
      assets: [...prev.assets, {
        id, class: cls, name: n, group_id: null,
        order: prev.assets.length, origin: 'user',
        tasks: [], task_details: {},
      }],
    }))
    setSelection({ kind: 'asset', id })
    setName('')
  }

  const createGroup = () => {
    const n = groupName.trim().toUpperCase()
    if (!n) return
    const id = nid('g')
    setState(prev => ({
      ...prev,
      asset_groups: [...prev.asset_groups, {
        id, class: cls, name: n, order: prev.asset_groups.length,
      }],
    }))
    setSelection({ kind: 'group', id })
    setGroupName('')
  }

  return (
    <>
      <div style={_pad}>
        <div style={_lbl}>{t('prod.newAsset')}</div>
        {!activeCategory && (
          <select value={cls} onChange={e => setCls(e.target.value)} style={{ ..._input, marginBottom: 6, width: '100%' }}>
            {CATEGORY_ORDER.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        )}
        {activeCategory && (
          <div style={{
            display: 'inline-flex', alignItems: 'center', gap: 6, marginBottom: 6,
            padding: '4px 8px', borderRadius: 5,
            background: categoryColor(activeCategory), color: 'var(--paper)',
            fontFamily: 'var(--mono)', fontSize: 9, letterSpacing: '0.06em',
          }}>
            <span style={{ width: 5, height: 5, borderRadius: '50%', background: 'var(--paper)' }} />
            {activeCategory}
          </div>
        )}
        <input
          value={name}
          onChange={e => setName(e.target.value.toUpperCase())}
          onKeyDown={e => { if (e.key === 'Enter') createAsset() }}
          style={{ ..._input, width: '100%' }}
        />
        <ProdBtn full onClick={createAsset} style={{ marginTop: 6 }}>
          <Plus size={12} strokeWidth={2} /> {t('prod.newAsset')}
        </ProdBtn>
      </div>

      <div style={_pad}>
        <div style={_lbl}>{t('prod.newGroup')}</div>
        <input
          value={groupName}
          onChange={e => setGroupName(e.target.value.toUpperCase())}
          onKeyDown={e => { if (e.key === 'Enter') createGroup() }}
          style={{ ..._input, width: '100%' }}
        />
        <ProdBtn full variant="ghost" onClick={createGroup} style={{ marginTop: 6 }}>
          <FolderPlus size={11} strokeWidth={1.75} /> {t('prod.newGroup')}
        </ProdBtn>
      </div>
    </>
  )
}

// ── asset actions ────────────────────────────────────────────────────────────
function AssetSection({ project, asset, state, setState, setSelection, projectTaskTokens, publishesByTask }: {
  project:           string
  asset:             Asset
  state:             ProductionState
  setState:          (patch: (prev: ProductionState) => ProductionState) => void
  setSelection:      (s: Selection) => void
  projectTaskTokens: string[]
  publishesByTask:   Record<string, ProductionPublish[]>
}) {
  const { t } = useI18n()
  const [taskName, setTaskName] = useState('')
  const [subtask, setSubtask]   = useState('')

  // Suggestions for the subtask field: every INSTANCE token seen across the
  // project on any task whose name (or type_tokens) matches the one being typed.
  // Falls back to *all* known subtasks when the task name is empty.
  const subtaskSuggestions = useMemo(() => {
    const wanted = taskName.trim().toUpperCase()
    const bag = new Set<string>()
    for (const a of state.assets) {
      for (const tk of a.tasks) {
        const matches = !wanted || tk.name.toUpperCase() === wanted || tk.type_tokens.map(x => x.toUpperCase()).includes(wanted)
        if (matches) tk.known_subtasks.forEach(v => bag.add(v.toUpperCase()))
      }
    }
    // Also mine any live publish INSTANCE for that task if present in publishes_by_task.
    for (const bucket of Object.values(publishesByTask)) {
      for (const p of bucket) {
        if (!wanted || p.task_token?.toUpperCase() === wanted) {
          if (p.instance) bag.add(p.instance.toUpperCase())
        }
      }
    }
    return [...bag].sort()
  }, [taskName, state.assets, publishesByTask])

  const rename = (v: string) => {
    const n = v.toUpperCase()
    setState(prev => ({ ...prev, assets: prev.assets.map(a => a.id === asset.id ? { ...a, name: n, origin: 'user' } : a) }))
  }

  const duplicate = () => {
    const id = nid('asset')
    setState(prev => ({
      ...prev,
      assets: [...prev.assets, {
        ...asset, id, name: `${asset.name}_COPY`,
        order: prev.assets.length, origin: 'user',
        tasks: asset.tasks.map(x => ({ ...x, id: nid('t') })),
      }],
    }))
    setSelection({ kind: 'asset', id })
  }

  const remove = () => {
    setState(prev => ({ ...prev, assets: prev.assets.filter(a => a.id !== asset.id) }))
    setSelection({ kind: 'none' })
  }

  const addTask = () => {
    const label = taskName.trim().toUpperCase()
    if (!label) return
    const subtaskUp = subtask.trim().toUpperCase()

    // Merge into an existing task if this asset already has one with the same
    // name (or type_token) — avoids duplicating the whole node just to add a
    // subtask.
    const existing = asset.tasks.find(x =>
      x.name.toUpperCase() === label ||
      x.type_tokens.map(t => t.toUpperCase()).includes(label)
    )
    if (existing) {
      setState(prev => ({
        ...prev,
        assets: prev.assets.map(a => a.id !== asset.id ? a : {
          ...a,
          tasks: a.tasks.map(x => x.id !== existing.id ? x : {
            ...x,
            known_subtasks: subtaskUp && !x.known_subtasks.map(s => s.toUpperCase()).includes(subtaskUp)
              ? [...x.known_subtasks, subtaskUp]
              : x.known_subtasks,
          }),
        }),
      }))
      setTaskName(''); setSubtask('')
      return
    }

    const id = nid('t')
    const newTask: ProductionTask = {
      id, name: label, order: asset.tasks.length,
      type_tokens: [label],
      known_subtasks: subtaskUp ? [subtaskUp] : [],
      origin: 'user',
    }
    setState(prev => ({
      ...prev,
      assets: prev.assets.map(a => a.id === asset.id ? { ...a, tasks: [...a.tasks, newTask] } : a),
    }))
    setTaskName(''); setSubtask('')
  }

  const materialize = async () => {
    try {
      const r = await api.materializeProductionEntity(project, {
        kind: 'asset', class_token: asset.class, name: asset.name,
      })
      toast.success(`Dossier créé : ${r.path}`)
      window.dispatchEvent(new Event('flux:refresh'))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <>
      <div style={_pad}>
        <div style={_lbl}>{asset.class} · {asset.name}</div>
        <input
          value={asset.name}
          onChange={e => rename(e.target.value)}
          style={{ ..._input, width: '100%' }}
        />
        <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
          <ProdBtn variant="ghost" size="sm" onClick={duplicate}>
            <Copy size={10} strokeWidth={1.75} /> {t('prod.duplicate')}
          </ProdBtn>
          <ProdBtn variant="danger" size="sm" onClick={remove}>
            <Trash2 size={10} strokeWidth={1.75} /> {t('prod.delete')}
          </ProdBtn>
        </div>
        <ProdBtn full variant="ghost" onClick={materialize} style={{ marginTop: 6 }}>
          <HardDriveDownload size={11} strokeWidth={1.75} /> {t('prod.materializeAsset')}
        </ProdBtn>
      </div>

      <div style={_pad}>
        <div style={_lbl}>{t('prod.newTask')}</div>
        <input
          value={taskName}
          onChange={e => setTaskName(e.target.value.toUpperCase())}
          list="prod-task-tokens"
          style={{ ..._input, width: '100%' }}
        />
        <datalist id="prod-task-tokens">
          {projectTaskTokens.map(x => <option key={x} value={x} />)}
        </datalist>

        <div style={{ ..._lbl, marginTop: 8 }}>SUBTASK</div>
        <input
          value={subtask}
          onChange={e => setSubtask(e.target.value.toUpperCase())}
          list="prod-subtask-suggest"
          onKeyDown={e => { if (e.key === 'Enter') addTask() }}
          style={{ ..._input, width: '100%' }}
        />
        <datalist id="prod-subtask-suggest">
          {subtaskSuggestions.map(x => <option key={x} value={x} />)}
        </datalist>

        <ProdBtn full onClick={addTask} style={{ marginTop: 6 }} disabled={!taskName.trim()}>
          <Plus size={12} strokeWidth={2} /> {t('prod.newTask')}
        </ProdBtn>
      </div>
    </>
  )
}

// ── group actions ────────────────────────────────────────────────────────────
function GroupSection({ group, setState, setSelection }: {
  group:        ProductionAssetGroup
  setState:     (patch: (prev: ProductionState) => ProductionState) => void
  setSelection: (s: Selection) => void
}) {
  const { t } = useI18n()
  const rename = (v: string) => {
    const n = v.toUpperCase()
    setState(prev => ({
      ...prev,
      asset_groups: prev.asset_groups.map(g => g.id === group.id ? { ...g, name: n } : g),
    }))
  }
  const remove = () => {
    setState(prev => ({
      ...prev,
      asset_groups: prev.asset_groups.filter(g => g.id !== group.id),
      assets: prev.assets.map(a => a.group_id === group.id ? { ...a, group_id: null } : a),
    }))
    setSelection({ kind: 'none' })
  }
  return (
    <div style={_pad}>
      <div style={_lbl}>{group.class} · GROUPE</div>
      <input value={group.name} onChange={e => rename(e.target.value)} style={{ ..._input, width: '100%' }} />
      <ProdBtn full variant="danger" onClick={remove} style={{ marginTop: 8 }}>
        <Trash2 size={11} strokeWidth={1.75} /> {t('prod.delete')}
      </ProdBtn>
    </div>
  )
}

// ── inline styles ────────────────────────────────────────────────────────────
const _pad: React.CSSProperties = { padding: '12px 12px 10px', borderBottom: '1px solid var(--rule)' }
const _lbl: React.CSSProperties = {
  fontFamily: 'var(--mono)', fontSize: 9, letterSpacing: '0.08em',
  color: 'var(--ink-3)', textTransform: 'uppercase', marginBottom: 4,
}
const _input: React.CSSProperties = {
  background: 'var(--paper)', color: 'var(--ink)',
  border: '1px solid var(--rule-2)', borderRadius: 6,
  padding: '6px 9px', fontSize: 11, fontFamily: 'var(--mono)',
  letterSpacing: '0.04em', outline: 'none',
}
const _hint: React.CSSProperties = { padding: 20, fontSize: 11, color: 'var(--ink-4)', textAlign: 'center' }
