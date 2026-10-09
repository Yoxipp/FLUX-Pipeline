// TaskDetail — Notes + completion + subtasks + Comments + Recent Publishes.
//
// Also used for the Subtask view; when `subtaskFilter` is set, the Subtasks
// section is hidden and detail state (notes/completion/comments) writes into
// `task_details[<taskName>|<subtask>]` — passed as `detailKey`.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import {
  Check, Clapperboard, Copy, Download, Film, FolderOpen, FolderTree, Heart, History,
  Image as ImageIcon, List, Pin, RotateCcw, UploadCloud, X,
} from 'lucide-react'
import { api, type RefVersion } from '../../api/client'
import { readSession, writeSession } from '../../hooks/useSessionState'
import { openInKeyframe } from '../../lib/keyframe'
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
import { OpenInMenu, projectRelPath } from '../../components/shared/OpenInMenu'

interface Props {
  asset:         Asset
  task:          ProductionTask
  entityKind:    'asset' | 'shot' | 'seq'       // asset shim carries seq/shot names for shots
  publishes:     ProductionPublish[]
  subtaskFilter: string | null
  detailKey:     string                         // task_details key : "<task>" or "<task>|<subtask>"
  headerActions?: React.ReactNode
  pinned?:       boolean
  onTogglePin?:  () => void
  onPatchTask:   (patch: Partial<ProductionTask>) => void
  onPatchDetail: (patch: Partial<ProductionTaskDetail>) => void
  renderHeader?: (actions: React.ReactNode) => React.ReactNode
}

const nid = (prefix: string) => `${prefix}_${Math.random().toString(36).slice(2, 12)}`

// Pipeline CLASS token → Publisher composer category ("FX" is the label for FXRIG).
const CLASS_TO_PUBLISHER_CATEGORY: Record<string, string> = {
  CHAR: 'CHAR', PROPS: 'PROPS', ENV: 'ENV', FXRIG: 'FX',
}

