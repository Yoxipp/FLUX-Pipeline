// MenuEdit — contextual right-side panel. Branches on the current selection
// (nothing / asset / group) and on which category is currently entered.

import { useEffect, useMemo, useState } from 'react'
import type { CSSProperties } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { Check, Clapperboard, Copy, FolderOpen, FolderPlus, Lock, LockOpen, Plus, Trash2, X } from 'lucide-react'
import { api } from '../../api/client'
import { useSettings } from '../../hooks/useSettings'
import { useI18n } from '../../i18n'
import type {
  ProductionAsset as Asset,
  CastingLink, ProductionAssetGroup, ProductionPublish,
  ProductionLock, ProductionSequence, ProductionShot,
  ProductionState, ProductionTask,
} from '../../types'
import { CATEGORY_ORDER, categoryColor, categoryLabelKey, defaultSeqColor, expandFluxPath, shotColorFromSeqColor } from './util'
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
  sequencesOnDisk?: Set<string>
  shotsOnDisk?:    Set<string>              // "SEQxxx|SHOTxxx"
}

const nid = (prefix: string) => `${prefix}_${Math.random().toString(36).slice(2, 12)}`

// ── delete = archive flow (asset / seq / shot) ───────────────────────────────
// Deleting a disk-backed entity never hard-deletes: it moves the folder into
// <project>/ARCHIVE/<timestamp>/ then removes the logical entity. A confirmation
// is ALWAYS shown (Milo's spec); when the folder is non-empty it states how
// many files will be moved. Cancel does nothing. If the folder is a ghost
// (nothing on disk) we skip the move and just drop the logical entity.
type ArchiveDescriptor =
  | { kind: 'asset'; class_token: string; name: string }
  | { kind: 'seq';   seq: string }
  | { kind: 'shot';  seq: string; shot: string }

function descToParams(d: ArchiveDescriptor) {
  if (d.kind === 'asset') return { kind: 'asset' as const, class_token: d.class_token, name: d.name }
  if (d.kind === 'seq')   return { kind: 'seq' as const, seq: d.seq }
  return { kind: 'shot' as const, seq: d.seq, shot: d.shot }
}

interface PendingArchive {
  desc:      ArchiveDescriptor
  label:     string
  info:      { rel_path: string; exists: boolean; file_count: number } | null
  onRemoved: () => void
  busy:      boolean
}

// A sequence / shot is only deleted after typing this word (2026-09-27).
const DELETE_PHRASE = 'Understand'

// Open a Production entity's folder in the Folder Manager (B1, 2026-09-28).
// The folder is resolved by the backend (SEQ / SHOT tokens, else shot/<SEQ>/<SHOT>),
// then handed to the Folder Manager through its existing `openPath` deep link.
function useOpenEntityFolder(project: string) {
  const navigate = useNavigate()
  const { settings } = useSettings()
  return async (desc: ArchiveDescriptor, label: string) => {
    try {
      const info = await api.getEntityFolder(project, descToParams(desc), { count: false })
      if (!info.rel_path || !info.exists) {
        toast.error(`Pas de dossier sur le disque pour ${label}`)
        return
      }
      const abs = expandFluxPath(`$FLUX/DOSSIER_PROJETS/${project}/${info.rel_path}`, settings?.workspace)
      navigate('/projects', { state: { openPath: abs } })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }
}

function useArchiveDelete(project: string) {
  const [pending, setPending] = useState<PendingArchive | null>(null)

  const request = (desc: ArchiveDescriptor, label: string, onRemoved: () => void) => {
    setPending({ desc, label, info: null, onRemoved, busy: false })
    api.getEntityFolder(project, descToParams(desc))
      .then(info => setPending(p => (p ? { ...p, info } : p)))
      .catch(() => setPending(p => (p ? { ...p, info: { rel_path: '', exists: false, file_count: 0 } } : p)))
  }

  const cancel = () => setPending(null)

  const confirm = async () => {
    if (!pending) return
    setPending(p => (p ? { ...p, busy: true } : p))
    const { desc, info } = pending
    try {
      if (desc.kind === 'asset') {
        if (info?.exists && info.rel_path) await api.archiveEntity(project, info.rel_path)
      } else {
        // Server-side: folders (shot + comp / lighting) archived, tokens dropped and the
        // entity removed from production.json with a tombstone, so neither an old
        // publish nor a stale save brings the folder back.
        await api.deleteSeqShot(project, desc.kind, desc.seq, desc.kind === 'shot' ? desc.shot : '')
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
      setPending(p => (p ? { ...p, busy: false } : p))
      return
    }
    pending.onRemoved()
    setPending(null)
  }

  const modal = pending ? (
    <ArchiveConfirm
      label={pending.label} info={pending.info} busy={pending.busy}
      phrase={pending.desc.kind === 'asset' ? '' : DELETE_PHRASE}
      onCancel={cancel} onConfirm={confirm}
    />
  ) : null

  return { request, modal }
}

// Number of a sequence / shot: typed freely, applied once on Enter or blur (a rename
// moves folders on disk, never one per keystroke). Escape restores the current number.
function NumberField({ value, onCommit, width, busy }: {
  value: number
  onCommit: (n: number) => Promise<boolean>
  width: number
  busy?: boolean
}) {
  const shown = Number.isNaN(value) ? '' : String(value)
  const [draft, setDraft] = useState(shown)
  useEffect(() => { setDraft(shown) }, [shown])
  const commit = async () => {
    const n = parseInt(draft, 10)
    if (Number.isNaN(n) || n <= 0 || n === value) { setDraft(shown); return }
    if (!(await onCommit(n))) setDraft(shown)
  }
  return (
    <input
      value={draft} disabled={busy}
      onChange={e => setDraft(e.target.value.replace(/[^0-9]/g, ''))}
      onKeyDown={e => {
        if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
        if (e.key === 'Escape') { setDraft(shown); (e.target as HTMLInputElement).blur() }
      }}
      onBlur={() => { void commit() }}
      title="Entree pour renommer (dossiers compris)"
      placeholder="N°" style={{ ..._input, width }}
    />
  )
}

function ArchiveConfirm({ label, info, busy, phrase, onCancel, onConfirm }: {
  label:     string
  info:      { rel_path: string; exists: boolean; file_count: number } | null
  busy:      boolean
  phrase:    string                  // '' = no word to type
  onCancel:  () => void
  onConfirm: () => void
}) {
  const [typed, setTyped] = useState('')
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onCancel() }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [onCancel])

  const analyzing = info === null
  const count = info?.file_count ?? 0
  const nonEmpty = !!info?.exists && count > 0
  const unlocked = !phrase || typed === phrase
  const canConfirm = !busy && !analyzing && unlocked

  return (
    <div
      onClick={e => { if (e.target === e.currentTarget) onCancel() }}
      style={{
        position: 'fixed', inset: 0, zIndex: 3000, background: 'rgba(0,0,0,0.55)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24,
      }}
    >
      <div style={{
        width: 360, maxWidth: '92vw',
        background: 'var(--paper)', border: '1px solid var(--rule-2)', borderRadius: 12,
        boxShadow: 'var(--shadow)', padding: '18px 18px 14px',
      }}>
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8,
          fontSize: 13, fontWeight: 600, color: 'var(--ink)',
        }}>
          <Trash2 size={15} strokeWidth={1.9} color="var(--err)" />
          Archiver {label} ?
        </div>
        <div style={{ fontSize: 11, color: 'var(--ink-3)', marginBottom: phrase ? 12 : 16, lineHeight: 1.5 }}>
          {analyzing
            ? 'Analyse du dossier…'
            : nonEmpty
              ? `Ce dossier contient ${count} fichier${count > 1 ? 's' : ''}. Il sera déplacé vers ARCHIVE/ (récupérable), pas supprimé.`
              : info?.exists
                ? 'Le dossier (vide) sera déplacé vers ARCHIVE/.'
                : "Aucun dossier sur disque : seule l'entrée logique sera retirée."}
          {phrase && !analyzing && ' Ses autres dossiers (comp, et lighting pour une séquence) partent aussi dans ARCHIVE/.'}
        </div>
        {phrase && (
          <>
            <div style={{ fontSize: 11, color: 'var(--ink-2)', marginBottom: 6 }}>
              Tape <code style={{ fontFamily: 'var(--mono)', fontSize: 11, background: 'var(--paper-2)', border: '1px solid var(--rule)', borderRadius: 4, padding: '1px 5px', color: 'var(--ink)' }}>{phrase}</code> pour confirmer.
            </div>
            <input
              autoFocus value={typed} onChange={e => setTyped(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && canConfirm) onConfirm() }}
              placeholder={phrase} spellCheck={false} autoCapitalize="off" autoCorrect="off"
              style={{
                width: '100%', boxSizing: 'border-box', marginBottom: 14, padding: '6px 9px', fontSize: 12,
                fontFamily: 'var(--mono)', background: 'var(--paper-2)', color: 'var(--ink)', borderRadius: 6, outline: 'none',
                border: `1px solid ${unlocked ? 'var(--err)' : 'var(--rule-2)'}`,
              }}
            />
          </>
        )}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <ProdBtn variant="ghost" size="sm" onClick={onCancel} disabled={busy}>Annuler</ProdBtn>
          <ProdBtn variant="danger" size="sm" onClick={onConfirm} disabled={!canConfirm}>
            <Trash2 size={10} strokeWidth={1.75} /> {busy ? 'Archivage…' : 'Archiver'}
          </ProdBtn>
        </div>
      </div>
    </div>
  )
}

