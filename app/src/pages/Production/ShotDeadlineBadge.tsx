import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import type { CalendarItem, ProductionShot, ProductionState } from '../../types'
import { shotDeadline } from './shotCalendar'

export function useShotCalendar(project: string, enabled: boolean) {
  const [calendar, setCalendar] = useState<{ project: string; items: CalendarItem[]; now: Date; ready: boolean }>({ project: '', items: [], now: new Date(), ready: false })
  useEffect(() => {
    if (!enabled) return
    let alive = true
    const load = () => {
      void api.getCalendar(project).then(r => {
        if (alive) setCalendar({ project, items: r.items, now: new Date(), ready: true })
      }).catch(() => { if (alive) setCalendar({ project, items: [], now: new Date(), ready: false }) })
    }
    load()
    const timer = setInterval(load, 30_000)
    window.addEventListener('focus', load)
    window.addEventListener('flux:refresh', load)
    return () => { alive = false; clearInterval(timer); window.removeEventListener('focus', load); window.removeEventListener('flux:refresh', load) }
  }, [project, enabled])
  return calendar.project === project ? calendar : { items: [], now: new Date(), ready: false }
}

export function ShotDeadlineBadge({ state, shot, calendar }: { state: ProductionState; shot: ProductionShot; calendar: ReturnType<typeof useShotCalendar> }) {
  const status = calendar.ready ? shotDeadline(state, shot, calendar.items, calendar.now) : null
  return <span className="tracking-deadline" data-deadline={status ?? 'None'} title={status ? 'Échéance du calendrier · ' + status : 'Calendrier en cours de chargement ou indisponible'}>{status ?? '…'}</span>
}