export function TaskDetail({
  asset, task, entityKind, publishes, subtaskFilter, detailKey,
  pinned, onTogglePin, headerActions,
  onPatchTask, onPatchDetail, renderHeader,
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
  // "Retake" toggle: the next comment is stored with kind 'retake' (home "Tes retakes").
  const [asRetake, setAsRetake] = useState(false)
  // Project-relative root of this task/subtask (from PathBrowser) — the /ref
  // embed folder lives under it. Empty until tokens resolve; refError says why.
  const [refBasePath, setRefBasePath] = useState('')
  const [refError, setRefError] = useState('')
  const [publishListOpen, setPublishListOpen] = useState(false)
  // Current TASK/INSTANCE selection mirrored up from PathBrowser — feeds "Publish here".
  const [sel, setSel] = useState<{ task: string; instance: string }>({ task: '', instance: '' })

  // Newest first, by date+time (ISO date + HH:MM sort lexicographically).
  const sortedPublishes = [...publishes].sort(
    (a, b) => `${b.date} ${b.time}`.localeCompare(`${a.date} ${a.time}`),
  )
  const latestPublish = sortedPublishes[0] ?? null

  const addSubtask = () => {
    const v = subtaskInput.trim().toUpperCase()
    if (!v) return
    if (!task.known_subtasks.map(s => s.toUpperCase()).includes(v)) {
      onPatchTask({ known_subtasks: [...task.known_subtasks, v] })
    }
    setSubtaskInput('')
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
      ...(asRetake ? { kind: 'retake' as const } : {}),   // absent = note
    }
    onPatchDetail({ comments: [...(detail.comments || []), comment] })
    setCommentInput('')
    setAsRetake(false)
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

  // Open the Publisher with the composer pre-filled from this task/subtask, ready
  // to publish. Assets → asset mode; shots/seqs → shot mode (TASK → the shot's
  // "Name", subtask → "Variante").
  const goPublishHere = () => {
    const taskTok = (sel.task || task.type_tokens[0] || task.name || '').toUpperCase()
    const instTok = '' // Artist supplies Instance in the Publisher.
    if (entityKind === 'asset') {
      const category = CLASS_TO_PUBLISHER_CATEGORY[asset.class.toUpperCase()] ?? asset.class.toUpperCase()
      navigate('/publisher', { state: { prefill: {
        project, mode: 'asset',
        sel: { category, name: asset.name.toUpperCase(), task: taskTok, instance: instTok, variante: '' },
      } } })
    } else {
      // shot: class = SEQxxx, name = SHOTxxx ; seq: name = SEQxxx (shot left blank)
      const seqLabel  = (entityKind === 'shot' ? asset.class : asset.name).toUpperCase()
      const shotLabel = (entityKind === 'shot' ? asset.name : '').toUpperCase()
      navigate('/publisher', { state: { prefill: {
        project, mode: 'shot',
        sel: { seq: seqLabel, shot: shotLabel, name: taskTok, variante: instTok },
      } } })
    }
  }

  const headerControls = <div className="production-retake-actions">
        {headerActions}
        {/* publish here — opens the Publisher with the composer pre-filled */}
        <button onClick={goPublishHere} title="Faire un publish ici" style={_headerBtn}>
          <UploadCloud size={12} strokeWidth={1.75} color="var(--accent-hi)" />
        </button>
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
  </div>

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      {renderHeader ? renderHeader(headerControls) : <div className="production-retake-header">{headerControls}</div>}

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
              <label title={t('prod.commentRetakeHint')} style={{
                display: 'inline-flex', alignItems: 'center', gap: 4, cursor: 'pointer',
                fontSize: 10, color: asRetake ? 'var(--err)' : 'var(--ink-3)', userSelect: 'none',
              }}>
                <input type="checkbox" checked={asRetake} onChange={e => setAsRetake(e.target.checked)} style={{ margin: 0 }} />
                {t('prod.commentRetake')}
              </label>
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
                      {c.kind === 'retake' && (
                        <span style={{
                          fontFamily: 'var(--mono)', fontSize: 8, fontWeight: 700, letterSpacing: '0.06em',
                          color: 'var(--err)', border: '1px solid color-mix(in oklch, var(--err) 45%, var(--rule-2))',
                          borderRadius: 3, padding: '0 4px',
                        }}>RETAKE</span>
                      )}
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
            onResolvedPath={(p, err) => { setRefBasePath(p); setRefError(err || '') }}
            onSelChange={(task, instance) => setSel({ task, instance })}
          />

          <div style={{ ..._lbl, marginBottom: 6, display: 'flex', alignItems: 'center', gap: 8 }}>
            <span>{t('prod.recentPublishes')}</span>
            {subtaskFilter && (
              <span style={{ color: color, textTransform: 'none', letterSpacing: 0 }}>
                · {subtaskFilter}
              </span>
            )}
            <span style={{ flex: 1 }} />
            {sortedPublishes.length > 0 && (
              <button
                onClick={() => setPublishListOpen(true)}
                title="Voir tous les publishs récents"
                style={{
                  border: 'none', background: 'transparent', cursor: 'pointer', padding: 0,
                  color: 'var(--ink-3)', display: 'inline-flex', alignItems: 'center',
                }}
              >
                <List size={15} strokeWidth={1.9} />
              </button>
            )}
          </div>
          {!latestPublish && (
            <div style={{ fontSize: 10, color: 'var(--ink-4)' }}>{t('prod.noPublishes')}</div>
          )}
          {latestPublish && (
            <PublishRow
              p={latestPublish}
              onOpen={() => openInFolderManager(latestPublish)}
              onCopy={() => copyPath(latestPublish)}
              onExplorer={() => openInExplorer(latestPublish)}
            />
          )}

          <MediaEmbed project={project || ''} relPath={refBasePath} unresolved={refError} color={color}
            context={`${entityKind === 'shot' ? `${asset.class} ${asset.name}` : asset.name} · ${task.name}${subtaskFilter ? ` · ${subtaskFilter}` : ''}`} />
        </div>
      </div>

      {publishListOpen && (
        <PublishListModal
          title={`${t('prod.recentPublishes')}${subtaskFilter ? ` · ${subtaskFilter}` : ` · ${task.name}`}`}
          publishes={sortedPublishes}
          color={color}
          onClose={() => setPublishListOpen(false)}
          onOpen={openInFolderManager}
          onCopy={copyPath}
          onExplorer={openInExplorer}
        />
      )}
    </div>
  )
}

