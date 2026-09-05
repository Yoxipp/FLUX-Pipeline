// TaskDetail — Notes + completion + subtasks + Comments + Recent Publishes.
//
// Also used for the Subtask view; when `subtaskFilter` is set, the Subtasks
// section is hidden and detail state (notes/completion/comments) writes into
// `task_details[<taskName>|<subtask>]` — passed as `detailKey`.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import {
  Check, Copy, Download, Film, FolderOpen, FolderTree, Heart,
  Image as ImageIcon, Pin, Trash2, UploadCloud, X,
} from 'lucide-react'
import { api } from '../../api/client'
import { useI18n } from '../../i18n'
import { useProject } from '../../ProjectContext'
import { useCommentReadState } from '../../hooks/useCommentReadState'
import { useSettings } from '../../hooks/useSettings'
import type {
  ProductionAsset as Asset,
  ProductionComment, ProductionPublish,
  ProductionTask, ProductionTaskDetail,
} from '../../types'
import { expandFluxPath, taskColorFromName } from './util'

interface Props {
  asset:         Asset
  task:          ProductionTask
  entityKind:    'asset' | 'shot' | 'seq'       // asset shim carries seq/shot names for shots
  publishes:     ProductionPublish[]
  subtaskFilter: string | null
  detailKey:     string                         // task_details key : "<task>" or "<task>|<subtask>"
  pinned?:       boolean
  onTogglePin?:  () => void
  onPatchTask:   (patch: Partial<ProductionTask>) => void
  onPatchDetail: (patch: Partial<ProductionTaskDetail>) => void
  onDeleteTask:  () => void
}

const nid = (prefix: string) => `${prefix}_${Math.random().toString(36).slice(2, 12)}`

