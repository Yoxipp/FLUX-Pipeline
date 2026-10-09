// MyTasks.tsx - home page "Mes tâches" (retake 07): every task / subtask of the active
// project assigned to the current artist, sorted by the shared Production logic
// (Production/taskPriority.ts: deadline from the Calendar, priority, status). A click
// opens the task in Production. Validated tasks stay at the end; the whole list scrolls.
// Calendar commitments owned by the artist (2026-10-09) are listed first; a click opens
// them in the Calendar (?item=<id>). Declined ones are left out, done ones go to the end.

import { useMemo } from 'react'
import { ArrowDown, CalendarClock, CalendarDays } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { ExpandPicker } from '../../components/shared/ExpandPicker'
import { ScrollMore } from '../../components/shared/ScrollMore'
import type { UseProductionResult } from '../../hooks/useProduction'
import type { CalendarItem } from '../../types'
import { STATE_COLOR, STATUS_LABEL } from '../Calendar'
import { useSessionState } from '../../hooks/useSessionState'
import { useShotCalendar } from '../Production/ShotDeadlineBadge'
import { myTasks, sortMyTasks, PRIORITY_LABEL, SORT_LABEL, type MyTaskSort } from '../Production/taskPriority'
import { STATUS_LABELS, STATUS_TOKENS } from '../Production/tracking'
import '../Production/tracking.css'
import { useI18n } from '../../i18n'

// What the list shows (2026-10-09): Production tasks, calendar commitments, or a mix.
type TaskFilter = 'all' | 'production' | 'calendar' | 'open' | 'to_accept'
const FILTER_LABEL: Record<TaskFilter, string> = {
  all: 'Tout', production: 'Production', calendar: 'Calendrier', open: 'En cours', to_accept: 'À accepter',
}
const FILTER_HINT: Record<TaskFilter, string> = {
  all: 'Tâches Production + engagements du calendrier',
  production: 'Seulement les tâches Production qui te sont assignées',
  calendar: 'Seulement tes engagements du calendrier',
  open: "Tout ce qui n'est pas validé ou fini",
  to_accept: "Engagements du calendrier qu'on te propose, à accepter",
}

function deadlineTone(deadline: string | null, today: string): string {
  if (!deadline) return 'var(--ink-4)'
  if (deadline < today) return 'var(--err)'
  const days = (Date.parse(deadline) - Date.parse(today)) / 86_400_000
  return days < 5 ? 'var(--warn)' : 'var(--ink-3)'
}