// ── one recent-publish row (inline latest + modal list) ──────────────────────
function PublishRow({ p, onOpen, onCopy, onExplorer }: {
  p:          ProductionPublish
  onOpen:     () => void
  onCopy:     () => void
  onExplorer: () => void
}) {
  // Publish comment on hover — positioned `fixed` at the cursor so it is never
  // clipped by the surrounding overflow:auto containers.
  const [tip, setTip] = useState<{ x: number; y: number } | null>(null)
  const comment = (p.description || '').trim()
  // "Ouvrir dans >" like the Folder Manager (2026-09-26): the published file.
  const { project } = useProject()
  const rel = p.dest_folder && project ? projectRelPath(project, `${p.dest_folder}/${p.file}`) : ''
  return (
    <div
      onClick={onOpen}
      onMouseMove={e => { if (comment) setTip({ x: e.clientX, y: e.clientY }) }}
      onMouseLeave={() => setTip(null)}
      style={{
        padding: '5px 8px', borderRadius: 5,
        border: '1px solid var(--rule-2)', background: 'var(--paper)',
        marginBottom: 3, display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer',
      }}
    >
      {tip && comment && (
        <div style={{
          position: 'fixed', left: tip.x + 14, top: tip.y + 14, zIndex: 4000,
          maxWidth: 320, padding: '7px 10px', borderRadius: 6, pointerEvents: 'none',
          background: 'var(--paper)', border: '1px solid var(--rule-2)', boxShadow: 'var(--shadow-md)',
          fontFamily: 'var(--sans)', fontSize: 10, color: 'var(--ink)', lineHeight: 1.45, whiteSpace: 'pre-wrap',
        }}>
          <span style={{
            display: 'block', marginBottom: 2, fontFamily: 'var(--mono)', fontSize: 8,
            color: 'var(--ink-4)', textTransform: 'uppercase', letterSpacing: '0.06em',
          }}>Commentaire</span>
          {comment}
        </div>
      )}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 10, color: 'var(--ink)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontFamily: 'var(--mono)' }}>
          {p.file}
        </div>
        <div style={{ fontSize: 8, color: 'var(--ink-4)', marginTop: 1 }}>
          {p.user} · {p.date} {p.time}
        </div>
        {comment && (
          <div style={{ fontSize: 8.5, color: 'var(--ink-2)', marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {comment}
          </div>
        )}
      </div>
      {rel && <OpenInMenu project={project} relPath={rel} compact />}
      <button style={_miniIconBtn} title="Copier" onClick={e => { e.stopPropagation(); onCopy() }}>
        <Copy size={9} strokeWidth={1.75} />
      </button>
      <button style={_miniIconBtn} title="Folder Manager" onClick={e => { e.stopPropagation(); onOpen() }}>
        <FolderTree size={9} strokeWidth={1.75} />
      </button>
      <button style={_miniIconBtn} title="Explorateur" onClick={e => { e.stopPropagation(); onExplorer() }}>
        <FolderOpen size={9} strokeWidth={1.75} />
      </button>
    </div>
  )
}

// ── all-recent-publishes modal (newest first, by date) ───────────────────────
function PublishListModal({ title, publishes, color, onClose, onOpen, onCopy, onExplorer }: {
  title:      string
  publishes:  ProductionPublish[]
  color:      string
  onClose:    () => void
  onOpen:     (p: ProductionPublish) => void
  onCopy:     (p: ProductionPublish) => void
  onExplorer: (p: ProductionPublish) => void
}) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [onClose])

  return (
    <div
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
      style={{
        position: 'fixed', inset: 0, zIndex: 3000, background: 'rgba(0,0,0,0.55)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24,
      }}
    >
      <div style={{
        width: 720, maxWidth: '92vw', maxHeight: '82vh',
        background: 'var(--paper)', border: '1px solid var(--rule-2)', borderRadius: 12,
        boxShadow: 'var(--shadow)', display: 'flex', flexDirection: 'column',
      }}>
        <div style={{
          display: 'flex', alignItems: 'center', gap: 10,
          padding: '14px 18px', borderBottom: '1px solid var(--rule)',
        }}>
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: color, flexShrink: 0 }} />
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)' }}>{title}</div>
          <span style={{ fontSize: 10, color: 'var(--ink-4)' }}>· {publishes.length}</span>
          <span style={{ flex: 1 }} />
          <button onClick={onClose} title="Fermer" style={{
            width: 26, height: 22, borderRadius: 4, border: '1px solid var(--rule-2)',
            background: 'var(--paper-2)', color: 'var(--ink-2)', cursor: 'pointer',
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          }}><X size={12} strokeWidth={1.75} /></button>
        </div>
        <div style={{ flex: 1, overflowY: 'auto', padding: '12px 18px' }}>
          {publishes.length === 0 && (
            <div style={{ fontSize: 11, color: 'var(--ink-4)' }}>—</div>
          )}
          {publishes.map(p => (
            <PublishRow
              key={p.id}
              p={p}
              onOpen={() => onOpen(p)}
              onCopy={() => onCopy(p)}
              onExplorer={() => onExplorer(p)}
            />
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
// Compact token selector. Four slots: CLASS / NAME / TASK / INSTANCE. CLASS +
// NAME are pinned to the current asset; TASK and INSTANCE are selectable
// dropdowns fed by the project's tokens.json (+ subtasks the artist has
// actually seen on this task). Each slot change composes a new project-relative
// path and writes it to task.path_override; the resolved path is bubbled up via
// onResolvedPath so the /ref embed folder can be located.
function PathBrowser({ project, asset, task, entityKind, subtaskFilter, onPatchTask, onResolvedPath, onSelChange }: {
  project:        string
  asset:          Asset
  task:           ProductionTask
  entityKind:     'asset' | 'shot' | 'seq'
  subtaskFilter:  string | null
  onPatchTask:    (patch: Partial<ProductionTask>) => void
  onResolvedPath: (path: string, error?: string) => void   // '' + error = unresolved, and why
  onSelChange:    (task: string, instance: string) => void
}) {
  const { t } = useI18n()
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
    if (!project) { onResolvedPath('', t('prod.refNoProject')); return }
    // A shot carries its sequence name in asset.class (MenuSpec toAssetShim). Empty =
    // the shot's sequence was not found: resolving would give shot//SHOT (collapsed to
    // shot/SHOT), a wrong folder, so refuse with a clear reason instead.
    const seqName = (asset.class || '').trim()
    if (entityKind === 'shot' && !seqName) { onResolvedPath('', t('prod.refNoSeq')); return }
    let ok = true
    const params = entityKind === 'asset'
      ? { kind: 'asset' as const, class_token: asset.class, name: asset.name, task: selTask, subtask: selInstance }
      : entityKind === 'shot'
        ? { kind: 'shot' as const, seq: seqName, shot: asset.name, task: selTask, subtask: selInstance }
        : { kind: 'seq' as const,  seq: asset.name, task: selTask, subtask: selInstance }
    api.resolveRefPath(project, params)
      .then(r => { if (ok) onResolvedPath(r.rel_path || '', r.rel_path ? '' : t('prod.refUnresolved')) })
      .catch(e => { if (ok) onResolvedPath('', t('prod.refResolveFailed', { err: e instanceof Error ? e.message : String(e) })) })
    return () => { ok = false }
  }, [project, entityKind, asset.class, asset.name, selTask, selInstance])   // eslint-disable-line react-hooks/exhaustive-deps

  // Bubble the current TASK/INSTANCE selection up so "Publish here" can prefill.
  useEffect(() => { onSelChange(selTask, selInstance) }, [selTask, selInstance])   // eslint-disable-line react-hooks/exhaustive-deps

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
// deposit a new version on disk; the newest (LAST) shows by default. Videos
// play on hover (muted, looping, no controls). Click opens a full-screen
// overlay; clicking the greyed backdrop minimises it back.
// Retake 10: a strip UNDER the media (never over it) names the version shown;
// "Versions" lists every deposit from the ref folder's modif log (author, date,
// status, thumbnail) to watch an older one, with "Dernière version" to come
// back. The choice is kept for the session per zone. Keyframe Pro opens the
// shown version with the other versions of the folder (retake 09).
const _IMAGE_EXT = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'apng', 'avif', 'svg']
const _VIDEO_EXT = ['mp4', 'webm', 'ogv', 'ogg', 'm4v', 'mov', 'mkv']

function isAcceptedMedia(file: File): boolean {
  if (file.type.startsWith('audio/')) return false
  if (file.type.startsWith('image/') || file.type.startsWith('video/')) return true
  const ext = file.name.split('.').pop()?.toLowerCase() ?? ''
  return _IMAGE_EXT.includes(ext) || _VIDEO_EXT.includes(ext)
}

const viewKey = (project: string, relPath: string) => `ref.view:${project}:${relPath}`

function MediaEmbed({ project, relPath, unresolved, color, context }: {
  project: string
  relPath: string
  unresolved: string       // why relPath is empty ('' while resolving or when resolved)
  color:   string
  context: string          // "SEQ010 SHOT020 · ANIM": the Keyframe source names
}) {
  const { t } = useI18n()
  const [latest, setLatest] = useState<{ file: string; kind: string } | null>(null)
  const [versions, setVersions] = useState<RefVersion[]>([])
  const [rev, setRev]       = useState(0)          // cache-buster: LAST.* is overwritten in place
  const [dragOver, setDragOver] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [full, setFull]     = useState(false)
  const [listOpen, setListOpen] = useState(false)
  const [mediaError, setMediaError] = useState(false)
  // Version being watched (vNNN file), null = the latest. Session memory per zone,
  // so switching tabs keeps it; a restart comes back to the latest.
  const [viewing, setViewingState] = useState<string | null>(null)
  useEffect(() => { setViewingState(readSession<string | null>(viewKey(project, relPath)) ?? null); setListOpen(false) }, [project, relPath])
  const setViewing = (file: string | null) => {
    setViewingState(file); writeSession(viewKey(project, relPath), file); setMediaError(false)
  }

  const canUse = !!project && !!relPath
  // Shown (placeholder, drag hint, toast) when a drop can't land: never fail silently.
  const blockedReason = canUse ? '' : (unresolved || (project ? t('prod.refUnresolved') : t('prod.refNoProject')))

  const refresh = useCallback((): (() => void) | undefined => {
    if (!canUse) { setLatest(null); setVersions([]); return undefined }
    let ok = true
    api.getRefLatest(project, relPath)
      .then(r => { if (ok) setLatest(r.found && r.file && r.kind ? { file: r.file, kind: r.kind } : null) })
      .catch(() => { if (ok) setLatest(null) })
    api.getRefVersions(project, relPath)
      .then(r => { if (ok) setVersions(r.versions) })
      .catch(() => { if (ok) setVersions([]) })
    return () => { ok = false }
  }, [project, relPath, canUse])

  useEffect(() => refresh(), [refresh])

  const doUpload = useCallback(async (files: FileList | File[]) => {
    if (!canUse) { toast.error(blockedReason); return }
    const list = Array.from(files).filter(isAcceptedMedia)
    if (list.length === 0) { toast.error('Formats acceptés : images et vidéos (pas d’audio)'); return }
    setUploading(true)
    try {
      // Deposit sequentially so the version numbering stays deterministic.
      for (const f of list) await api.depositRef(project, relPath, f)
      setRev(v => v + 1)
      setViewing(null)                         // a new deposit is what you want to see
      refresh()
      toast.success(list.length > 1 ? `${list.length} fichiers déposés` : 'Fichier déposé')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setUploading(false)
    }
  }, [project, relPath, canUse, blockedReason, refresh])   // eslint-disable-line react-hooks/exhaustive-deps

  // Always accept the drag inside the zone (A6): when dragover is not cancelled,
  // Chromium never fires drop, so an unresolved path used to make the drop vanish
  // with no feedback. The drop then explains why it can't land.
  const onDragOver = (e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation()
    e.dataTransfer.dropEffect = 'copy'
    if (!dragOver) setDragOver(true)
  }
  const onDrop = (e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation()
    setDragOver(false)
    if (e.dataTransfer.files?.length) void doUpload(e.dataTransfer.files)
    else toast.error(t('prod.refNoFile'))
  }

  const newest = versions.find(v => v.latest) ?? null
  const watched = viewing ? versions.find(v => v.file === viewing) ?? null : null
  const lostVersion = !!viewing && versions.length > 0 && (!watched || !watched.available)
  // What the slot shows: the watched version, else LAST.
  const shown = watched && watched.available
    ? { file: watched.file, kind: watched.kind, playable: watched.playable, version: watched.version, old: !watched.latest }
    : latest
      ? { file: latest.file, kind: latest.kind, playable: newest ? newest.playable : true, version: newest?.version ?? '', old: false }
      : null
  const unreadable = !!shown && (!shown.playable || mediaError)
  const nextVersion = `v${String((versions.reduce((m, v) => Math.max(m, Number(v.version.slice(1)) || 0), 0)) + 1).padStart(3, '0')}`

  const download = async () => {
    if (!shown) return
    const ext = shown.file.split('.').pop() ?? ''
    const suggested = `${relPath.split('/').pop() || 'ref'}_${shown.file}`
    const dest = await window.electronAPI?.saveFile?.(suggested, [
      { name: shown.kind === 'video' ? 'Vidéo' : 'Image', extensions: [ext] },
      { name: 'Tous les fichiers', extensions: ['*'] },
    ])
    if (!dest) return
    try {
      await api.exportRef(project, relPath, shown.file, dest)
      toast.success('Téléchargé')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }

  const { settings } = useSettings()
  const openKeyframe = (file: string, version: string) => {
    const rel = `${relPath}/ref/${file}`
    void openInKeyframe(project, [{ rel_path: rel, label: `${context} · ${version || file}` }], {
      title: context,
      fallbackPath: expandFluxPath(`$FLUX/DOSSIER_PROJETS/${project}/${rel}`, settings?.workspace),
    })
  }

  const src = shown ? `${api.refFileUrl(project, relPath, shown.file)}&rev=${rev}` : ''

  return (
    <>
      <div style={{ ..._lbl, marginTop: 14, marginBottom: 6, display: 'flex', alignItems: 'center', gap: 6 }}>
        <span>Références</span>
        {uploading && <span style={{ fontSize: 8, color: 'var(--ink-4)', textTransform: 'none' }}>envoi…</span>}
      </div>

      <div
        onDragEnter={onDragOver}
        onDragOver={onDragOver}
        onDragLeave={e => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragOver(false) }}
        onDrop={onDrop}
      >
        <div
          style={{
            position: 'relative',
            borderRadius: shown ? '8px 8px 0 0' : 8,
            border: `1px ${shown ? 'solid' : 'dashed'} ${dragOver ? color : shown?.old ? 'var(--warn)' : 'var(--rule-2)'}`,
            background: dragOver ? `color-mix(in oklch, ${color} 12%, var(--paper))` : 'var(--paper)',
            overflow: 'hidden',
            minHeight: shown ? undefined : 90,
            aspectRatio: shown ? '16 / 9' : undefined,
            maxHeight: 320,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            cursor: shown && !unreadable ? 'pointer' : 'default',
          }}
          onClick={() => { if (shown && !unreadable) setFull(true) }}
          title={shown ? (unreadable ? '' : 'Cliquer pour agrandir') : 'Glissez une image ou une vidéo ici'}
        >
          {shown && !unreadable ? (
            <>
              <HoverMedia key={src} src={src} kind={shown.kind} onError={() => setMediaError(true)} />
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
            </>
          ) : shown ? (
            <div style={_placeholder}>
              <Film size={18} strokeWidth={1.5} />
              <span>Format non lisible dans FLUX ({shown.file.split('.').pop()})</span>
              <button style={_stripBtn} onClick={e => { e.stopPropagation(); openKeyframe(shown.file, shown.version) }}>
                <Clapperboard size={11} strokeWidth={1.75} /> Ouvrir dans Keyframe Pro
              </button>
            </div>
          ) : (
            <div style={_placeholder}>
              <div style={{ display: 'flex', gap: 6 }}>
                <ImageIcon size={16} strokeWidth={1.5} />
                <Film size={16} strokeWidth={1.5} />
              </div>
              {canUse
                ? <span><UploadCloud size={11} style={{ verticalAlign: '-2px' }} strokeWidth={1.75} /> Glissez une image ou une vidéo</span>
                : <span style={{ color: 'var(--warn)', textAlign: 'center' }}>{blockedReason}</span>}
            </div>
          )}
          {dragOver && <div style={_dropHint}>{!canUse ? blockedReason : shown ? `Déposer : nouvelle version ${nextVersion}` : 'Déposer pour créer v001'}</div>}
        </div>

        {/* Strip under the media: which version, the way back, the version list, Keyframe. */}
        {(shown || lostVersion) && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap',
            padding: '5px 8px', border: `1px solid ${shown?.old || lostVersion ? 'var(--warn)' : 'var(--rule-2)'}`, borderTop: 'none',
            borderRadius: listOpen ? 0 : '0 0 8px 8px',
            background: shown?.old || lostVersion ? 'color-mix(in oklch, var(--warn) 10%, var(--paper-2))' : 'var(--paper-2)',
            fontSize: 10, color: 'var(--ink-2)',
          }}>
            {lostVersion ? (
              <span style={{ color: 'var(--warn)', fontWeight: 600 }}>Version {watched?.version ?? viewing} inaccessible</span>
            ) : shown && (
              <>
                <span style={{ fontFamily: 'var(--mono)', fontWeight: 700, color: shown.old ? 'var(--warn)' : 'var(--ink)' }}>{shown.version || 'LAST'}</span>
                <span style={{ color: 'var(--ink-4)' }}>{shown.old ? 'ancienne version' : 'dernière version'}</span>
              </>
            )}
            {(shown?.old || lostVersion) && (
              <button style={{ ..._stripBtn, borderColor: 'var(--warn)' }} onClick={() => setViewing(null)} title="Revenir à la dernière version">
                <RotateCcw size={10} strokeWidth={2} /> Dernière version
              </button>
            )}
            <span style={{ flex: 1 }} />
            {versions.length > 1 && (
              <button style={_stripBtn} aria-expanded={listOpen} onClick={() => setListOpen(o => !o)}
                title="Voir les autres versions de cette zone">
                <History size={10} strokeWidth={2} /> Versions ({versions.length})
              </button>
            )}
            {shown && shown.kind === 'video' && (
              <button style={_stripBtn} onClick={() => openKeyframe(shown.file, shown.version)}
                title="Ouvrir dans Keyframe Pro, avec les autres versions du dossier">
                <Clapperboard size={10} strokeWidth={2} /> Keyframe
              </button>
            )}
          </div>
        )}
        {listOpen && versions.length > 1 && (
          <VersionList
            project={project} relPath={relPath} versions={versions}
            current={watched?.file ?? newest?.file ?? ''}
            onPick={v => { setViewing(v.latest ? null : v.file); setListOpen(false) }}
            onKeyframe={v => openKeyframe(v.file, v.version)}
            onClose={() => setListOpen(false)}
          />
        )}
      </div>

      {full && shown && !unreadable && (
        <FullscreenMedia src={src} kind={shown.kind} onClose={() => setFull(false)} />
      )}
    </>
  )
}