export function TaskDetail({
  asset, task, entityKind, publishes, subtaskFilter, detailKey,
  pinned, onTogglePin,
  onPatchTask, onPatchDetail, onDeleteTask,
}: Props) {
  const { t }        = useI18n()
  const navigate     = useNavigate()
  const { settings } = useSettings()
  const { project }  = useProject()
  const readState    = useCommentReadState()
  const workspace    = settings?.workspace
  const color        = taskColorFromName(task.name)

  const detail: ProductionTaskDetail = asset.task_details?.[detailKey] || { notes: '', completion: 0, comments: [] }
  const [subtaskInput, setSubtaskInput] = useState('')
  const [commentInput, setCommentInput] = useState('')
  // Project-relative root of this task/subtask (from PathBrowser) — the /ref
  // embed folder lives under it. Empty until tokens resolve.
  const [refBasePath, setRefBasePath] = useState('')
  const [confirmOpen, setConfirmOpen] = useState(false)

  // Group publishes by subtask (INSTANCE) — only meaningful in the Task view.
  const grouped: { key: string; items: ProductionPublish[] }[] = []
  const seen = new Map<string, number>()
  for (const p of publishes) {
    const key = (p.instance || '—').toUpperCase()
    if (!seen.has(key)) { seen.set(key, grouped.length); grouped.push({ key, items: [] }) }
    grouped[seen.get(key)!].items.push(p)
  }

  const addSubtask = () => {
    const v = subtaskInput.trim().toUpperCase()
    if (!v) return
    if (!task.known_subtasks.map(s => s.toUpperCase()).includes(v)) {
      onPatchTask({ known_subtasks: [...task.known_subtasks, v] })
    }
    setSubtaskInput('')
  }
  // Subtask deletion is now only reachable from the big delete button in the
  // subtask view — removes it from the parent task and closes the tab.
  const deleteCurrentSubtask = () => {
    if (!subtaskFilter) return
    onPatchTask({ known_subtasks: task.known_subtasks.filter(s => s.toUpperCase() !== subtaskFilter.toUpperCase()) })
    onDeleteTask()
  }

  const postComment = () => {
    const txt = commentInput.trim()
    if (!txt) return
    const now = new Date()
    const comment: ProductionComment = {
      id: nid('c'), text: txt,
      author: (settings?.username || 'unknown').toUpperCase(),
      date: now.toISOString().slice(0, 10),
      time: now.toTimeString().slice(0, 5),
    }
    onPatchDetail({ comments: [...(detail.comments || []), comment] })
    setCommentInput('')
    // Fan out an activity event so anyone with this task in their favorites
    // sees it in Activity under the "Fav" filter.
    if (project) {
      void api.notifyProductionComment(project, {
        class_token: asset.class, name: asset.name,
        task: task.name, subtask: subtaskFilter, text: txt,
      }).catch(() => { /* non-fatal — the comment is already persisted */ })
    }
  }
  const removeComment = (id: string) => {
    onPatchDetail({ comments: (detail.comments || []).filter(c => c.id !== id) })
  }

  const openInFolderManager = (p: ProductionPublish) => {
    if (!p.dest_folder) return
    navigate('/projects', { state: { openPath: expandFluxPath(p.dest_folder, workspace) } })
  }
  const openInExplorer = (p: ProductionPublish) => {
    if (!p.dest_folder) return
    void window.electronAPI?.openPath?.(expandFluxPath(p.dest_folder, workspace))
  }
  const copyPath = (p: ProductionPublish) => {
    if (!p.dest_folder) return
    void navigator.clipboard.writeText(expandFluxPath(p.dest_folder, workspace)).then(
      () => toast.success('Chemin copié'),
      () => toast.error('Copie impossible'),
    )
  }

  // Absolute path of this task/subtask's own folder (resolved via the selector).
  const taskFolderAbs = refBasePath && project
    ? expandFluxPath(`$FLUX/DOSSIER_PROJETS/${project}/${refBasePath}`, workspace)
    : ''
  const copyTaskFolder = () => {
    if (!taskFolderAbs) { toast.error('Chemin non résolu'); return }
    void navigator.clipboard.writeText(taskFolderAbs).then(
      () => toast.success('Chemin copié'),
      () => toast.error('Copie impossible'),
    )
  }
  const openTaskFolder = () => {
    if (!taskFolderAbs) { toast.error('Chemin non résolu'); return }
    navigate('/projects', { state: { openPath: taskFolderAbs } })
  }

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      {/* header */}
      <div style={{
        padding: '8px 14px', borderBottom: '1px solid var(--rule)',
        display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0,
      }}>
        <span style={{ width: 6, height: 6, borderRadius: '50%', background: color, flexShrink: 0 }} />
        <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink)' }}>{task.name}</span>
        {subtaskFilter && (
          <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink-3)' }}>
            · {subtaskFilter}
          </span>
        )}
        <span style={{ flex: 1 }} />
        {/* folder actions on this task/subtask's resolved folder */}
        <button onClick={copyTaskFolder} title="Copier le chemin du dossier" style={_headerBtn}>
          <Copy size={12} strokeWidth={1.75} />
        </button>
        <button onClick={openTaskFolder} title="Ouvrir dans le Folder Manager" style={_headerBtn}>
          <FolderTree size={12} strokeWidth={1.75} />
        </button>
        {/* pin — machine-wide, keeps this tab across restarts */}
        {onTogglePin && (
          <button
            onClick={() => onTogglePin()}
            title={pinned ? 'Désépingler' : 'Épingler cet onglet'}
            style={_headerBtn}
          >
            <Pin
              size={12} strokeWidth={1.75}
              color={pinned ? 'var(--accent-hi)' : 'var(--ink-3)'}
              fill={pinned ? 'var(--accent)' : 'none'}
            />
          </button>
        )}
        {/* favorite heart — user-wide, wired below */}
        <FavoriteToggle detailKey={detailKey} asset={asset} task={task} subtask={subtaskFilter} />
        {/* delete — far right; the only entry point, confirmed before it runs */}
        <button onClick={() => setConfirmOpen(true)} title={t('prod.delete')} style={_headerBtn}>
          <Trash2 size={12} strokeWidth={1.75} color="var(--err)" />
        </button>
      </div>

      {/* two-column body */}
      <div style={{ flex: 1, display: 'grid', gridTemplateColumns: '1fr 1fr', minHeight: 0 }}>
        {/* Left: notes / completion / subtasks / comments */}
        <div style={{ padding: '10px 14px', overflowY: 'auto', borderRight: '1px solid var(--rule)' }}>
          <Section label={t('prod.notes')}>
            <textarea
              value={detail.notes || ''}
              onChange={e => onPatchDetail({ notes: e.target.value })}
              rows={3}
              style={_textarea}
            />
          </Section>

          <Section label={t('prod.progress')}>
            <div style={{
              display: 'flex', alignItems: 'center', gap: 10,
            }}>
              <input
                type="range" min={0} max={100} step={5}
                value={detail.completion ?? 0}
                onChange={e => onPatchDetail({ completion: Number(e.target.value) })}
                style={{ flex: 1, accentColor: color }}
              />
              <span style={{
                fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink-2)',
                minWidth: 34, textAlign: 'right',
              }}>{detail.completion ?? 0}%</span>
            </div>
          </Section>

          {!subtaskFilter && (
            <Section label={t('prod.subtasks')}>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 6 }}>
                {task.known_subtasks.map(s => (
                  <span key={s} style={_tag} title={s}>
                    {s}
                  </span>
                ))}
                {task.known_subtasks.length === 0 && (
                  <span style={{ fontSize: 10, color: 'var(--ink-4)' }}>—</span>
                )}
              </div>
              <input
                value={subtaskInput}
                onChange={e => setSubtaskInput(e.target.value.toUpperCase())}
                onKeyDown={e => { if (e.key === 'Enter') addSubtask() }}
                placeholder={t('prod.addSubtask')}
                style={{ ..._input, width: '100%' }}
              />
            </Section>
          )}

          <Section label="COMMENTS">
            <textarea
              value={commentInput}
              onChange={e => setCommentInput(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); postComment() }
              }}
              rows={3}
              placeholder=""
              style={_textarea}
            />
            <div style={{
              display: 'flex', alignItems: 'center', gap: 8, marginTop: 4,
            }}>
              <span style={{ fontSize: 9, color: 'var(--ink-4)' }}>Ctrl+Enter</span>
              <span style={{ flex: 1 }} />
              <button
                onClick={postComment}
                disabled={!commentInput.trim()}
                style={_postBtn}
              >Envoyer</button>
            </div>
            <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 6 }}>
              {(detail.comments || []).slice().reverse().map(c => {
                const read = readState.isRead(c.id)
                return (
                  <div key={c.id} style={{
                    border: '1px solid var(--rule-2)', borderRadius: 6, padding: '6px 8px 6px 10px',
                    background: 'var(--paper)',
                    borderLeft: read ? '1px solid var(--rule-2)' : '3px solid var(--accent)',
                  }}>
                    <div style={{
                      display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2,
                    }}>
                      <span style={{
                        fontFamily: 'var(--mono)', fontSize: 10, fontWeight: 700,
                        color: 'var(--accent-hi)', letterSpacing: '0.04em',
                      }}>{c.author}</span>
                      <span style={{ fontSize: 8, color: 'var(--ink-4)', fontFamily: 'var(--mono)' }}>{c.date} {c.time}</span>
                      <span style={{ flex: 1 }} />
                      <button
                        onClick={() => void readState.setRead(c.id, !read)}
                        title={read ? 'Marquer non lu' : 'Marquer lu'}
                        style={{
                          ..._miniIconBtn,
                          borderColor: read ? 'var(--ok)' : 'var(--rule-2)',
                          color: read ? 'var(--ok)' : 'var(--ink-3)',
                          background: read ? 'color-mix(in oklch, var(--ok) 12%, transparent)' : 'var(--paper-2)',
                        }}
                      >
                        <Check size={9} strokeWidth={2.2} />
                      </button>
                      <button
                        onClick={() => { void readState.setRead(c.id, false); removeComment(c.id) }}
                        title="Supprimer"
                        style={{
                          ..._miniIconBtn,
                          borderColor: 'color-mix(in oklch, var(--err) 40%, var(--rule-2))',
                          color: 'var(--err)',
                          background: 'var(--paper-2)',
                        }}
                      >×</button>
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--ink)', whiteSpace: 'pre-wrap' }}>{c.text}</div>
                  </div>
                )
              })}
            </div>
          </Section>
        </div>

        {/* Right: Path browser + Recent Publishes grouped by subtask (Task view) or filtered (Subtask view) */}
        <div style={{ padding: '10px 14px', overflowY: 'auto' }}>
          <PathBrowser
            project={project || ''}
            asset={asset}
            task={task}
            entityKind={entityKind}
            subtaskFilter={subtaskFilter}
            onPatchTask={onPatchTask}
            onResolvedPath={setRefBasePath}
          />

          <div style={{ ..._lbl, marginBottom: 6 }}>
            {t('prod.recentPublishes')}
            {subtaskFilter && (
              <span style={{ marginLeft: 8, color: color, textTransform: 'none', letterSpacing: 0 }}>
                · {subtaskFilter}
              </span>
            )}
          </div>
          {grouped.length === 0 && (
            <div style={{ fontSize: 10, color: 'var(--ink-4)' }}>{t('prod.noPublishes')}</div>
          )}
          {grouped.map(g => (
            <div key={g.key} style={{ marginBottom: 10 }}>
              {!subtaskFilter && (
                <div style={{
                  display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4,
                  fontFamily: 'var(--mono)', fontSize: 9, color: 'var(--ink-3)', letterSpacing: '0.05em',
                }}>
                  <span style={{ width: 4, height: 4, borderRadius: 2, background: color }} />
                  <span style={{ textTransform: 'uppercase' }}>{g.key}</span>
                  <span style={{ color: 'var(--ink-4)' }}>· {g.items.length}</span>
                </div>
              )}
              {g.items.map(p => (
                <div key={p.id} style={{
                  padding: '5px 8px', borderRadius: 5,
                  border: '1px solid var(--rule-2)', background: 'var(--paper)',
                  marginBottom: 3, display: 'flex', alignItems: 'center', gap: 6,
                  cursor: 'pointer',
                }}
                     onClick={() => openInFolderManager(p)}
                     title={p.dest_folder}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 10, color: 'var(--ink)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontFamily: 'var(--mono)' }}>
                      {p.file}
                    </div>
                    <div style={{ fontSize: 8, color: 'var(--ink-4)', marginTop: 1 }}>
                      {p.user} · {p.date} {p.time}
                    </div>
                  </div>
                  <button style={_miniIconBtn} title="Copier"
                          onClick={e => { e.stopPropagation(); copyPath(p) }}>
                    <Copy size={9} strokeWidth={1.75} />
                  </button>
                  <button style={_miniIconBtn} title="Folder Manager"
                          onClick={e => { e.stopPropagation(); openInFolderManager(p) }}>
                    <FolderTree size={9} strokeWidth={1.75} />
                  </button>
                  <button style={_miniIconBtn} title="Explorateur"
                          onClick={e => { e.stopPropagation(); openInExplorer(p) }}>
                    <FolderOpen size={9} strokeWidth={1.75} />
                  </button>
                </div>
              ))}
            </div>
          ))}

          <MediaEmbed project={project || ''} relPath={refBasePath} color={color} />
        </div>
      </div>

      {confirmOpen && (
        <ConfirmDelete
          label={subtaskFilter ? `le subtask « ${subtaskFilter} »` : `la tâche « ${task.name} »`}
          onCancel={() => setConfirmOpen(false)}
          onConfirm={() => { setConfirmOpen(false); subtaskFilter ? deleteCurrentSubtask() : onDeleteTask() }}
        />
      )}
    </div>
  )
}

