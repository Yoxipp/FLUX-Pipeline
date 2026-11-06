// ShareSummary.tsx: farm use per team against the engine's Shares (engine limits.config, husk tag), and the
// teams outside the Shares grouped as "default". Read only, an estimate: Tractor decides at each dispatch.
// A team above its part gives blades back as its running tasks end (nothing is killed); the jobs listed
// are the ones whose next task ends free those blades.

import { useEffect, useMemo, useState } from 'react'
import { api } from '../../api/client'
import type { RenderFarm, RenderJob, RenderShareRule } from '../../api/client'
import { Bar, Section, hint, useTr, warnText } from './renderUi'

const DEFAULT_SHARE = 'default'
const DONE = new Set(['done', 'deleted', 'paused'])

function projectsOf(j: RenderJob): string[] {
  return Array.isArray(j.projects) ? j.projects : j.projects ? [j.projects] : []
}

type Row = {
  name: string; used: number; nominal: number; cap: number; pending: number
  members: string[]; jobs: { title: string; active: number }[]
}

export function ShareSummary({ farm, project, shares }: {
  farm: RenderFarm; project: string; shares: Record<string, RenderShareRule> | null
}) {
  const { tr } = useTr()
  const [jobs, setJobs] = useState<RenderJob[]>([])
  useEffect(() => {
    let live = true
    api.renderJobs(project, 'all', 7).then(r => { if (live) setJobs(r.jobs ?? []) }).catch(() => { /* summary without queue */ })
    return () => { live = false }
  }, [project, farm])

  const pool = (farm.counts.free ?? 0) + (farm.counts.busy ?? 0)   // usable blades now (NIMBY and off excluded)
  const rows = useMemo<Row[]>(() => {
    if (!shares) return []
    const named = Object.keys(shares).filter(t => t !== DEFAULT_SHARE).sort()
    const groupOf = (p: string) => (named.includes(p) ? p : DEFAULT_SHARE)
    const make = (name: string): Row => {
      const r = shares[name] ?? { nominal: 0, cap: 0 }
      return { name, used: 0, nominal: Math.round((r.nominal ?? 0) * pool), cap: Math.floor((r.cap ?? 0) * pool),
        pending: 0, members: [], jobs: [] }
    }
    const out: Record<string, Row> = Object.fromEntries([...named, DEFAULT_SHARE].map(n => [n, make(n)]))
    for (const [p, n] of Object.entries(farm.active_by_project)) {
      const row = out[groupOf(p)]
      row.used += n
      if (row.name === DEFAULT_SHARE && !row.members.includes(p)) row.members.push(p)
    }
    for (const j of jobs) {
      if (DONE.has(j.state ?? '')) continue
      const p = projectsOf(j)[0] ?? ''
      const row = out[groupOf(p)]
      row.pending += Math.max(0, j.numTasks - j.numDone - j.numActive - (j.numError ?? 0))
      if (j.numActive > 0) row.jobs.push({ title: j.title, active: j.numActive })
    }
    return Object.values(out)
  }, [shares, farm, jobs, pool])

  if (!shares) {
    return <Section title={tr('Parts de la farm', 'Farm shares')}><div style={hint}>{tr("Parts de la farm inconnues : moteur injoignable, ou FLUX a relancer apres une mise a jour",
      'Farm shares unknown: engine unreachable, or FLUX to restart after an update')}</div></Section>
  }
  const waiting = (except: string) => rows.some(r => r.name !== except && r.pending > 0)

  return (
    <Section title={tr(`Parts de la farm (${pool} PC utilisables)`, `Farm shares (${pool} usable PCs)`)}>
      {rows.map(r => {
        const max = Math.max(r.cap, r.nominal, r.used, 1)
        const over = r.used > r.nominal && waiting(r.name)
        const capped = r.cap > 0 && r.used >= r.cap
        let state = r.pending > 0 || r.used > 0 ? tr('dans sa part', 'within its share') : tr('rien en cours', 'idle')
        if (capped) state = tr(`au plafond (${r.cap})`, `at its cap (${r.cap})`)
        else if (over) state = tr(`au-dessus : rend ~${r.used - r.nominal} PC au fil des fins de taches`, `above: gives ~${r.used - r.nominal} PCs back as tasks end`)
        else if (r.used < r.nominal && r.pending > 0) state = tr('sous sa part : recupere des PC des que des taches finissent ailleurs', 'below: gets PCs as tasks end elsewhere')
        const label = r.name === DEFAULT_SHARE ? tr('Autres (default)', 'Others (default)') : r.name
        return (
          <div key={r.name} style={{ display: 'flex', flexDirection: 'column', gap: 3, fontSize: 11.5 }}>
            <div style={{ display: 'grid', gridTemplateColumns: '140px 1fr 150px', gap: 10, alignItems: 'center' }}>
              <div style={{ color: 'var(--ink-2)', fontWeight: r.name === farm.tractor_project ? 700 : undefined }}>{label}</div>
              <Bar value={r.used} max={max} color={capped || over ? 'var(--warn)' : 'var(--accent)'} />
              <div style={{ color: 'var(--ink-3)', textAlign: 'right' }}>
                {r.used} / {r.nominal} {tr('(max', '(max')} {r.cap}) · {r.pending} {tr('en attente', 'waiting')}
              </div>
            </div>
            <div style={over || capped ? warnText : hint}>{state}</div>
            {r.name === DEFAULT_SHARE && r.members.length > 0 && <div style={hint}>{r.members.join(', ')}</div>}
            {over && r.jobs.length > 0 && (
              <div style={hint}>{tr('PC rendus par : ', 'PCs given back by: ')}{r.jobs.slice(0, 4).map(j => `${j.title} (${j.active})`).join(', ')}</div>
            )}
          </div>
        )
      })}
      <div style={hint}>{tr('Estimation : utilises / part nominale (max = plafond). Tractor decide a chaque tache, rien n\'est tue.',
        'Estimate: used / nominal share (max = cap). Tractor decides at each task, nothing is killed.')}</div>
    </Section>
  )
}
