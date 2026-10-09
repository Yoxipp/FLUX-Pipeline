// MyRetakes.tsx - home page "Tes retakes": the comments marked as retake
// (ProductionComment.kind === 'retake', TaskDetail) written by someone else on a
// task / subtask assigned to the current artist. Source = the task_details comments
// of the production store, no second store. Newest first; a click opens the task in
// Production like "Tes tâches". A retake on a parent task (ANIM) also reaches the
// artist assigned to one of its subtasks (ANIM|BLOCK), same as the activity "mine" logic.

import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Btn } from '../../components/shared/ui'
import type { UseProductionResult } from '../../hooks/useProduction'
import { useCommentReadState } from '../../hooks/useCommentReadState'
import { useI18n } from '../../i18n'
import type { ProductionAsset, ProductionShot, ProductionState } from '../../types'

const PAGE = 20

export interface MyRetake {
  id:      string                 // comment id
  text:    string
  author:  string
  stamp:   string                 // "YYYY-MM-DD HH:MM"
  label:   string                 // "SEQ0010 SHOT0020" or "CHAR HERO"
  seq:     string                 // sequence name for a shot, class for an asset
  name:    string
  task:    string
  subtask: string
}

/** Retake comments by other users on the tasks / subtasks assigned to *username*, newest first. */
export function myRetakes(state: ProductionState, username: string): MyRetake[] {
  const who = username.trim().toUpperCase()
  if (!who) return []
  const out: MyRetake[] = []
  const entities: (ProductionShot | ProductionAsset)[] = [...state.shots, ...state.assets]
  for (const entity of entities) {
    const details = Object.entries(entity.task_details ?? {})
    const mine = details.filter(([, d]) => d.assignee?.trim().toUpperCase() === who).map(([k]) => k.toUpperCase())
    if (!mine.length) continue
    const isShot = 'seq_id' in entity
    const seq = isShot ? state.sequences.find(s => s.id === entity.seq_id)?.name ?? '' : entity.class
    for (const [key, detail] of details) {
      const upper = key.toUpperCase()
      const [task, subtask = ''] = key.split('|')
      const concerned = mine.includes(upper) || (!subtask && mine.some(k => k.startsWith(`${upper}|`)))
      if (!concerned) continue
      for (const c of detail.comments ?? []) {
        if (c.kind !== 'retake' || (c.author ?? '').trim().toUpperCase() === who) continue
        out.push({
          id: c.id, text: c.text, author: c.author, stamp: `${c.date} ${(c.time ?? '').slice(0, 5)}`.trim(),
          label: `${seq} ${entity.name}`.trim(), seq, name: entity.name, task, subtask,
        })
      }
    }
  }
  return out.sort((a, b) => b.stamp.localeCompare(a.stamp) || a.id.localeCompare(b.id))
}

export function MyRetakes({ project, username, prod }: { project: string | null | undefined; username: string; prod: UseProductionResult }) {
  const navigate = useNavigate()
  const { t } = useI18n()
  const readState = useCommentReadState()
  const [shown, setShown] = useState(PAGE)
  const retakes = useMemo(() => myRetakes(prod.state, username), [prod.state, username])
  const unread = retakes.filter(r => !readState.isRead(r.id)).length

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: 0, flex: 1 }}>
      <div style={{ padding: '7px 14px', borderBottom: '1px solid var(--rule)', display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
        <div className="cap">{t('hub.yourRetakes')}</div>
        {retakes.length > 0 && <span className="lbl" style={{ color: 'var(--ink-3)' }}>{unread}{unread !== retakes.length ? ` / ${retakes.length}` : ''}</span>}
      </div>
      <div style={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>
        {project && !prod.loading && !retakes.length && (
          <div style={{ padding: '10px 14px', fontSize: 11, color: 'var(--ink-4)', lineHeight: 1.5 }}>{t('hub.noRetake')}</div>
        )}
        {project && retakes.slice(0, shown).map(r => {
          const read = readState.isRead(r.id)
          const where = `${r.label} · ${r.task}${r.subtask ? ` · ${r.subtask}` : ''}`
          return (
            <div key={r.id} className="row" role="button" tabIndex={0}
              style={{ padding: '7px 14px', gap: 10, cursor: 'pointer', alignItems: 'flex-start', opacity: read ? 0.6 : 1 }}
              title={where}
              onClick={() => navigate('/production', { state: { openFavorite: { project, class: r.seq, name: r.name, task: r.task, subtask: r.subtask || undefined } } })}
              onKeyDown={e => { if (e.key === 'Enter') (e.currentTarget as HTMLElement).click() }}>
              <span className="tracking-status" data-status="RTK" style={{ flexShrink: 0, marginTop: 1 }}>RTK</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 11, color: 'var(--ink)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  <span style={{ fontFamily: 'var(--mono)' }}>{r.label}</span>
                  <span style={{ color: 'var(--ink-3)' }}> · {r.task}{r.subtask ? ` · ${r.subtask}` : ''}</span>
                </div>
                <div style={{ fontSize: 11, color: 'var(--ink-2)', marginTop: 2, lineHeight: 1.4, whiteSpace: 'pre-wrap',
                  display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', overflow: 'hidden', fontWeight: read ? 400 : 500 }}>
                  {r.text}
                </div>
                <div className="lbl" style={{ marginTop: 2 }}>{r.author} · <span style={{ color: 'var(--ink-3)' }}>{r.stamp}</span></div>
              </div>
            </div>
          )
        })}
        {project && retakes.length > shown && (
          <div style={{ padding: '10px 14px', display: 'flex', justifyContent: 'center' }}>
            <Btn sm ghost onClick={() => setShown(n => n + PAGE)}>{t('hub.showMore', { n: retakes.length - shown })}</Btn>
          </div>
        )}
      </div>
    </div>
  )
}