// ── favorite toggle (user-wide, stored in User.json under production.favorites) ─
function FavoriteToggle({ detailKey, asset, task, subtask }: {
  detailKey: string
  asset:     Asset
  task:      ProductionTask
  subtask:   string | null
}) {
  // We display it live but reading/writing is delegated to a sibling hook via
  // an imported helper (see useFavorites in ../../hooks/useFavorites).
  const { isFavorite, toggle } = useFavoriteBinding(asset, task, subtask)
  const active = isFavorite
  return (
    <button
      onClick={() => void toggle()}
      title={active ? 'Retirer des favoris' : 'Ajouter aux favoris'}
      style={_headerBtn}
    >
      <Heart
        size={12} strokeWidth={1.75}
        color={active ? 'var(--accent-hi)' : 'var(--ink-3)'}
        fill={active ? 'var(--accent)' : 'none'}
      />
      {/* mute the unused-param */}
      <span style={{ display: 'none' }}>{detailKey}</span>
    </button>
  )
}

// tiny local hook wrapping the shared favorite store — declared inline so this
// file remains self-contained; the real store lives in ../../hooks/useFavorites
import { useFavoriteBinding } from '../../hooks/useFavorites'

// ── path browser ─────────────────────────────────────────────────────────────
// Compact token selector. Four slots: CLASS / NAME / TASK / INSTANCE. CLASS +
// NAME are pinned to the current asset; TASK and INSTANCE are selectable
// dropdowns fed by the project's tokens.json (+ subtasks the artist has
// actually seen on this task). Each slot change composes a new project-relative
// path and writes it to task.path_override; the resolved path is bubbled up via
// onResolvedPath so the /ref embed folder can be located.
function PathBrowser({ project, asset, task, entityKind, subtaskFilter, onPatchTask, onResolvedPath }: {
  project:        string
  asset:          Asset
  task:           ProductionTask
  entityKind:     'asset' | 'shot' | 'seq'
  subtaskFilter:  string | null
  onPatchTask:    (patch: Partial<ProductionTask>) => void
  onResolvedPath: (path: string) => void
}) {
  const [tokens, setTokens] = useState<{
    CLASS?:    Record<string, string>
    TYPE?:     Record<string, string>
    INSTANCE?: Record<string, string>
    NAME?:     Record<string, string>
  }>({})
  useEffect(() => {
    let ok = true
    if (!project) { setTokens({}); return }
    api.getTokens(project).then(r => { if (ok) setTokens(r.tokens || {}) }).catch(() => { if (ok) setTokens({}) })
    return () => { ok = false }
  }, [project])

  // Effective selection: what the slots currently point at. TASK defaults to
  // the task's first type_token; INSTANCE defaults to the subtask filter (in
  // a subtask view) else empty.
  const [selTask, setSelTask]         = useState<string>(() => (task.type_tokens[0] || task.name).toUpperCase())
  const [selInstance, setSelInstance] = useState<string>(() => (subtaskFilter || '').toUpperCase())
  useEffect(() => { setSelTask((task.type_tokens[0] || task.name).toUpperCase()) }, [task.id, task.type_tokens, task.name])
  useEffect(() => { setSelInstance((subtaskFilter || '').toUpperCase()) }, [subtaskFilter, task.id])

  // Helpers that turn a token pick into an absolute-in-project path segment.
  const clsPath = useMemo(
    () => (tokens.CLASS?.[asset.class.toUpperCase()] || '').replace(/\\/g, '/').replace(/^\/|\/$/g, ''),
    [tokens.CLASS, asset.class],
  )
  const namePath = useMemo(() => {
    const nameTok = tokens.NAME?.[asset.name.toUpperCase()]
    return (nameTok ? nameTok.replace(/\\/g, '/') : (clsPath ? `${clsPath}/${asset.name.toUpperCase()}` : asset.name.toUpperCase()))
      .replace(/^\/|\/$/g, '')
  }, [tokens.NAME, asset.name, clsPath])

  const composeFromSlots = (tk: string, inst: string): string => {
    const typeSub  = tk ? (tokens.TYPE?.[tk] || tk.toLowerCase()).replace(/\\/g, '/').replace(/^\/|\/$/g, '') : ''
    const instSub  = inst ? ((tokens.INSTANCE?.[inst.toLowerCase()] ?? tokens.INSTANCE?.[inst.toUpperCase()] ?? inst.toLowerCase())).replace(/\\/g, '/').replace(/^\/|\/$/g, '') : ''
    const parts = [namePath, typeSub, instSub].filter(Boolean)
    return parts.join('/')
  }

  // TASK options depend on the entity kind:
  //  - shots/seqs → the templated CLASS tokens (ANIM, LAYOUT, LIGHTING, FX…),
  //    i.e. CLASS entries whose path carries {seq}/{shot};
  //  - assets     → the TYPE tokens.
  const taskOptions = useMemo(() => {
    if (entityKind === 'shot' || entityKind === 'seq') {
      return [...new Set(
        Object.entries(tokens.CLASS || {})
          .filter(([, p]) => typeof p === 'string' && (p.includes('{seq}') || p.includes('{shot}')))
          .map(([k]) => k.toUpperCase()),
      )].sort()
    }
    return [...new Set(Object.keys(tokens.TYPE || {}).map(k => k.toUpperCase()))].sort()
  }, [tokens.TYPE, tokens.CLASS, entityKind])
  const instanceOptions = useMemo(() => {
    const s = new Set<string>()
    for (const k of Object.keys(tokens.INSTANCE || {})) {
      if (k.toLowerCase() === 'null') continue
      s.add(k.toUpperCase())
    }
    for (const k of task.known_subtasks) s.add(k.toUpperCase())
    return [...s].sort()
  }, [tokens.INSTANCE, task.known_subtasks])

  // Writing a slot change: recompute + push to override.
  const pickTask = (v: string) => {
    setSelTask(v)
    onPatchTask({ path_override: composeFromSlots(v, selInstance) })
  }
  const pickInstance = (v: string) => {
    setSelInstance(v)
    onPatchTask({ path_override: composeFromSlots(selTask, v) })
  }

  // Resolve the /ref root on the backend (authoritative — shots use templated
  // CLASS tokens the client-side composer above can't reproduce). Driven by the
  // current TASK/INSTANCE selection so the embed follows the selector.
  useEffect(() => {
    if (!project) { onResolvedPath(''); return }
    let ok = true
    const params = entityKind === 'asset'
      ? { kind: 'asset' as const, class_token: asset.class, name: asset.name, task: selTask, subtask: selInstance }
      : entityKind === 'shot'
        ? { kind: 'shot' as const, seq: asset.class, shot: asset.name, task: selTask, subtask: selInstance }
        : { kind: 'seq' as const,  seq: asset.name, task: selTask, subtask: selInstance }
    api.resolveRefPath(project, params)
      .then(r => { if (ok) onResolvedPath(r.rel_path || '') })
      .catch(() => { if (ok) onResolvedPath('') })
    return () => { ok = false }
  }, [project, entityKind, asset.class, asset.name, selTask, selInstance])   // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div style={{
      border: '1px solid var(--rule-2)',
      borderRadius: 6, padding: '8px 10px', marginBottom: 10,
      background: 'var(--paper)',
    }}>
      {/* four-slot token selector */}
      <div style={{
        display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr',
        gap: 6,
      }}>
        <Slot label="CLASS" locked>
          <span style={_slotLocked}>{asset.class}</span>
        </Slot>

        <Slot label="NAME" locked>
          <span style={_slotLocked}>{asset.name}</span>
        </Slot>

        <Slot label="TASK">
          <select value={selTask} onChange={e => pickTask(e.target.value)} style={_slotSelect}>
            {!taskOptions.includes(selTask) && selTask && <option value={selTask}>{selTask}</option>}
            {taskOptions.map(o => <option key={o} value={o}>{o}</option>)}
          </select>
        </Slot>

        <Slot label="INSTANCE">
          <select value={selInstance} onChange={e => pickInstance(e.target.value)} style={_slotSelect}>
            <option value="">—</option>
            {!instanceOptions.includes(selInstance) && selInstance && <option value={selInstance}>{selInstance}</option>}
            {instanceOptions.map(o => <option key={o} value={o}>{o}</option>)}
          </select>
        </Slot>
      </div>
    </div>
  )
}