// Lock of a sequence / shot (2026-09-30): anyone locks in one click, unlocking asks
// to type Understand. A locked record cannot be edited, renamed or deleted (the backend
// enforces it too); task progress and comments stay open.
const _lockedFieldset: CSSProperties = { border: 0, padding: 0, margin: 0, minWidth: 0 }

function LockControl({ project, kind, seqName, shotName, own, inherited, onChange }: {
  project:   string
  kind:      'seq' | 'shot'
  seqName:   string
  shotName:  string
  own:       ProductionLock | undefined          // lock of this record
  inherited: ProductionLock | undefined          // lock of its sequence (shots only)
  onChange:  (lock: ProductionLock | undefined) => void
}) {
  const [asking, setAsking] = useState(false)
  const [typed, setTyped] = useState('')
  const [busy, setBusy] = useState(false)
  const call = async (locked: boolean, phrase = '') => {
    setBusy(true)
    try {
      const r = await api.lockSeqShot(project, kind, seqName, shotName, locked, phrase)
      onChange(r.locked ?? undefined)
      setAsking(false); setTyped('')
      toast.success(locked ? `${shotName || seqName} verrouillé` : `${shotName || seqName} déverrouillé`)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }
  if (inherited && !own) {
    return (
      <div style={{ ..._lbl, marginTop: 6, textTransform: 'none', letterSpacing: 0, display: 'flex', gap: 6, alignItems: 'center' }}>
        <Lock size={11} strokeWidth={1.9} /> Verrouillé avec sa séquence {seqName} ({inherited.by})
      </div>
    )
  }
  if (!own) {
    return (
      <ProdBtn full variant="ghost" onClick={() => { void call(true) }} disabled={busy} style={{ marginTop: 6 }}>
        <Lock size={11} strokeWidth={1.75} /> Verrouiller
      </ProdBtn>
    )
  }
  return (
    <div style={{ marginTop: 6 }}>
      <div style={{ ..._lbl, textTransform: 'none', letterSpacing: 0, display: 'flex', gap: 6, alignItems: 'center' }}>
        <Lock size={11} strokeWidth={1.9} /> Verrouillé par {own.by}
      </div>
      {!asking ? (
        <ProdBtn full variant="ghost" onClick={() => setAsking(true)} style={{ marginTop: 6 }}>
          <LockOpen size={11} strokeWidth={1.75} /> Déverrouiller
        </ProdBtn>
      ) : (
        <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
          <input
            autoFocus value={typed} onChange={e => setTyped(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && typed === DELETE_PHRASE) void call(false, typed)
              if (e.key === 'Escape') { setAsking(false); setTyped('') }
            }}
            placeholder={`Tape ${DELETE_PHRASE}`} spellCheck={false}
            style={{ ..._input, flex: 1, fontFamily: 'var(--mono)' }}
          />
          <ProdBtn size="sm" onClick={() => { void call(false, typed) }} disabled={busy || typed !== DELETE_PHRASE}>
            <LockOpen size={10} strokeWidth={1.75} /> OK
          </ProdBtn>
        </div>
      )}
    </div>
  )
}

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
  const selectedSeq = selection.kind === 'seq'
    ? state.sequences.find(s => s.id === selection.id) ?? null
    : null
  const selectedShot = selection.kind === 'shot'
    ? state.shots.find(s => s.id === selection.id) ?? null
    : null

  // Shot task tokens: shot CLASS tokens (templated with {seq}{shot}).
  const [shotClassTokens, setShotClassTokens] = useState<string[]>([])
  useEffect(() => {
    let alive = true
    if (mode !== 'shot') return () => { alive = false }
    api.getTokens(project)
      .then(r => {
        if (!alive) return
        const cls = (r.tokens?.CLASS ?? {}) as Record<string, string>
        const shotTokens = Object.entries(cls)
          .filter(([, path]) => typeof path === 'string' && path.includes('{seq}') && path.includes('{shot}'))
          .map(([k]) => k.toUpperCase())
          .sort()
        setShotClassTokens(shotTokens)
      })
      .catch(() => { if (alive) setShotClassTokens([]) })
    return () => { alive = false }
  }, [project, mode])

  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      <div style={{ padding: '10px 12px 6px', borderBottom: '1px solid var(--rule)' }}>
        <div className="cap" style={{ fontSize: 9, letterSpacing: '0.09em', color: 'var(--ink-3)' }}>Edit</div>
      </div>

      {mode === 'asset' && selection.kind === 'none' && (
        <CreateSection
          setState={setState}
          setSelection={setSelection}
          activeCategory={activeCategory}
        />
      )}

      {mode === 'asset' && selectedAsset && (
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

      {mode === 'asset' && selectedGroup && (
        <GroupSection group={selectedGroup} setState={setState} setSelection={setSelection} />
      )}

      {mode === 'shot' && selection.kind === 'none' && (
        <ShotCreateSection setState={setState} setSelection={setSelection} state={state} />
      )}

      {mode === 'shot' && selectedSeq && (
        <SeqSection
          project={project}
          seq={selectedSeq}
          state={state}
          setState={setState}
          setSelection={setSelection}
          shotClassTokens={shotClassTokens}
        />
      )}

      {mode === 'shot' && selectedShot && (
        <ShotSection
          project={project}
          shot={selectedShot}
          state={state}
          setState={setState}
          setSelection={setSelection}
          shotClassTokens={shotClassTokens}
        />
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
            padding: '4px 10px', borderRadius: 5,
            background: categoryColor(activeCategory), color: 'var(--paper)',
            fontFamily: 'var(--sans)', fontSize: 10, fontWeight: 600, letterSpacing: '0.04em',
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

  const archiveDel = useArchiveDelete(project)
  const remove = () => {
    archiveDel.request(
      { kind: 'asset', class_token: asset.class, name: asset.name },
      `${asset.class} · ${asset.name}`,
      () => {
        setState(prev => ({ ...prev, assets: prev.assets.filter(a => a.id !== asset.id) }))
        setSelection({ kind: 'none' })
      },
    )
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
      {archiveDel.modal}
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

// ── shot / seq sections ──────────────────────────────────────────────────────
const padSeq = (n: number, len = 3) => String(n).padStart(len, '0')
const parseSeqNum  = (name: string) => Number((name.match(/SEQ(\d+)/i) || [])[1] ?? NaN)
const parseShotNum = (name: string) => Number((name.match(/SHOT(\d+)/i) || [])[1] ?? NaN)
const ANIM_DEFAULT_SUBTASKS = ['BLOCK', 'SPLINE', 'POLISH']

// Compute the .order value that inserts a new entity numerically-in-place
// among *sortedNumbers* (values already sorted ascending). Entity is placed
// right before the first entry with a strictly greater number; if none, at end.
function computeInsertOrder(existing: Array<{ order: number; num: number }>, newNum: number): number {
  const sorted = [...existing].sort((a, b) => a.order - b.order)
  // Find the first item whose num > newNum → new order = that order (shift later items).
  const idx = sorted.findIndex(x => x.num > newNum)
  return idx === -1 ? sorted.length : sorted[idx].order
}

// After inserting an item at position *pos*, shift every order >= pos by +1 (for the "before N+1" semantic).
function shiftOrders<T extends { id: string; order: number }>(list: T[], fromOrder: number, exceptId: string): T[] {
  return list.map(x => (x.id !== exceptId && x.order >= fromOrder ? { ...x, order: x.order + 1 } : x))
}

function ShotCreateSection({ state, setState, setSelection }: {
  state:        ProductionState
  setState:     (patch: (prev: ProductionState) => ProductionState) => void
  setSelection: (s: Selection) => void
}) {
  const { t } = useI18n()
  const [num, setNum] = useState('')
  const [label, setLabel] = useState('')
  const create = () => {
    const n = parseInt(num, 10)
    if (Number.isNaN(n) || n <= 0) return
    const nm = `SEQ${padSeq(n)}`
    if (state.sequences.some(s => s.name === nm)) return
    const id = nid('seq')
    const pos = computeInsertOrder(
      state.sequences.map(s => ({ order: s.order, num: parseSeqNum(s.name) })).filter(x => !Number.isNaN(x.num)),
      n,
    )
    setState(prev => ({
      ...prev,
      sequences: [
        ...shiftOrders(prev.sequences, pos, ''),
        { id, name: nm, label: label.trim() || undefined,
          order: pos, tasks: [], assets: [], notes: '', origin: 'user' },
      ],
    }))
    setSelection({ kind: 'seq', id })
    setNum(''); setLabel('')
  }
  return (
    <div style={_pad}>
      <div style={_lbl}>{t('prod.newSequence')}</div>
      <div style={{ display: 'flex', gap: 6 }}>
        <input
          value={num}
          placeholder="N°"
          onChange={e => setNum(e.target.value.replace(/[^0-9]/g, ''))}
          onKeyDown={e => { if (e.key === 'Enter') create() }}
          style={{ ..._input, width: 70 }}
        />
        <input
          value={label}
          placeholder="Label (optionnel)"
          onChange={e => setLabel(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') create() }}
          style={{ ..._input, flex: 1, fontFamily: 'var(--sans)' }}
        />
      </div>
      <ProdBtn full onClick={create} style={{ marginTop: 6 }} disabled={!num.trim()}>
        <Plus size={12} strokeWidth={2} /> {t('prod.newSequence')}
      </ProdBtn>
    </div>
  )
}

function SeqSection({ project, seq, state, setState, setSelection, shotClassTokens }: {
  project:         string
  seq:             ProductionSequence
  state:           ProductionState
  setState:        (patch: (prev: ProductionState) => ProductionState) => void
  setSelection:    (s: Selection) => void
  shotClassTokens: string[]
}) {
  const { t }         = useI18n()
  const [shotNum, setShotNum] = useState('')
  const [shotLabelInput, setShotLabelInput] = useState('')
  const [taskName, setTaskName] = useState('')
  const [taskSubtask, setTaskSubtask] = useState('')

  const seqNum = parseSeqNum(seq.name)
  const patchSeq = (p: Partial<ProductionSequence>) => {
    setState(prev => ({ ...prev, sequences: prev.sequences.map(s => s.id === seq.id ? { ...s, ...p, origin: 'user' } : s) }))
  }
  const [renaming, setRenaming] = useState(false)
  const changeSeqNumber = async (n: number): Promise<boolean> => {
    const newName = `SEQ${padSeq(n)}`
    if (newName === seq.name) return true
    if (state.sequences.some(s => s.id !== seq.id && s.name === newName)) {
      toast.error(`${newName} existe déjà`); return false
    }
    setRenaming(true)
    try {
      const r = await api.renameSeqShot(project, 'seq', seq.name, '', newName)
      patchSeq({ name: newName })
      toast.success(`${seq.name} renommée en ${newName}`)
      for (const w of r.warnings ?? []) toast.warning(w)
      return true
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
      return false
    } finally {
      setRenaming(false)
    }
  }
  // Default Houdini render scene of the sequence (ADR 0036), built offline by hython.
  const [renderBusy, setRenderBusy] = useState(false)
  const makeRenderScene = async () => {
    setRenderBusy(true)
    try {
      const r = await api.createSequenceRenderScene(project, seq.name)
      if (!r.created) toast.info(`La scène de rendu existe déjà : ${r.path}`)
      else {
        const missing = r.without_stage?.length ? ` · sans stage : ${r.without_stage.join(', ')}` : ''
        toast.success(`Scène de rendu créée (${r.shots?.length ?? 0} shots)${missing}`)
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setRenderBusy(false)
    }
  }
  const openFolder = useOpenEntityFolder(project)
  const archiveDel = useArchiveDelete(project)
  const remove = () => {
    archiveDel.request(
      { kind: 'seq', seq: seq.name },
      `séquence ${seq.name}`,
      () => {
        setState(prev => ({
          ...prev,
          sequences: prev.sequences.filter(s => s.id !== seq.id),
          shots:     prev.shots.filter(s => s.seq_id !== seq.id),
        }))
        setSelection({ kind: 'none' })
      },
    )
  }
  const createShot = () => {
    // No number entered → auto-pick max(existing shot num) + 1 (or 1 if none).
    let n = parseInt(shotNum, 10)
    if (Number.isNaN(n) || n <= 0) {
      const nums = state.shots
        .filter(s => s.seq_id === seq.id)
        .map(s => parseShotNum(s.name))
        .filter(x => !Number.isNaN(x))
      n = nums.length ? Math.max(...nums) + 1 : 1
    }
    const nm = `SHOT${padSeq(n)}`
    if (state.shots.some(s => s.seq_id === seq.id && s.name === nm)) return
    const id = nid('shot')
    const siblings = state.shots.filter(s => s.seq_id === seq.id)
    const pos = computeInsertOrder(
      siblings.map(s => ({ order: s.order, num: parseShotNum(s.name) })).filter(x => !Number.isNaN(x.num)),
      n,
    )
    const shiftedInSeq = shiftOrders(siblings, pos, '')
    const shiftedIds = new Set(shiftedInSeq.map(s => s.id))
    setState(prev => ({
      ...prev,
      shots: [
        ...prev.shots.map(s => shiftedIds.has(s.id) ? { ...s, order: s.order + 1 } : s),
        { id, seq_id: seq.id, name: nm, label: shotLabelInput.trim() || undefined,
          order: pos,
          inherit_tasks: true, inherit_assets: true,
          tasks: [], assets: [], task_details: {}, origin: 'user' },
      ],
    }))
    // Keep the seq focused; user is bulk-adding shots.
    setShotNum(''); setShotLabelInput('')
  }

  const addTask = () => {
    const label = taskName.trim().toUpperCase()
    if (!label) return
    const subtaskUp = taskSubtask.trim().toUpperCase()
    const existing = seq.tasks.find(x =>
      x.name.toUpperCase() === label || x.type_tokens.map(t => t.toUpperCase()).includes(label))
    if (existing) {
      setState(prev => ({
        ...prev,
        sequences: prev.sequences.map(s => s.id !== seq.id ? s : {
          ...s,
          tasks: s.tasks.map(x => x.id !== existing.id ? x : {
            ...x,
            known_subtasks: subtaskUp && !x.known_subtasks.map(k => k.toUpperCase()).includes(subtaskUp)
              ? [...x.known_subtasks, subtaskUp]
              : x.known_subtasks,
          }),
        }),
      }))
      setTaskName(''); setTaskSubtask('')
      return
    }
    const known: string[] = []
    if (subtaskUp) known.push(subtaskUp)
    if (label === 'ANIM') for (const s of ANIM_DEFAULT_SUBTASKS) if (!known.includes(s)) known.push(s)
    const newTask: ProductionTask = {
      id: nid('t'), name: label, order: seq.tasks.length,
      type_tokens: [label], known_subtasks: known, origin: 'user',
    }
    setState(prev => ({
      ...prev,
      sequences: prev.sequences.map(s => s.id === seq.id ? { ...s, tasks: [...s.tasks, newTask] } : s),
    }))
    setTaskName(''); setTaskSubtask('')
  }

  const locked = !!seq.locked
  const setLock = (lock: ProductionLock | undefined) =>
    setState(prev => ({ ...prev, sequences: prev.sequences.map(s => s.id === seq.id ? { ...s, locked: lock } : s) }))

  return (
    <>
      <div style={_pad}>
        <div style={_lbl}>SÉQUENCE · {seq.name}{seq.label ? ` — ${seq.label}` : ''}</div>
        <fieldset disabled={locked} style={_lockedFieldset}>
        <div style={{ display: 'flex', gap: 6, alignItems: 'stretch' }}>
          <NumberField value={seqNum} onCommit={changeSeqNumber} width={60} busy={renaming} />
          <input
            value={seq.label ?? ''}
            onChange={e => patchSeq({ label: e.target.value || undefined })}
            placeholder="Label (optionnel)"
            style={{ ..._input, flex: 1, fontFamily: 'var(--sans)' }}
          />
          <SeqColorPicker seq={seq} onPick={c => patchSeq({ color: c })} onReset={() => patchSeq({ color: undefined })} />
        </div>
        </fieldset>
        <ProdBtn full variant="ghost" onClick={() => { void openFolder({ kind: 'seq', seq: seq.name }, seq.name) }} style={{ marginTop: 6 }}>
          <FolderOpen size={11} strokeWidth={1.75} /> Ouvrir dans le Folder Manager
        </ProdBtn>
        <LockControl project={project} kind="seq" seqName={seq.name} shotName=""
                     own={seq.locked} inherited={undefined} onChange={setLock} />
        {!locked && (
          <ProdBtn full variant="danger" onClick={remove} style={{ marginTop: 6 }}>
            <Trash2 size={11} strokeWidth={1.75} /> {t('prod.delete')}
          </ProdBtn>
        )}
      </div>

      <div style={_pad}>
        <div style={_lbl}>RENDU</div>
        <ProdBtn full onClick={() => { void makeRenderScene() }} disabled={renderBusy}>
          <Clapperboard size={12} strokeWidth={1.75} /> {renderBusy ? 'Création en cours…' : 'Scène de rendu Houdini'}
        </ProdBtn>
        <div style={{ ..._lbl, marginTop: 6, textTransform: 'none', letterSpacing: 0 }}>
          Un FLUX Shot et un ROP Karma par shot, dans {seq.name}_render.hip. Une scène existante n'est jamais écrasée.
        </div>
      </div>

      <fieldset disabled={locked} style={_lockedFieldset}>
      <AssetsPicker
        state={state}
        setState={setState}
        entityKind="seq"
        entity={seq}
      />
      </fieldset>

      <div style={_pad}>
        <div style={_lbl}>{t('prod.newShot')}</div>
        <div style={{ display: 'flex', gap: 6 }}>
          <input
            value={shotNum}
            placeholder="N°"
            onChange={e => setShotNum(e.target.value.replace(/[^0-9]/g, ''))}
            onKeyDown={e => { if (e.key === 'Enter') createShot() }}
            style={{ ..._input, width: 70 }}
          />
          <input
            value={shotLabelInput}
            placeholder="Label (optionnel)"
            onChange={e => setShotLabelInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') createShot() }}
            style={{ ..._input, flex: 1, fontFamily: 'var(--sans)' }}
          />
        </div>
        <ProdBtn full onClick={createShot} style={{ marginTop: 6 }}>
          <Plus size={12} strokeWidth={2} /> {t('prod.newShot')}
        </ProdBtn>
      </div>

      <fieldset disabled={locked} style={_lockedFieldset}>
      <div style={_pad}>
        <div style={_lbl}>{t('prod.newTask')} (séquence)</div>
        <input
          value={taskName}
          onChange={e => setTaskName(e.target.value.toUpperCase())}
          list="prod-shot-task-tokens"
          style={{ ..._input, width: '100%' }}
        />
        <datalist id="prod-shot-task-tokens">
          {shotClassTokens.map(x => <option key={x} value={x} />)}
        </datalist>
        <div style={{ ..._lbl, marginTop: 6 }}>SUBTASK (optionnel)</div>
        <input
          value={taskSubtask}
          onChange={e => setTaskSubtask(e.target.value.toUpperCase())}
          onKeyDown={e => { if (e.key === 'Enter') addTask() }}
          style={{ ..._input, width: '100%' }}
        />
        <ProdBtn full onClick={addTask} style={{ marginTop: 6 }} disabled={!taskName.trim()}>
          <Plus size={12} strokeWidth={2} /> {t('prod.newTask')}
        </ProdBtn>
      </div>
      </fieldset>
      {archiveDel.modal}
    </>
  )
}

function ShotSection({ project, shot, state, setState, setSelection, shotClassTokens }: {
  project:         string
  shot:            ProductionShot
  state:           ProductionState
  setState:        (patch: (prev: ProductionState) => ProductionState) => void
  setSelection:    (s: Selection) => void
  shotClassTokens: string[]
}) {
  const { t } = useI18n()
  const seq = state.sequences.find(s => s.id === shot.seq_id) ?? null
  const [taskName, setTaskName]     = useState('')
  const [taskSubtask, setTaskSubtask] = useState('')

  const shotNum = parseShotNum(shot.name)
  const patchShot = (p: Partial<ProductionShot>) => {
    setState(prev => ({ ...prev, shots: prev.shots.map(s => s.id === shot.id ? { ...s, ...p, origin: 'user' } : s) }))
  }
  const [renaming, setRenaming] = useState(false)
  const changeShotNumber = async (n: number): Promise<boolean> => {
    const newName = `SHOT${padSeq(n)}`
    if (newName === shot.name) return true
    if (!seq) return false
    if (state.shots.some(s => s.id !== shot.id && s.seq_id === shot.seq_id && s.name === newName)) {
      toast.error(`${newName} existe déjà dans ${seq.name}`); return false
    }
    setRenaming(true)
    try {
      const r = await api.renameSeqShot(project, 'shot', seq.name, shot.name, newName)
      patchShot({ name: newName })
      toast.success(`${shot.name} renommé en ${newName}`)
      for (const w of r.warnings ?? []) toast.warning(w)
      return true
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
      return false
    } finally {
      setRenaming(false)
    }
  }
  const openFolder = useOpenEntityFolder(project)
  const archiveDel = useArchiveDelete(project)
  const remove = () => {
    archiveDel.request(
      { kind: 'shot', seq: seq?.name ?? '', shot: shot.name },
      `shot ${seq?.name ?? '?'} · ${shot.name}`,
      () => {
        setState(prev => ({ ...prev, shots: prev.shots.filter(s => s.id !== shot.id) }))
        setSelection({ kind: 'none' })
      },
    )
  }
  const addTask = () => {
    const label = taskName.trim().toUpperCase()
    if (!label) return
    const subtaskUp = taskSubtask.trim().toUpperCase()
    const existing = shot.tasks.find(x =>
      x.name.toUpperCase() === label || x.type_tokens.map(t => t.toUpperCase()).includes(label))
    if (existing) {
      setState(prev => ({
        ...prev,
        shots: prev.shots.map(s => s.id !== shot.id ? s : {
          ...s,
          tasks: s.tasks.map(x => x.id !== existing.id ? x : {
            ...x,
            known_subtasks: subtaskUp && !x.known_subtasks.map(k => k.toUpperCase()).includes(subtaskUp)
              ? [...x.known_subtasks, subtaskUp]
              : x.known_subtasks,
          }),
        }),
      }))
      setTaskName(''); setTaskSubtask('')
      return
    }
    const known: string[] = []
    if (subtaskUp) known.push(subtaskUp)
    if (label === 'ANIM') for (const s of ANIM_DEFAULT_SUBTASKS) if (!known.includes(s)) known.push(s)
    const newTask: ProductionTask = {
      id: nid('t'), name: label, order: shot.tasks.length,
      type_tokens: [label], known_subtasks: known, origin: 'user',
    }
    setState(prev => ({
      ...prev,
      shots: prev.shots.map(s => s.id === shot.id ? { ...s, tasks: [...s.tasks, newTask] } : s),
    }))
    setTaskName(''); setTaskSubtask('')
  }

  const locked = !!shot.locked || !!seq?.locked
  const setLock = (lock: ProductionLock | undefined) =>
    setState(prev => ({ ...prev, shots: prev.shots.map(s => s.id === shot.id ? { ...s, locked: lock } : s) }))

  return (
    <>
      <div style={_pad}>
        <div style={_lbl}>SHOT · {seq?.name ?? '?'} · {shot.name}{shot.label ? ` — ${shot.label}` : ''}</div>
        <fieldset disabled={locked} style={_lockedFieldset}>
        <div style={{ display: 'flex', gap: 6 }}>
          <NumberField value={shotNum} onCommit={changeShotNumber} width={70} busy={renaming} />
          <input
            value={shot.label ?? ''}
            onChange={e => patchShot({ label: e.target.value || undefined })}
            placeholder="Label (optionnel)"
            style={{ ..._input, flex: 1, fontFamily: 'var(--sans)' }}
          />
        </div>
        <div style={{ ..._lbl, marginTop: 8 }}>Plage d'images (stage USD)</div>
        <div style={{ display: 'flex', gap: 6 }}>
          <input
            value={shot.frame_start ?? ''}
            onChange={e => patchShot({ frame_start: parseFrame(e.target.value) })}
            placeholder="Debut" style={{ ..._input, flex: 1 }}
          />
          <input
            value={shot.frame_end ?? ''}
            onChange={e => patchShot({ frame_end: parseFrame(e.target.value) })}
            placeholder="Fin" style={{ ..._input, flex: 1 }}
          />
        </div>
        </fieldset>
        <ProdBtn full variant="ghost" disabled={!seq} style={{ marginTop: 6 }}
                 onClick={() => { if (seq) void openFolder({ kind: 'shot', seq: seq.name, shot: shot.name }, `${seq.name} · ${shot.name}`) }}>
          <FolderOpen size={11} strokeWidth={1.75} /> Ouvrir dans le Folder Manager
        </ProdBtn>
        {seq && (
          <LockControl project={project} kind="shot" seqName={seq.name} shotName={shot.name}
                       own={shot.locked} inherited={seq.locked} onChange={setLock} />
        )}
        {!locked && (
          <ProdBtn full variant="danger" onClick={remove} style={{ marginTop: 6 }}>
            <Trash2 size={11} strokeWidth={1.75} /> {t('prod.delete')}
          </ProdBtn>
        )}
      </div>

      <fieldset disabled={locked} style={_lockedFieldset}>
      <div style={_pad}>
        <label style={{ ..._lbl, display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', marginBottom: 6 }}>
          <input type="checkbox" checked={shot.inherit_tasks}
                 onChange={e => patchShot({ inherit_tasks: e.target.checked })}
                 style={{ accentColor: 'var(--accent)' }} />
          <span>{t('prod.inheritTasks')}</span>
        </label>
        <label style={{ ..._lbl, display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
          <input type="checkbox" checked={shot.inherit_assets}
                 onChange={e => patchShot({ inherit_assets: e.target.checked })}
                 style={{ accentColor: 'var(--accent)' }} />
          <span>{t('prod.inheritAssets')}</span>
        </label>
      </div>

      <AssetsPicker state={state} setState={setState} entityKind="shot" entity={shot}
                    title={shot.inherit_assets ? 'Casting du shot (en plus de la sequence)' : undefined} />

      {!shot.inherit_tasks && (
        <div style={_pad}>
          <div style={_lbl}>{t('prod.newTask')}</div>
          <input
            value={taskName}
            onChange={e => setTaskName(e.target.value.toUpperCase())}
            list="prod-shot-task-tokens"
            style={{ ..._input, width: '100%' }}
          />
          <datalist id="prod-shot-task-tokens">
            {shotClassTokens.map(x => <option key={x} value={x} />)}
          </datalist>
          <div style={{ ..._lbl, marginTop: 6 }}>SUBTASK (optionnel — auto pour ANIM)</div>
          <input
            value={taskSubtask}
            onChange={e => setTaskSubtask(e.target.value.toUpperCase())}
            onKeyDown={e => { if (e.key === 'Enter') addTask() }}
            style={{ ..._input, width: '100%' }}
          />
          <ProdBtn full onClick={addTask} style={{ marginTop: 6 }} disabled={!taskName.trim()}>
            <Plus size={12} strokeWidth={2} /> {t('prod.newTask')}
          </ProdBtn>
        </div>
      )}
      </fieldset>
      {archiveDel.modal}
    </>
  )
}

// ── assets picker (button + modal box) ──────────────────────────────────────
function AssetsPicker({ state, setState, entityKind, entity, title }: {
  state:      ProductionState
  setState:   (patch: (prev: ProductionState) => ProductionState) => void
  entityKind: 'seq' | 'shot'
  entity:     ProductionSequence | ProductionShot
  title?:     string
}) {
  const { t } = useI18n()
  const [modalOpen, setModalOpen] = useState(false)
  const linked = entity.assets ?? []

  const editLinks = (fn: (arr: CastingLink[]) => CastingLink[]) => {
    setState(prev => {
      if (entityKind === 'seq') {
        return { ...prev, sequences: prev.sequences.map(s => s.id === entity.id ? { ...s, assets: fn(s.assets ?? []) } : s) }
      }
      return { ...prev, shots: prev.shots.map(s => s.id === entity.id ? { ...s, assets: fn(s.assets ?? []) } : s) }
    })
  }
  const removeChip = (id: string) => editLinks(arr => arr.filter(x => x.id !== id))
  // Number of instances in the shot stage (ADR 0020): DINGO_01, DINGO_02...
  const setCount = (id: string, delta: number) => editLinks(arr => arr.map(x => x.id === id
    ? { ...x, count: Math.max(1, (x.count ?? 1) + delta) } : x))

  return (
    <div style={_pad}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
        <div style={_lbl}>{title ?? t('prod.tabAssets')}</div>
        <span style={{ fontSize: 9, color: 'var(--ink-4)' }}>· {linked.length}</span>
        <span style={{ flex: 1 }} />
        <ProdBtn size="sm" variant="ghost" onClick={() => setModalOpen(true)}>
          <Plus size={10} strokeWidth={2} /> Ajouter
        </ProdBtn>
      </div>

      {linked.length === 0 && (
        <div style={{ fontSize: 10, color: 'var(--ink-4)' }}>—</div>
      )}
      {linked.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
          {linked.map(l => {
            const a = state.assets.find(x => x.id === l.id)
            const color = a ? categoryColor(a.class) : 'var(--ink-4)'
            return (
              <span key={l.id}
                    title={l.origin === 'auto' ? `${l.ref} (ajoute par une anim publiee)` : l.ref}
                    style={{
                      display: 'inline-flex', alignItems: 'center', gap: 4,
                      padding: '3px 9px', borderRadius: 999,
                      background: color, color: 'var(--paper)',
                      fontFamily: 'var(--sans)', fontSize: 10, fontWeight: 600,
                    }}>
                {a?.name ?? l.ref}
                {(l.count ?? 1) > 1 && <span style={{ opacity: 0.85 }}>x{l.count}</span>}
                <span title="Une instance de moins" onClick={() => setCount(l.id, -1)}
                      style={{ cursor: 'pointer', opacity: 0.75, padding: '0 2px' }}>-</span>
                <span title="Une instance de plus" onClick={() => setCount(l.id, 1)}
                      style={{ cursor: 'pointer', opacity: 0.75, padding: '0 2px' }}>+</span>
                <span title="Retirer" onClick={() => removeChip(l.id)}
                      style={{ cursor: 'pointer', opacity: 0.75 }}>×</span>
              </span>
            )
          })}
        </div>
      )}

      {modalOpen && (
        <AssetsPickerModal
          state={state}
          setState={setState}
          entityKind={entityKind}
          entity={entity}
          onClose={() => setModalOpen(false)}
        />
      )}
    </div>
  )
}

function AssetsPickerModal({ state, setState, entityKind, entity, onClose }: {
  state:      ProductionState
  setState:   (patch: (prev: ProductionState) => ProductionState) => void
  entityKind: 'seq' | 'shot'
  entity:     ProductionSequence | ProductionShot
  onClose:    () => void
}) {
  const { t } = useI18n()
  const [query, setQuery] = useState('')

  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [onClose])

  const linkedIds = new Set((entity.assets ?? []).map(l => l.id))
  const toggle = (a: Asset) => {
    const ref = `${a.class}/${a.name}`
    setState(prev => {
      const patchAssets = (existing: CastingLink[]) => {
        if (existing.some(x => x.id === a.id)) return existing.filter(x => x.id !== a.id)
        return [...existing, { id: a.id, ref }]
      }
      if (entityKind === 'seq') {
        return { ...prev, sequences: prev.sequences.map(s => s.id === entity.id ? { ...s, assets: patchAssets(s.assets ?? []) } : s) }
      }
      return { ...prev, shots: prev.shots.map(s => s.id === entity.id ? { ...s, assets: patchAssets(s.assets ?? []) } : s) }
    })
  }

  const byCategory = useMemo(() => {
    const q = query.trim().toUpperCase()
    const m = new Map<string, Asset[]>()
    for (const cls of CATEGORY_ORDER) m.set(cls, [])
    for (const a of state.assets) {
      if (q && !a.name.toUpperCase().includes(q) && !a.class.toUpperCase().includes(q)) continue
      const c = a.class.toUpperCase()
      const list = m.get(c) ?? []
      list.push(a); m.set(c, list)
    }
    for (const arr of m.values()) arr.sort((a, b) => a.name.localeCompare(b.name))
    return m
  }, [state.assets, query])

  const title = entityKind === 'seq'
    ? `Assets — ${(entity as ProductionSequence).name}`
    : `Assets — ${(entity as ProductionShot).name}`

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)', zIndex: 2000,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }} onClick={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div style={{
        background: 'var(--paper)', border: '1px solid var(--rule-2)', borderRadius: 12,
        boxShadow: 'var(--shadow)', width: 640, maxWidth: '92vw',
        maxHeight: '80vh', display: 'flex', flexDirection: 'column',
      }}>
        <div style={{
          display: 'flex', alignItems: 'center', gap: 10,
          padding: '14px 18px', borderBottom: '1px solid var(--rule)',
        }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)' }}>{title}</div>
          <span style={{ fontSize: 10, color: 'var(--ink-4)' }}>
            {t('prod.tabAssets')} · {linkedIds.size} lié{linkedIds.size > 1 ? 's' : ''}
          </span>
          <span style={{ flex: 1 }} />
          <button onClick={onClose} title="Fermer" style={{
            width: 26, height: 22, borderRadius: 4, border: '1px solid var(--rule-2)',
            background: 'var(--paper-2)', color: 'var(--ink-2)', cursor: 'pointer',
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          }}><X size={12} strokeWidth={1.75} /></button>
        </div>

        <div style={{ padding: '10px 18px', borderBottom: '1px solid var(--rule)' }}>
          <input
            autoFocus
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Rechercher un asset…"
            style={{
              width: '100%', height: 32,
              background: 'var(--paper-2)', color: 'var(--ink)',
              border: '1px solid var(--rule-2)', borderRadius: 6,
              padding: '0 10px', outline: 'none',
              fontFamily: 'var(--sans)', fontSize: 11,
            }}
          />
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: '12px 18px' }}>
          {state.assets.length === 0 && (
            <div style={{ fontSize: 11, color: 'var(--ink-4)' }}>Aucun asset dans ce projet.</div>
          )}
          {CATEGORY_ORDER.map(cls => {
            const arr = byCategory.get(cls) ?? []
            if (arr.length === 0) return null
            const color = categoryColor(cls)
            return (
              <div key={cls} style={{ marginBottom: 16 }}>
                <div style={{
                  display: 'inline-flex', alignItems: 'center', gap: 6, marginBottom: 8,
                  padding: '4px 10px', borderRadius: 5,
                  background: color, color: 'var(--paper)',
                  fontFamily: 'var(--sans)', fontSize: 10, fontWeight: 600, letterSpacing: '0.04em',
                }}>
                  <span style={{ width: 5, height: 5, borderRadius: '50%', background: 'var(--paper)' }} />
                  {t(categoryLabelKey(cls)) || cls}
                  <span style={{ opacity: 0.75 }}>· {arr.length}</span>
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  {arr.map(a => {
                    const on = linkedIds.has(a.id)
                    return (
                      <button key={a.id} onClick={() => toggle(a)} title={`${a.class}/${a.name}`}
                              style={{
                                display: 'inline-flex', alignItems: 'center', gap: 5,
                                padding: '6px 12px', borderRadius: 8,
                                background: on ? color : 'var(--paper-2)',
                                color: on ? 'var(--paper)' : 'var(--ink-2)',
                                border: `1px solid ${on ? color : 'var(--rule-2)'}`,
                                fontFamily: 'var(--sans)', fontSize: 11, fontWeight: on ? 600 : 500,
                                cursor: 'pointer',
                                boxShadow: on ? '0 2px 4px rgba(0,0,0,0.25)' : 'none',
                              }}>
                        {on && <Check size={11} strokeWidth={2.5} />}
                        {a.name}
                      </button>
                    )
                  })}
                </div>
              </div>
            )
          })}
        </div>

        <div style={{
          display: 'flex', justifyContent: 'flex-end', gap: 8,
          padding: '12px 18px', borderTop: '1px solid var(--rule)',
        }}>
          <ProdBtn variant="ghost" onClick={onClose}>Fermer</ProdBtn>
        </div>
      </div>
    </div>
  )
}

// ── seq color picker ────────────────────────────────────────────────────────
function SeqColorPicker({ seq, onPick, onReset }: {
  seq:     ProductionSequence
  onPick:  (hex: string) => void
  onReset: () => void
}) {
  const effective = seq.color || defaultSeqColor(seq.id || seq.name)
  const shotShade = shotColorFromSeqColor(effective)
  const isCustom = !!seq.color
  return (
    <label
      title={`Couleur de la séquence · shot: dérivé\nClic-droit : réinitialiser`}
      onContextMenu={e => { e.preventDefault(); if (isCustom) onReset() }}
      style={{
        position: 'relative', width: 30, minHeight: 32,
        borderRadius: 6, cursor: 'pointer',
        border: '1px solid var(--rule-2)',
        overflow: 'hidden', flexShrink: 0,
        display: 'flex', flexDirection: 'column',
      }}
    >
      <div style={{ flex: 3, background: effective }} />
      <div style={{ flex: 1, background: shotShade, borderTop: '1px solid rgba(0,0,0,0.15)' }} />
      <input
        type="color"
        value={effective}
        onChange={e => onPick(e.target.value)}
        style={{ position: 'absolute', inset: 0, opacity: 0, cursor: 'pointer' }}
      />
    </label>
  )
}

// ── inline styles ────────────────────────────────────────────────────────────
const _pad: React.CSSProperties = { padding: '12px 12px 10px', borderBottom: '1px solid var(--rule)' }
// Frame number typed in a shot range field; empty or invalid = not set.
function parseFrame(raw: string): number | undefined {
  const v = raw.replace(/[^0-9-]/g, '')
  if (!v || v === '-') return undefined
  const n = parseInt(v, 10)
  return Number.isNaN(n) ? undefined : n
}

const _lbl: React.CSSProperties = {
  fontFamily: 'var(--sans)', fontSize: 10, fontWeight: 600,
  letterSpacing: '0.05em', color: 'var(--ink-3)',
  textTransform: 'uppercase', marginBottom: 5,
}
const _input: React.CSSProperties = {
  background: 'var(--paper)', color: 'var(--ink)',
  border: '1px solid var(--rule-2)', borderRadius: 6,
  padding: '6px 9px', fontSize: 11, fontFamily: 'var(--sans)',
  outline: 'none',
  // An <input> keeps an intrinsic ~150 px width: two in a row overflowed the 260 px panel.
  minWidth: 0, boxSizing: 'border-box',
}