// Every version of the zone, newest first. Arrow keys move, Enter watches, Escape closes.
function VersionList({ project, relPath, versions, current, onPick, onKeyframe, onClose }: {
  project:    string
  relPath:    string
  versions:   RefVersion[]
  current:    string
  onPick:     (v: RefVersion) => void
  onKeyframe: (v: RefVersion) => void
  onClose:    () => void
}) {
  const listRef = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLButtonElement>('[data-current="true"]') ?? listRef.current?.querySelector<HTMLButtonElement>('button[data-row]')
    el?.focus()
  }, [])
  const onKey = (e: React.KeyboardEvent) => {
    const rows = [...(listRef.current?.querySelectorAll<HTMLButtonElement>('button[data-row]') ?? [])]
    const i = rows.indexOf(document.activeElement as HTMLButtonElement)
    if (e.key === 'ArrowDown') { e.preventDefault(); rows[Math.min(rows.length - 1, i + 1)]?.focus() }
    else if (e.key === 'ArrowUp') { e.preventDefault(); rows[Math.max(0, i - 1)]?.focus() }
    else if (e.key === 'Escape') { e.preventDefault(); onClose() }
  }
  return (
    <div ref={listRef} role="listbox" aria-label="Versions" onKeyDown={onKey} style={{
      border: '1px solid var(--rule-2)', borderTop: 'none', borderRadius: '0 0 8px 8px',
      background: 'var(--paper)', maxHeight: 260, overflowY: 'auto', padding: 4,
    }}>
      {versions.map(v => {
        const isCurrent = v.file === current
        const status = !v.available ? 'Inaccessible' : !v.playable ? 'Non lisible ici' : v.latest ? 'Dernière' : ''
        return (
          <div key={v.file} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <button
              data-row role="option" aria-selected={isCurrent} data-current={isCurrent}
              disabled={!v.available}
              onClick={() => onPick(v)}
              style={{
                flex: 1, minWidth: 0, display: 'flex', alignItems: 'center', gap: 8, padding: 4,
                borderRadius: 5, border: `1px solid ${isCurrent ? 'var(--accent)' : 'transparent'}`,
                background: isCurrent ? 'var(--accent-soft)' : 'transparent', textAlign: 'left',
                cursor: v.available ? 'pointer' : 'not-allowed', opacity: v.available ? 1 : 0.55, color: 'var(--ink)',
              }}
            >
              <VersionThumb src={v.available && v.playable ? api.refFileUrl(project, relPath, v.file) : ''} kind={v.kind} />
              <span style={{ display: 'flex', flexDirection: 'column', minWidth: 0, flex: 1 }}>
                <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span style={{ fontFamily: 'var(--mono)', fontSize: 10, fontWeight: 700 }}>{v.version}</span>
                  {status && <span style={{ ..._chip, color: v.latest && v.available ? 'var(--ok)' : 'var(--warn)' }}>{status}</span>}
                  {isCurrent && <span style={{ ..._chip, color: 'var(--accent-hi)' }}>affichée</span>}
                </span>
                <span style={{ fontSize: 9, color: 'var(--ink-4)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {v.logged ? `${v.user || '?'} · ${v.date} ${v.time}` : 'avant le journal (auteur et date inconnus)'}
                  {v.source_name ? ` · ${v.source_name}` : ''}
                </span>
              </span>
            </button>
            {v.available && v.kind === 'video' && (
              <button style={_miniIconBtn} title="Ouvrir cette version dans Keyframe Pro" onClick={() => onKeyframe(v)}>
                <Clapperboard size={9} strokeWidth={1.75} />
              </button>
            )}
          </div>
        )
      })}
    </div>
  )
}

// First frame of a video (metadata only) or the image; an icon when not shown here.
function VersionThumb({ src, kind }: { src: string; kind: string }) {
  const box: React.CSSProperties = {
    width: 56, height: 32, borderRadius: 3, flexShrink: 0, background: '#000', overflow: 'hidden',
    display: 'inline-flex', alignItems: 'center', justifyContent: 'center', color: 'var(--ink-4)',
  }
  if (!src) return <span style={{ ...box, background: 'var(--paper-2)' }}>{kind === 'video' ? <Film size={12} /> : <ImageIcon size={12} />}</span>
  return kind === 'video'
    ? <video src={`${src}#t=0.1`} muted preload="metadata" style={{ ...box, objectFit: 'cover' }} />
    : <img src={src} alt="" style={{ ...box, objectFit: 'cover' }} />
}

// Video plays on hover only (muted / looping / no controls); images just show.
function HoverMedia({ src, kind, onError }: { src: string; kind: string; onError?: () => void }) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  if (kind === 'video') {
    return (
      <video
        ref={videoRef}
        src={src}
        onError={onError}
        muted loop playsInline preload="metadata"
        onMouseEnter={() => { void videoRef.current?.play().catch(() => {}) }}
        onMouseLeave={() => { const v = videoRef.current; if (v) { v.pause(); v.currentTime = 0 } }}
        style={{ width: '100%', height: '100%', objectFit: 'contain', background: '#000', display: 'block' }}
      />
    )
  }
  return (
    <img src={src} alt="référence" onError={onError}
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

const _placeholder: React.CSSProperties = {
  display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6,
  color: 'var(--ink-4)', fontSize: 10, padding: 12, textAlign: 'center',
}
const _stripBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 4, height: 20, padding: '0 7px',
  borderRadius: 4, border: '1px solid var(--rule-2)', background: 'var(--paper)',
  color: 'var(--ink-2)', fontSize: 9.5, cursor: 'pointer', whiteSpace: 'nowrap',
}
const _chip: React.CSSProperties = {
  fontFamily: 'var(--mono)', fontSize: 8, fontWeight: 700, letterSpacing: '0.05em',
  textTransform: 'uppercase',
}
const _dropHint: React.CSSProperties = {
  position: 'absolute', inset: 0, zIndex: 3, pointerEvents: 'none',
  display: 'flex', alignItems: 'center', justifyContent: 'center',
  background: 'color-mix(in oklch, var(--paper) 55%, transparent)',
  color: 'var(--ink)', fontSize: 11, fontWeight: 600, textAlign: 'center', padding: 12,
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