function Slot({ label, locked, children }: { label: string; locked?: boolean; children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 3, minWidth: 0 }}>
      <span style={{
        fontFamily: 'var(--mono)', fontSize: 8, letterSpacing: '0.08em',
        color: locked ? 'var(--ink-4)' : 'var(--ink-3)', textTransform: 'uppercase',
      }}>{label}</span>
      {children}
    </div>
  )
}

const _slotSelect: React.CSSProperties = {
  background: 'var(--paper)', color: 'var(--ink)',
  border: '1px solid var(--rule-2)', borderRadius: 5,
  padding: '4px 6px', fontSize: 10, fontFamily: 'var(--mono)',
  letterSpacing: '0.03em', outline: 'none',
  minWidth: 0, width: '100%',
}
const _slotLocked: React.CSSProperties = {
  padding: '4px 8px', borderRadius: 5,
  background: 'var(--paper-2)', border: '1px solid var(--rule-2)',
  color: 'var(--ink-3)', fontFamily: 'var(--mono)', fontSize: 10,
  letterSpacing: '0.04em',
  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
}

// ── media embed (reference images / videos / playblasts, /ref folder) ────────
// A single-slot viewer below the recent publishes: drop an image or video to
// deposit a new version on disk; the newest (LAST) is always what shows. Videos
// play on hover (muted, looping, no controls). Click opens a full-screen
// overlay; clicking the greyed backdrop minimises it back.
const _IMAGE_EXT = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'apng', 'avif', 'svg']
const _VIDEO_EXT = ['mp4', 'webm', 'ogv', 'ogg', 'm4v', 'mov', 'mkv']

