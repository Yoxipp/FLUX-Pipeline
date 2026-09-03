// TaskDetail — Notes + completion + subtasks + Comments + Recent Publishes.
//
// Also used for the Subtask view; when `subtaskFilter` is set, the Subtasks
// section is hidden and detail state (notes/completion/comments) writes into
// `task_details[<taskName>|<subtask>]` — passed as `detailKey`.

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { Copy, FolderOpen, FolderTree, Heart, Trash2 } from 'lucide-react'
import { api } from '../../api/client'
import { useI18n } from '../../i18n'
import { useProject } from '../../ProjectContext'
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
  onPatchTask:   (patch: Partial<ProductionTask>) => void
  onPatchDetail: (patch: Partial<ProductionTaskDetail>) => void
  onDeleteTask:  () => void
}

const nid = (prefix: string) => `${prefix}_${Math.random().toString(36).slice(2, 12)}`

export function TaskDetail({
  asset, task, publishes, subtaskFilter, detailKey,
  onPatchTask, onPatchDetail, onDeleteTask,
}: Props) {
  const { t }        = useI18n()
  const navigate     = useNavigate()
  const { settings } = useSettings()
  const { project }  = useProject()
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
              {(detail.comments || []).slice().reverse().map(c => (
                <div key={c.id} style={{
                  border: '1px solid var(--rule-2)', borderRadius: 6, padding: '6px 8px',
                  background: 'var(--paper)',
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
                    <button onClick={() => removeComment(c.id)}
                            style={{ ..._miniBtn, color: 'var(--err)' }}
                            title="Supprimer">×</button>
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--ink)', whiteSpace: 'pre-wrap' }}>{c.text}</div>
                </div>
              ))}
            </div>
          </Section>
        </div>

        {/* Right: Recent Publishes grouped by subtask (Task view) or filtered (Subtask view) */}
        <div style={{ padding: '10px 14px', overflowY: 'auto' }}>
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
const _miniBtn: React.CSSProperties = {
  padding: '1px 6px', borderRadius: 3, border: '1px solid var(--rule-2)',
  background: 'var(--paper)', color: 'var(--ink-2)', fontSize: 10, cursor: 'pointer',
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