// *prod* comes from the Hub: one production load shared with "Tes retakes".
export function MyTasks({ project, username, prod }: { project: string | null | undefined; username: string; prod: UseProductionResult }) {
  const navigate = useNavigate()
  const { t } = useI18n()
  const calendar = useShotCalendar(project || '', Boolean(project))
  const [sort, setSort] = useSessionState<MyTaskSort>('hub.myTasks.sort', 'smart')
  const [filter, setFilter] = useSessionState<TaskFilter>('hub.myTasks.filter', 'all')
  const today = new Date().toISOString().slice(0, 10)

  const tasks = useMemo(
    () => sortMyTasks(myTasks(prod.state, username, calendar.items, prod.publishesByTask), sort, username),
    [prod.state, username, calendar.items, prod.publishesByTask, sort])
  const mine = useMemo(() => {
    const who = username.trim().toLowerCase()
    const list = calendar.items.filter(it => it.status !== 'declined' && it.owner.trim().toLowerCase() === who)
    return list.sort((a, b) => Number(a.status === 'done') - Number(b.status === 'done') || a.end.localeCompare(b.end))
  }, [calendar.items, username])
  const open = tasks.filter(t => t.status !== 'APPROVED').length + mine.filter(it => it.status !== 'done').length
  const total = tasks.length + mine.length
  const showProd = filter === 'all' || filter === 'production' || filter === 'open'
  const shownTasks = !showProd ? [] : filter === 'open' ? tasks.filter(t => t.status !== 'APPROVED') : tasks
  const shownCal = filter === 'production' ? []
    : filter === 'open' ? mine.filter(it => it.status !== 'done')
    : filter === 'to_accept' ? mine.filter(it => it.status === 'proposed')
    : mine

  if (!project) return <Empty text="Choisis un projet pour voir tes tâches." />

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: 0, flex: 1 }}>
      <div style={{ padding: '7px 14px', borderBottom: '1px solid var(--rule)', display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
        <div className="cap">{t('hub.yourTasks')}</div>
        <span className="lbl" style={{ color: 'var(--ink-3)' }}>{open}{total !== open ? ` / ${total}` : ''}</span>
        <div style={{ flex: 1 }} />
        <ExpandPicker title="Afficher" value={filter} onChange={v => setFilter(v as TaskFilter)}
          options={(Object.keys(FILTER_LABEL) as TaskFilter[]).map(k => ({ value: k, label: FILTER_LABEL[k], title: FILTER_HINT[k] }))} />
        <ExpandPicker title="Trier par" value={sort} onChange={v => setSort(v as MyTaskSort)}
          options={(Object.keys(SORT_LABEL) as MyTaskSort[]).map(k => ({ value: k, label: SORT_LABEL[k],
            title: k === 'smart' ? 'Deadline du calendrier, puis priorité, puis statut'
              : k === 'concern' ? t('hub.sortConcernHint') : undefined }))} />
      </div>
      <ScrollMore>
        {prod.loading && !tasks.length && <Empty text="Chargement…" />}
        {shownCal.filter(it => it.status !== 'done').map(it => <CalendarRow key={it.id} it={it} today={today} />)}
        {!prod.loading && !tasks.length && !mine.length && (
          <Empty text={`Aucune tâche assignée à ${username} dans ${project}. Dans Production, clic droit sur un badge > Artiste > Prendre la task.`} />
        )}
        {!prod.loading && (tasks.length > 0 || mine.length > 0) && !shownTasks.length && !shownCal.length && (
          <Empty text={`Rien dans « ${FILTER_LABEL[filter]} ».`} />
        )}
        {shownTasks.map(t => {
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
        {shownCal.filter(it => it.status === 'done').map(it => <CalendarRow key={it.id} it={it} today={today} />)}
      </ScrollMore>
    </div>
  )
}

// One calendar commitment: state color, title, span, link. A click opens it in the Calendar.
function CalendarRow({ it, today }: { it: CalendarItem; today: string }) {
  const navigate = useNavigate()
  const { lang } = useI18n()
  const label = STATUS_LABEL[lang === 'en' ? 'en' : 'fr'][it.status]
  const span = it.start === it.end ? it.start : `${it.start} → ${it.end}`
  return (
    <div className="row" role="button" tabIndex={0}
      style={{ padding: '7px 14px', gap: 10, cursor: 'pointer', opacity: it.status === 'done' ? 0.55 : 1 }}
      title={`Calendrier · ${it.title} · ${label}${it.link ? ` · ${it.link}` : ''}`}
      onClick={() => navigate(`/calendar?item=${encodeURIComponent(it.id)}`)}
      onKeyDown={e => { if (e.key === 'Enter') (e.currentTarget as HTMLElement).click() }}>
      <span style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, width: 79, paddingLeft: 11 }}
        aria-label={`Calendrier · ${label}`}>
        <CalendarDays size={16} color={STATE_COLOR[it.status]} />
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 11, color: 'var(--ink)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {it.title}{it.link && <span style={{ color: 'var(--ink-3)', fontFamily: 'var(--mono)' }}> · {it.link}</span>}
        </div>
        <div className="lbl" style={{ marginTop: 2, display: 'flex', gap: 8 }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 3, color: it.status === 'done' ? 'var(--ink-4)' : deadlineTone(it.end, today) }}>
            <CalendarClock size={10} />{span}
          </span>
          <span>{label}</span>
        </div>
      </div>
    </div>
  )
}

function Empty({ text }: { text: string }) {
  return <div style={{ padding: '10px 14px', fontSize: 11, color: 'var(--ink-4)', lineHeight: 1.5 }}>{text}</div>
}