function isAcceptedMedia(file: File): boolean {
  if (file.type.startsWith('audio/')) return false
  if (file.type.startsWith('image/') || file.type.startsWith('video/')) return true
  const ext = file.name.split('.').pop()?.toLowerCase() ?? ''
  return _IMAGE_EXT.includes(ext) || _VIDEO_EXT.includes(ext)
}

function MediaEmbed({ project, relPath, color }: {
  project: string
  relPath: string
  color:   string
}) {
  const [latest, setLatest] = useState<{ file: string; kind: string } | null>(null)
  const [rev, setRev]       = useState(0)          // cache-buster: LAST.* is overwritten in place
  const [dragOver, setDragOver] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [full, setFull]     = useState(false)

  const canUse = !!project && !!relPath

  const refresh = useCallback((): (() => void) | undefined => {
    if (!canUse) { setLatest(null); return undefined }
    let ok = true
    api.getRefLatest(project, relPath)
      .then(r => { if (ok) setLatest(r.found && r.file && r.kind ? { file: r.file, kind: r.kind } : null) })
      .catch(() => { if (ok) setLatest(null) })
    return () => { ok = false }
  }, [project, relPath, canUse])

  useEffect(() => refresh(), [refresh])

  const doUpload = useCallback(async (files: FileList | File[]) => {
    if (!canUse) { toast.error('Chemin non résolu — impossible de déposer'); return }
    const list = Array.from(files).filter(isAcceptedMedia)
    if (list.length === 0) { toast.error('Formats acceptés : images et vidéos (pas d’audio)'); return }
    setUploading(true)
    try {
      // Deposit sequentially so the version numbering stays deterministic.
      for (const f of list) await api.depositRef(project, relPath, f)
      setRev(v => v + 1)
      refresh()
      toast.success(list.length > 1 ? `${list.length} fichiers déposés` : 'Fichier déposé')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setUploading(false)
    }
  }, [project, relPath, canUse, refresh])

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation()
    setDragOver(false)
    if (e.dataTransfer.files?.length) void doUpload(e.dataTransfer.files)
  }

  const download = async () => {
    if (!latest) return
    const ext = latest.file.split('.').pop() ?? ''
    const suggested = `${relPath.split('/').pop() || 'ref'}_${latest.file}`
    const dest = await window.electronAPI?.saveFile?.(suggested, [
      { name: latest.kind === 'video' ? 'Vidéo' : 'Image', extensions: [ext] },
      { name: 'Tous les fichiers', extensions: ['*'] },
    ])
    if (!dest) return
    try {
      await api.exportRef(project, relPath, latest.file, dest)
      toast.success('Téléchargé')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }

  const src = latest ? `${api.refFileUrl(project, relPath, latest.file)}&rev=${rev}` : ''

  return (
    <>
      <div style={{ ..._lbl, marginTop: 14, marginBottom: 6, display: 'flex', alignItems: 'center', gap: 6 }}>
        <span>Références</span>
        {uploading && <span style={{ fontSize: 8, color: 'var(--ink-4)', textTransform: 'none' }}>envoi…</span>}
      </div>

      <div
        onDragOver={e => { if (canUse) { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; if (!dragOver) setDragOver(true) } }}
        onDragLeave={e => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragOver(false) }}
        onDrop={onDrop}
        style={{
          position: 'relative',
          borderRadius: 8,
          border: `1px ${latest ? 'solid' : 'dashed'} ${dragOver ? color : 'var(--rule-2)'}`,
          background: dragOver ? `color-mix(in oklch, ${color} 12%, var(--paper))` : 'var(--paper)',
          overflow: 'hidden',
          minHeight: latest ? undefined : 90,
          aspectRatio: latest ? '16 / 9' : undefined,
          maxHeight: 320,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          cursor: latest ? 'pointer' : 'default',
        }}
        onClick={() => { if (latest) setFull(true) }}
        title={latest ? 'Cliquer pour agrandir' : 'Glissez une image ou une vidéo ici'}
      >
        {latest ? (
          <>
            <HoverMedia src={src} kind={latest.kind} />
            <button
              onClick={e => { e.stopPropagation(); void download() }}
              title="Télécharger"
              style={{
                position: 'absolute', top: 6, right: 6, zIndex: 2,
                width: 26, height: 26, borderRadius: 6, border: '1px solid var(--rule-2)',
                background: 'color-mix(in oklch, var(--paper) 80%, transparent)',
                color: 'var(--ink-2)', cursor: 'pointer',
                display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                backdropFilter: 'blur(2px)',
              }}
            >
              <Download size={13} strokeWidth={1.75} />
            </button>
            {dragOver && (
              <div style={_dropHint}>Déposer pour remplacer (nouvelle version)</div>
            )}
          </>
        ) : (
          <div style={{
            display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6,
            color: 'var(--ink-4)', fontSize: 10, padding: 12, textAlign: 'center',
          }}>
            <div style={{ display: 'flex', gap: 6 }}>
              <ImageIcon size={16} strokeWidth={1.5} />
              <Film size={16} strokeWidth={1.5} />
            </div>
            {canUse
              ? <span><UploadCloud size={11} style={{ verticalAlign: '-2px' }} strokeWidth={1.75} /> Glissez une image ou une vidéo</span>
              : <span>Chemin non résolu</span>}
          </div>
        )}
      </div>

      {full && latest && (
        <FullscreenMedia src={src} kind={latest.kind} onClose={() => setFull(false)} />
      )}
    </>
  )
}

