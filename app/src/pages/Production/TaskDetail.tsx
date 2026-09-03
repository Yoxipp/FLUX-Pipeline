// TaskDetail — Notes + completion + subtasks + Comments + Recent Publishes.
//
// Also used for the Subtask view; when `subtaskFilter` is set, the Subtasks
// section is hidden and detail state (notes/completion/comments) writes into
// `task_details[<taskName>|<subtask>]` — passed as `detailKey`.

import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { Check, Copy, FolderOpen, FolderTree, Heart, Pin, Trash2 } from 'lucide-react'
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
  asset, task, publishes, subtaskFilter, detailKey,
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
  const removeSubtask = (v: string) => {
    onPatchTask({ known_subtasks: task.known_subtasks.filter(s => s.toUpperCase() !== v.toUpperCase()) })
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
        {!subtaskFilter && (
          <button onClick={onDeleteTask} title={t('prod.delete')} style={_headerBtn}>
            <Trash2 size={11} strokeWidth={1.75} color="var(--err)" />
          </button>
        )}
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
                  <span key={s} style={_tag} onClick={() => removeSubtask(s)} title={t('prod.delete')}>
                    {s} <span style={{ opacity: 0.6 }}>×</span>
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
            subtaskFilter={subtaskFilter}
            color={color}
            onPatchTask={onPatchTask}
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
        </div>
      </div>
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
// Publisher-style compact token composer. Four slots: CLASS / NAME / TASK /
// INSTANCE. CLASS + NAME are pinned to the current asset; TASK and INSTANCE
// are selectable dropdowns fed by the project's tokens.json (+ subtasks the
// artist has actually seen on this task). The path input above the slots is
// always editable; each slot change composes a new path into it and writes it
// to task.path_override.
function PathBrowser({ project, asset, task, subtaskFilter, color, onPatchTask }: {
  project:       string
  asset:         Asset
  task:          ProductionTask
  subtaskFilter: string | null
  color:         string
  onPatchTask:   (patch: Partial<ProductionTask>) => void
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

  // Menu populations from the project's tokens (+ this task's known subtasks).
  const taskOptions = useMemo(
    () => [...new Set(Object.keys(tokens.TYPE || {}).map(k => k.toUpperCase()))].sort(),
    [tokens.TYPE],
  )
  const instanceOptions = useMemo(() => {
    const s = new Set<string>()
    for (const k of Object.keys(tokens.INSTANCE || {})) {
      if (k.toLowerCase() === 'null') continue
      s.add(k.toUpperCase())
    }
    for (const k of task.known_subtasks) s.add(k.toUpperCase())
    return [...s].sort()
  }, [tokens.INSTANCE, task.known_subtasks])

  const override   = task.path_override ?? ''
  const composed   = composeFromSlots(selTask, selInstance)
  const overridden = !!override

  // Writing a slot change: recompute + push to override.
  const pickTask = (v: string) => {
    setSelTask(v)
    onPatchTask({ path_override: composeFromSlots(v, selInstance) })
  }
  const pickInstance = (v: string) => {
    setSelInstance(v)
    onPatchTask({ path_override: composeFromSlots(selTask, v) })
  }
  const typeFreeText = (v: string) => onPatchTask({ path_override: v })
  const clearOverride = () => onPatchTask({ path_override: '' })

  const shown = override || composed

  return (
    <div style={{
      border: `1px solid ${overridden ? color : 'var(--rule-2)'}`,
      borderRadius: 6, padding: '8px 10px', marginBottom: 10,
      background: overridden ? `color-mix(in oklch, ${color} 8%, var(--paper))` : 'var(--paper)',
    }}>
      <div style={{ ..._lbl, marginBottom: 4, display: 'flex', alignItems: 'center', gap: 6 }}>
        <span>Chemin</span>
        {overridden ? (
          <span style={{
            padding: '1px 5px', borderRadius: 3, fontSize: 8,
            background: color, color: 'var(--paper)', textTransform: 'uppercase', letterSpacing: '0.06em',
          }}>override</span>
        ) : (
          <span style={{
            padding: '1px 5px', borderRadius: 3, fontSize: 8,
            background: 'var(--paper-2)', color: 'var(--ink-4)', border: '1px solid var(--rule-2)',
            textTransform: 'uppercase', letterSpacing: '0.06em',
          }}>défaut</span>
        )}
        <span style={{ flex: 1 }} />
        {overridden && (
          <button onClick={clearOverride} title="Rétablir le chemin par défaut" style={_pathClearBtn}>reset</button>
        )}
      </div>

      <input
        value={shown}
        onChange={e => typeFreeText(e.target.value)}
        placeholder={composed || 'chemin relatif au projet…'}
        spellCheck={false}
        style={{
          width: '100%',
          background: 'var(--paper)', color: overridden ? 'var(--ink)' : 'var(--ink-2)',
          border: '1px solid var(--rule-2)', borderRadius: 5,
          padding: '5px 8px', fontSize: 10, fontFamily: 'var(--mono)',
          letterSpacing: '0.03em', outline: 'none',
        }}
      />

      {/* four-slot token composer */}
      <div style={{
        display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr',
        gap: 6, marginTop: 8,
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
const _pathClearBtn: React.CSSProperties = {
  padding: '1px 6px', borderRadius: 3, fontSize: 8,
  background: 'transparent', color: 'var(--ink-3)',
  border: '1px solid var(--rule-2)', cursor: 'pointer',
  textTransform: 'uppercase', letterSpacing: '0.06em',
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
  letterSpacing: '0.05em', cursor: 'pointer',
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
