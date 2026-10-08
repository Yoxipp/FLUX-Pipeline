// MyTasks.tsx - home page "Mes tâches" (retake 07): every task / subtask of the active
// project assigned to the current artist, sorted by the shared Production logic
// (Production/taskPriority.ts: deadline from the Calendar, priority, status). A click
// opens the task in Production. Validated tasks stay at the end, long lists load by page.

import { useMemo, useState } from 'react'
import { ArrowDown, CalendarClock } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { ExpandPicker } from '../../components/shared/ExpandPicker'
import { Btn } from '../../components/shared/ui'
import { useProduction } from '../../hooks/useProduction'
import { useSessionState } from '../../hooks/useSessionState'
import { useShotCalendar } from '../Production/ShotDeadlineBadge'
import { myTasks, sortMyTasks, PRIORITY_LABEL, SORT_LABEL, type MyTaskSort } from '../Production/taskPriority'
import { STATUS_LABELS, STATUS_TOKENS } from '../Production/tracking'
import '../Production/tracking.css'

const PAGE = 30

function deadlineTone(deadline: string | null, today: string): string {
  if (!deadline) return 'var(--ink-4)'
  if (deadline < today) return 'var(--err)'
  const days = (Date.parse(deadline) - Date.parse(today)) / 86_400_000
  return days < 5 ? 'var(--warn)' : 'var(--ink-3)'
}

export function MyTasks({ project, username }: { project: string | null | undefined; username: string }) {
  const navigate = useNavigate()
  const prod = useProduction(project || null)
  const calendar = useShotCalendar(project || '', Boolean(project))
  const [sort, setSort] = useSessionState<MyTaskSort>('hub.myTasks.sort', 'smart')
  const [shown, setShown] = useState(PAGE)
  const today = new Date().toISOString().slice(0, 10)

  const tasks = useMemo(
    () => sortMyTasks(myTasks(prod.state, username, calendar.items, prod.publishesByTask), sort),
    [prod.state, username, calendar.items, prod.publishesByTask, sort])
  const open = tasks.filter(t => t.status !== 'APPROVED').length

  if (!project) return <Empty text="Choisis un projet pour voir tes tâches." />

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: 0, flex: 1 }}>
      <div style={{ padding: '7px 14px', borderBottom: '1px solid var(--rule)', display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
        <div className="cap">Mes tâches</div>
        <span className="lbl" style={{ color: 'var(--ink-3)' }}>{open}{tasks.length !== open ? ` / ${tasks.length}` : ''}</span>
        <div style={{ flex: 1 }} />
        <ExpandPicker title="Trier par" value={sort} onChange={v => { setSort(v as MyTaskSort); setShown(PAGE) }}
          options={(Object.keys(SORT_LABEL) as MyTaskSort[]).map(k => ({ value: k, label: SORT_LABEL[k],
            title: k === 'smart' ? 'Deadline du calendrier, puis priorité, puis statut' : undefined }))} />
      </div>
      <div style={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>
        {prod.loading && !tasks.length && <Empty text="Chargement…" />}
        {!prod.loading && !tasks.length && (
          <Empty text={`Aucune tâche assignée à ${username} dans ${project}. Dans Production, clic droit sur un badge > Artiste > Prendre la task.`} />
        )}
        {tasks.slice(0, shown).map(t => {
          const status = t.status || 'TODO'
          return (
            <div key={t.id} className="row" role="button" tabIndex={0}
              style={{ padding: '7px 14px', gap: 10, cursor: 'pointer', opacity: t.status === 'APPROVED' ? 0.55 : 1 }}
              title={`${t.label} · ${t.task.name}${t.subtask ? ` · ${t.subtask}` : ''} · ${STATUS_LABELS[status] ?? status} · priorité ${PRIORITY_LABEL[t.priority].toLowerCase()}`}
              onClick={() => navigate('/production', { state: { openFavorite: { project, class: t.seq, name: t.entity.name, task: t.task.name, subtask: t.subtask || undefined } } })}
              onKeyDown={e => { if (e.key === 'Enter') (e.currentTarget as HTMLElement).click() }}>
              <span style={{ display: 'inline-flex', alignItems: 'center', flexShrink: 0 }}>
                {t.priority === 'high' ? <span className="tracking-priority-high" aria-label="Priorité haute">!</span> : <span style={{ width: 11 }} />}
              <span className="tracking-status" data-status={STATUS_TOKENS.includes(status) ? status : 'UNKNOWN'} >{status}</span>
              </span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 11, color: 'var(--ink)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'flex', alignItems: 'center', gap: 4 }}>
                  {t.priority === 'low' && <ArrowDown size={11} strokeWidth={2.4} color="var(--ink-4)" aria-label="Priorité basse" />}
                  <span style={{ fontFamily: 'var(--mono)' }}>{t.label}</span>
                  <span style={{ color: 'var(--ink-3)' }}>· {t.task.name}{t.subtask ? ` · ${t.subtask}` : ''}</span>
                </div>
                <div className="lbl" style={{ marginTop: 2, display: 'flex', gap: 8 }}>
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 3, color: deadlineTone(t.deadline, today) }}>
                    <CalendarClock size={10} />{t.deadline ?? 'sans deadline'}
                  </span>
                  {t.updated && <span>maj {t.updated}</span>}
                </div>
              </div>
            </div>
          )
        })}
        {tasks.length > shown && (
          <div style={{ padding: '10px 14px', display: 'flex', justifyContent: 'center' }}>
            <Btn sm ghost onClick={() => setShown(n => n + PAGE)}>Afficher plus ({tasks.length - shown})</Btn>
          </div>
        )}
      </div>
    </div>
  )
}

function Empty({ text }: { text: string }) {
  return <div style={{ padding: '10px 14px', fontSize: 11, color: 'var(--ink-4)', lineHeight: 1.5 }}>{text}</div>
}