// Video plays on hover only (muted / looping / no controls); images just show.
function HoverMedia({ src, kind }: { src: string; kind: string }) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  if (kind === 'video') {
    return (
      <video
        ref={videoRef}
        src={src}
        muted loop playsInline preload="metadata"
        onMouseEnter={() => { void videoRef.current?.play().catch(() => {}) }}
        onMouseLeave={() => { const v = videoRef.current; if (v) { v.pause(); v.currentTime = 0 } }}
        style={{ width: '100%', height: '100%', objectFit: 'contain', background: '#000', display: 'block' }}
      />
    )
  }
  return (
    <img src={src} alt="référence"
         style={{ width: '100%', height: '100%', objectFit: 'contain', display: 'block' }} />
  )
}

// Full-screen overlay: greyed backdrop; the media fills the interface. Clicking
// outside the media minimises. Video autoplays muted + loops (no controls).
function FullscreenMedia({ src, kind, onClose }: { src: string; kind: string; onClose: () => void }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [onClose])
  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, zIndex: 3000,
        background: 'rgba(0,0,0,0.72)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: 40,
      }}
    >
      {kind === 'video' ? (
        <video
          src={src} autoPlay muted loop playsInline
          onClick={e => e.stopPropagation()}
          style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain', boxShadow: 'var(--shadow)' }}
        />
      ) : (
        <img
          src={src} alt="référence"
          onClick={e => e.stopPropagation()}
          style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain', boxShadow: 'var(--shadow)' }}
        />
      )}
      <button onClick={onClose} title="Fermer (Échap)" style={{
        position: 'fixed', top: 18, right: 18, width: 34, height: 34, borderRadius: 8,
        border: '1px solid var(--rule-2)', background: 'var(--paper)', color: 'var(--ink-2)',
        cursor: 'pointer', display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      }}>
        <X size={16} strokeWidth={1.75} />
      </button>
    </div>
  )
}

