// Render.tsx: Tractor farm render window (ADR 0015).
//
// Four tabs (pages/render/*): "Lancer" (a shot or published USD; farm share, machines and start time
// folded), "Jobs" (every Tractor job like the Dashboard, actions on FLUX jobs only), "Farm" (who uses
// the farm: blade states, team cap, per team, per room) and "Avance" (team settings in render.json).
// Backend: routers/render.py, features/render/*. Jobs poll every 15 s, the farm every 30 s (the farm
// poll also runs the team cap balancer), only while this page is mounted.

import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
import { api } from '../api/client'
import type { RenderFarm, RenderJob, RenderJobScope, RenderSettings, RenderShot } from '../api/client'
import { startAdaptivePoll } from '../lib/adaptivePoll'
import { useProject } from '../ProjectContext'
import { AdvancedTab } from './render/AdvancedTab'
import { FarmTab } from './render/FarmTab'
import { JobsTab } from './render/JobsTab'
import { LaunchTab } from './render/LaunchTab'
import { Banner, Toggle, errMsg, hint, openDir, useTr } from './render/renderUi'

const JOBS_POLL_MS = 15_000
const FARM_POLL_MS = 30_000
const TAB_KEY = 'flux.render.tab'

type Tab = 'launch' | 'jobs' | 'farm' | 'advanced'
const TABS: Tab[] = ['launch', 'jobs', 'farm', 'advanced']

function usePoll(name: string, ms: number, load: () => Promise<void>) {
  useEffect(() => {
    void load()
    const stop = startAdaptivePoll(name, ms, load)
    const onRefresh = () => { void load() }
    window.addEventListener('flux:refresh', onRefresh)
    return () => { stop(); window.removeEventListener('flux:refresh', onRefresh) }
  }, [name, ms, load])
}

export function Render() {
  const { project } = useProject()
  const { tr } = useTr()
  const [tab, setTabState] = useState<Tab>(() => {
    try { const t = localStorage.getItem(TAB_KEY) as Tab; return TABS.includes(t) ? t : 'launch' } catch { return 'launch' }
  })
  const setTab = (t: Tab) => { setTabState(t); try { localStorage.setItem(TAB_KEY, t) } catch { /* private window */ } }
  const [settings, setSettings] = useState<RenderSettings | null>(null)
  const [warning, setWarning] = useState<string | null>(null)
  const [shots, setShots] = useState<RenderShot[]>([])
  const [scope, setScope] = useState<RenderJobScope>('mine')
  const [days, setDays] = useState(30)
  const [jobs, setJobs] = useState<RenderJob[]>([])
  const [jobsDry, setJobsDry] = useState(false)
  const [farm, setFarm] = useState<RenderFarm | null>(null)

  const applySettings = useCallback((r: { settings: RenderSettings; warning: string | null }) => {
    setSettings(r.settings); setWarning(r.warning)
  }, [])

  useEffect(() => {
    if (!project) return
    let live = true
    setSettings(null)
    api.renderSettings(project).then(r => { if (live) applySettings(r) })
      .catch(e => toast.error(`${tr('Reglages de rendu indisponibles', 'Render settings unavailable')} : ${errMsg(e)}`))
    api.renderShots(project).then(r => { if (live) setShots(r.shots) }).catch(() => { if (live) setShots([]) })
    return () => { live = false }
  }, [project]) // eslint-disable-line react-hooks/exhaustive-deps

  const loadJobs = useCallback(async () => {
    if (!project) return
    try {
      const r = await api.renderJobs(project, scope, days)
      setJobs(r.jobs ?? [])
      setJobsDry(!!r.dry_run)
      for (const f of r.finished ?? []) {
        toast.success(`${tr('Rendu termine', 'Render finished')} : ${f.title}`, {
          action: f.output ? { label: tr('Ouvrir', 'Open'), onClick: () => openDir(f.output!) } : undefined,
        })
      }
    } catch (e) { toast.error(`${tr('Jobs indisponibles', 'Jobs unavailable')} : ${errMsg(e)}`) }
  }, [project, scope, days]) // eslint-disable-line react-hooks/exhaustive-deps

  const loadFarm = useCallback(async () => {
    if (!project) return
    try { setFarm(await api.renderFarm(project)) }
    catch (e) { toast.error(`${tr('Farm indisponible', 'Farm unavailable')} : ${errMsg(e)}`) }
  }, [project]) // eslint-disable-line react-hooks/exhaustive-deps

  usePoll('render-jobs', JOBS_POLL_MS, loadJobs)
  usePoll('render-farm', FARM_POLL_MS, loadFarm)

  if (!project) {
    return <div style={{ padding: 24, fontSize: 12, color: 'var(--ink-3)' }}>{tr('Ouvre un projet pour lancer un rendu.', 'Open a project to launch a render.')}</div>
  }

  const mineRunning = jobs.filter(j => j.state === 'active').length
  const tabs = [
    { id: 'launch', label: tr('Lancer', 'Launch') },
    { id: 'jobs', label: `Jobs${scope === 'mine' && mineRunning ? ` (${mineRunning})` : ''}` },
    { id: 'farm', label: farm?.counts ? tr(`Farm (${farm.counts.free} libres)`, `Farm (${farm.counts.free} free)`) : 'Farm' },
    { id: 'advanced', label: tr('Avance', 'Advanced') },
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
      <div style={{ padding: '14px 16px 0', fontSize: 15, fontWeight: 700, letterSpacing: '0.12em', color: 'var(--ink)' }}>TRACTOR</div>
      <div className="page-toolbar" style={{ gap: 6 }}>
        <Toggle value={tab} options={tabs} onChange={id => setTab(id as Tab)} />
      </div>

      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
        {settings?.dry_run && (
          <Banner>{tr(
            "Mode simulation : les jobs sont ecrits sur disque, rien n'est envoye a la farm. Les lectures (jobs, farm) sont reelles.",
            'Simulation mode: jobs are written to disk, nothing is sent to the farm. Reads (jobs, farm) are real.')}</Banner>
        )}
        {!settings ? <div style={hint}>{tr('Chargement...', 'Loading...')}</div> : (
          <>
            {tab === 'launch' && (
              <LaunchTab key={project} project={project} settings={settings} shots={shots} farm={farm}
                onSubmitted={() => { void loadJobs() }} />
            )}
            {tab === 'jobs' && (
              <JobsTab project={project} jobs={jobs} dryRun={jobsDry} scope={scope} setScope={setScope}
                days={days} setDays={setDays} reload={() => { void loadJobs() }} />
            )}
            {tab === 'farm' && <FarmTab farm={farm} />}
            {tab === 'advanced' && (
              <AdvancedTab project={project} settings={settings} warning={warning} farm={farm}
                onSaved={r => { applySettings(r); void loadFarm() }} />
            )}
          </>
        )}
      </div>
    </div>
  )
}