const _dropHint: React.CSSProperties = {
  position: 'absolute', inset: 0, zIndex: 3, pointerEvents: 'none',
  display: 'flex', alignItems: 'center', justifyContent: 'center',
  background: 'color-mix(in oklch, var(--paper) 55%, transparent)',
  color: 'var(--ink)', fontSize: 11, fontWeight: 600, textAlign: 'center', padding: 12,
}

// ── confirm-before-delete dialog ─────────────────────────────────────────────
function ConfirmDelete({ label, onCancel, onConfirm }: {
  label:     string
  onCancel:  () => void
  onConfirm: () => void
}) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancel()
      if (e.key === 'Enter') onConfirm()
    }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [onCancel, onConfirm])

  return (
    <div
      onClick={e => { if (e.target === e.currentTarget) onCancel() }}
      style={{
        position: 'fixed', inset: 0, zIndex: 3000, background: 'rgba(0,0,0,0.55)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24,
      }}
    >
      <div style={{
        width: 340, maxWidth: '92vw',
        background: 'var(--paper)', border: '1px solid var(--rule-2)', borderRadius: 12,
        boxShadow: 'var(--shadow)', padding: '18px 18px 14px',
      }}>
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8,
          fontSize: 13, fontWeight: 600, color: 'var(--ink)',
        }}>
          <Trash2 size={15} strokeWidth={1.9} color="var(--err)" />
          Supprimer {label} ?
        </div>
        <div style={{ fontSize: 11, color: 'var(--ink-3)', marginBottom: 16 }}>
          Cette action est définitive.
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button onClick={onCancel} style={_confirmCancelBtn}>Annuler</button>
          <button onClick={onConfirm} autoFocus style={_confirmDeleteBtn}>Supprimer</button>
        </div>
      </div>
    </div>
  )
}

const _confirmCancelBtn: React.CSSProperties = {
  padding: '6px 14px', borderRadius: 6, fontSize: 11, fontWeight: 500,
  border: '1px solid var(--rule-2)', background: 'var(--paper-2)',
  color: 'var(--ink-2)', cursor: 'pointer',
}
const _confirmDeleteBtn: React.CSSProperties = {
  padding: '6px 14px', borderRadius: 6, fontSize: 11, fontWeight: 600,
  border: '1px solid var(--err)', background: 'var(--err)',
  color: 'var(--paper)', cursor: 'pointer',
}

// ── local atoms ──────────────────────────────────────────────────────────────
function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={_lbl}>{label}</div>
      {children}
    </div>
  )
}

const _lbl: React.CSSProperties = {
  fontFamily: 'var(--mono)', fontSize: 9, letterSpacing: '0.08em',
  color: 'var(--ink-3)', textTransform: 'uppercase', marginBottom: 4,
}
const _textarea: React.CSSProperties = {
  width: '100%', background: 'var(--paper)', color: 'var(--ink)',
  border: '1px solid var(--rule-2)', borderRadius: 5,
  padding: '6px 8px', fontSize: 11, fontFamily: 'var(--sans)',
  outline: 'none', resize: 'vertical', minHeight: 60,
}
const _input: React.CSSProperties = {
  background: 'var(--paper)', color: 'var(--ink)',
  border: '1px solid var(--rule-2)', borderRadius: 5,
  padding: '4px 8px', fontSize: 10, fontFamily: 'var(--mono)',
  outline: 'none',
}
const _tag: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 4,
  padding: '2px 7px', borderRadius: 999,
  border: '1px solid var(--rule-2)', background: 'var(--paper-2)',
  color: 'var(--ink-2)', fontSize: 9, fontFamily: 'var(--mono)',
  letterSpacing: '0.05em',
}
const _headerBtn: React.CSSProperties = {
  width: 24, height: 22, borderRadius: 4, border: '1px solid var(--rule-2)',
  background: 'var(--paper)', color: 'var(--ink-2)', cursor: 'pointer',
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
}
const _miniIconBtn: React.CSSProperties = {
  width: 20, height: 20, borderRadius: 3, border: '1px solid var(--rule-2)',
  background: 'var(--paper-2)', color: 'var(--ink-3)', cursor: 'pointer',
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
}
const _postBtn: React.CSSProperties = {
  padding: '4px 12px', borderRadius: 6, fontSize: 10, fontWeight: 600,
  border: '1px solid var(--accent)', background: 'var(--accent)',
  color: 'var(--paper)', cursor: 'pointer',
}
