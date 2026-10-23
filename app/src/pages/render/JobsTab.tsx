// JobsTab.tsx: every Tractor job like the Dashboard (all / team / my FLUX jobs, any state),
// tasks and logs; pause, retry, kill only on FLUX jobs (the backend checks the user too).

import { useMemo, useState } from 'react'
import { toast } from 'sonner'
import { ChevronDown, ChevronRight, FolderOpen, MoreHorizontal, Pause, Pin, Play, RotateCcw, ScanSearch, Square } from 'lucide-react'
import { api } from '../../api/client'
import type { RenderJob, RenderJobAction, RenderJobScope, RenderTask } from '../../api/client'
import { JobMenu } from './JobMenu'
import type { JobMenuChoice } from './JobMenu'
import {
  Banner, Toggle, STATE_COLOR, btn, card, errMsg, hint, openDir, jobOutput, shortDate, stateLabel, useTr,
} from './renderUi'

type StateFilter = 'all' | 'active' | 'error' | 'done' | 'paused' | 'waiting'
const TASK_ERROR = 'error'
const PIN_KEY = 'flux.render.pinnedJobs'

export function JobsTab({ project, jobs, dryRun, scope, setScope, days, setDays, reload }: {
  project: string; jobs: RenderJob[]; dryRun: boolean
  scope: RenderJobScope; setScope: (s: RenderJobScope) => void
  days: number; setDays: (d: number) => void; reload: () => void
}) {
  const { tr } = useTr()
  const [stateFilter, setStateFilter] = useState<StateFilter>('all')
  const [openJid, setOpenJid] = useState<number | null>(null)
  const [tasks, setTasks] = useState<RenderTask[]>([])
  const [logOf, setLogOf] = useState<{ tid: number; text: string } | null>(null)

  const shownJobsUnpinned = useMemo(
    () => (stateFilter === 'all' ? jobs : jobs.filter(j => j.state === stateFilter)), [jobs, stateFilter])

  const toggleJob = async (jid: number) => {
    setLogOf(null)
    if (openJid === jid) { setOpenJid(null); return }
    setOpenJid(jid); setTasks([])
    try { setTasks((await api.renderJobTasks(project, jid)).tasks ?? []) }
    catch (e) { toast.error(`${tr('Taches indisponibles', 'Tasks unavailable')} : ${errMsg(e)}`) }
  }
  const showLog = async (jid: number, tid: number) => {
    if (logOf?.tid === tid) { setLogOf(null); return }
    setLogOf({ tid, text: tr('Chargement du log...', 'Loading log...') })
    try { setLogOf({ tid, text: (await api.renderTaskLog(project, jid, tid)).log || tr('(log vide)', '(empty log)') }) }
    catch (e) { setLogOf({ tid, text: errMsg(e) }) }
  }
  // Confirmation for what cannot be undone from FLUX (archive can: "Restaurer" in its toast).
  const CONFIRM: Partial<Record<RenderJobAction, (t: string) => string>> = {
    kill: t => tr(`Arreter le job "${t}" ?`, `Kill job "${t}"?`),
    restart: t => tr(`Redemarrer "${t}" ? Toutes les taches repartent de zero (images refaites).`, `Restart "${t}"? Every task runs again.`),
    skip_errors: t => tr(`Ignorer les taches en erreur de "${t}" ? Leurs images manqueront.`, `Skip error tasks of "${t}"? Their frames will be missing.`),
    archive: t => tr(`Archiver "${t}" ? Il disparait de la liste (restaurable).`, `Archive "${t}"? It leaves the list (can be restored).`),
  }
  const DONE: Partial<Record<RenderJobAction, string>> = {
    skip_errors: tr('Erreurs ignorees', 'Errors skipped'), restart: tr('Job redemarre', 'Job restarted'),
    shuffle_top: tr('Job en tete de file', 'Job moved to top'), lock: tr('Job verrouille', 'Job locked'),
    unlock: tr('Job deverrouille', 'Job unlocked'), restore: tr('Job restaure', 'Job restored'),
  }
  const jobAction = async (j: RenderJob, action: RenderJobAction) => {
    const ask = CONFIRM[action]
    if (ask && !window.confirm(ask(j.title))) return
    try {
      await api.renderJobAction(project, j.jid, action)
      if (action === 'archive') {
        toast.success(tr(`"${j.title}" archive`, `"${j.title}" archived`), {
          action: { label: tr('Restaurer', 'Restore'), onClick: () => void jobAction(j, 'restore') },
        })
      } else if (DONE[action]) toast.success(DONE[action]!)
      reload()
    } catch (e) { toast.error(errMsg(e)) }
  }

  // Pinned jobs stay on top (this viewer only, like the Dashboard's pin).
  const [pinned, setPinned] = useState<number[]>(() => {
    try { return JSON.parse(localStorage.getItem(PIN_KEY) || '[]') } catch { return [] }
  })
  const setPin = (jid: number, on: boolean) => {
    const next = on ? [...new Set([...pinned, jid])] : pinned.filter(x => x !== jid)
    setPinned(next)
    try { localStorage.setItem(PIN_KEY, JSON.stringify(next)) } catch { /* private window */ }
  }
  const [menu, setMenu] = useState<{ job: RenderJob; x: number; y: number } | null>(null)
  const [traceOf, setTraceOf] = useState<{ jid: number; text: string } | null>(null)
  const showTrace = async (jid: number) => {
    setTraceOf({ jid, text: tr('Chargement de la trace...', 'Loading trace...') })
    try { setTraceOf({ jid, text: (await api.renderJobTrace(project, jid)).trace || tr('(trace vide)', '(empty trace)') }) }
    catch (e) { setTraceOf({ jid, text: errMsg(e) }) }
  }
  const pick = (j: RenderJob, choice: JobMenuChoice) => {
    if (choice === 'trace') void showTrace(j.jid)
    else if (choice === 'pin' || choice === 'unpin') setPin(j.jid, choice === 'pin')
    else void jobAction(j, choice)
  }
  const shownJobs = useMemo(() => [
    ...shownJobsUnpinned.filter(j => pinned.includes(j.jid)),
    ...shownJobsUnpinned.filter(j => !pinned.includes(j.jid)),
  ], [shownJobsUnpinned, pinned])

  return (
    <>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
        <Toggle value={scope} onChange={id => setScope(id as RenderJobScope)}
          options={[{ id: 'all', label: tr('Toute la farm', 'Whole farm') }, { id: 'team', label: tr('Equipe', 'Team') },
            { id: 'mine', label: tr('Mes jobs FLUX', 'My FLUX jobs') }]} />
        <Toggle value={stateFilter} onChange={id => setStateFilter(id as StateFilter)}
          options={[{ id: 'all', label: tr('Tous etats', 'Any state') }, { id: 'active', label: tr('En cours', 'Running') },
            { id: 'error', label: tr('Erreur', 'Error') }, { id: 'done', label: tr('Fini', 'Done') },
            { id: 'paused', label: 'Pause' }, { id: 'waiting', label: tr('En attente', 'Waiting') }]} />
        <Toggle value={String(days)} onChange={id => setDays(Number(id))}
          options={[{ id: '7', label: tr('7 j', '7 d') }, { id: '30', label: tr('30 j', '30 d') }, { id: '90', label: tr('90 j', '90 d') }]} />
      </div>
      {dryRun && jobs.length > 0 && (
        <Banner>{tr('Simulation : actions bloquees', 'Simulation: actions blocked')}</Banner>
      )}
      {shownJobs.length === 0 ? (
        <div style={{ fontSize: 12, color: 'var(--ink-3)' }}>
          {dryRun && jobs.length === 0 ? tr('Mode simulation : pont Tractor non configure', 'Simulation mode: Tractor bridge not configured') : tr('Aucun job.', 'No jobs.')}
        </div>
      ) : (
        <div style={{ ...card, padding: 0, overflow: 'hidden' }}>
          {shownJobs.map(j => {
            const pct = j.percent ?? (j.numTasks > 0 ? Math.round((j.numDone / j.numTasks) * 100) : 0)
            const out = jobOutput(j)
            const state = j.state ?? 'waiting'
            const projects = Array.isArray(j.projects) ? j.projects.join(', ') : (j.projects ?? '')
            const open = openJid === j.jid
            // Blades rendering now; the job maximum only in the tooltip ("0/1" on a finished job read as wrong, the maintainer).
            const runningTitle = `${tr('Blades en cours', 'Running blades')}${j.maxactive ? ` (${tr('max', 'max')} ${j.maxactive})` : ''}`
            return (
              <div key={j.jid} style={{ borderBottom: '1px solid var(--rule-2)' }}>
                {/* The whole row folds / unfolds the tasks; the action buttons stop the click. */}
                <div onClick={() => void toggleJob(j.jid)}
                  onContextMenu={e => { e.preventDefault(); setMenu({ job: j, x: e.clientX, y: e.clientY }) }}
                  style={{ display: 'grid', gridTemplateColumns: 'minmax(120px,2fr) 80px 60px 70px minmax(90px,1.2fr) 50px 50px 80px auto', gap: 10, alignItems: 'center', padding: '8px 12px', fontSize: 11.5, color: 'var(--ink)', cursor: 'pointer' }}>
                  <button type="button" title={`${j.jid} ${j.title}`}
                    style={{ display: 'flex', alignItems: 'center', gap: 4, minWidth: 0, background: 'none', border: 'none', padding: 0, cursor: 'pointer', color: 'var(--ink)', fontSize: 11.5, fontFamily: 'var(--sans)', textAlign: 'left' }}>
                    {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                    {pinned.includes(j.jid) && <Pin size={11} style={{ color: 'var(--accent)', flexShrink: 0 }} />}
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{j.title}</span>
                  </button>
                  <div style={{ color: 'var(--ink-3)', overflow: 'hidden', textOverflow: 'ellipsis' }} title={j.user}>{j.flux_user || j.user}</div>
                  <div style={{ color: 'var(--ink-3)', overflow: 'hidden', textOverflow: 'ellipsis' }} title={projects}>{projects}</div>
                  <div style={{ color: STATE_COLOR[state] ?? 'var(--ink-3)', fontWeight: 600 }}>{stateLabel(state, tr)}</div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <div style={{ flex: 1, height: 6, borderRadius: 3, background: 'var(--rule-2)', overflow: 'hidden' }}>
                      <div style={{ width: `${pct}%`, height: '100%', background: 'var(--accent)' }} />
                    </div>
                    <span style={{ color: 'var(--ink-3)', minWidth: 28 }}>{pct}%</span>
                  </div>
                  <div style={{ color: 'var(--ink-3)' }} title={runningTitle}>{j.numActive}</div>
                  <div style={{ color: 'var(--err)' }} title={tr('Taches en erreur', 'Tasks in error')}>{j.numError > 0 ? `${j.numError} ${tr('err.', 'err.')}` : ''}</div>
                  <div style={{ color: 'var(--ink-3)' }} title={String(j.spooltime ?? '')}>{shortDate(j.spooltime)}</div>
                  <div style={{ display: 'flex', gap: 4, justifyContent: 'flex-end' }} onClick={e => e.stopPropagation()}>
                    {/* Actions only on FLUX jobs that can still change (never on a finished or deleted job). */}
                    {j.flux_user && state !== 'done' && state !== 'deleted' && <>
                      {state === 'paused'
                        ? <button type="button" style={btn()} title={tr('Reprendre', 'Resume')} onClick={() => void jobAction(j, 'resume')}><Play size={11} /></button>
                        : <button type="button" style={btn()} title="Pause" onClick={() => void jobAction(j, 'pause')}><Pause size={11} /></button>}
                      {j.numError > 0 && <button type="button" style={btn()} title={tr('Relancer les erreurs', 'Retry errors')} onClick={() => void jobAction(j, 'retry')}><RotateCcw size={11} /></button>}
                      <button type="button" style={btn(false, true)} title={tr('Arreter', 'Kill')} onClick={() => void jobAction(j, 'kill')}><Square size={11} /></button>
                    </>}
                    {out && <button type="button" style={btn()} title={tr('Ouvrir le dossier', 'Open folder')} onClick={() => openDir(out)}><FolderOpen size={11} /></button>}
                    <button type="button" style={btn()} title={tr('Autres actions (ou clic droit)', 'More actions (or right click)')}
                      onClick={e => { const r = e.currentTarget.getBoundingClientRect(); setMenu({ job: j, x: r.right - 220, y: r.bottom + 4 }) }}>
                      <MoreHorizontal size={11} />
                    </button>
                  </div>
                </div>
                {traceOf?.jid === j.jid && (
                  <div style={{ padding: '0 12px 10px 28px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11, color: 'var(--ink-2)', marginBottom: 4 }}>
                      <ScanSearch size={12} />{tr('Trace du moteur', 'Engine trace')}
                      <button type="button" style={btn()} onClick={() => setTraceOf(null)}>{tr('Fermer', 'Close')}</button>
                    </div>
                    <pre style={{ margin: 0, padding: 8, maxHeight: 260, overflow: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-all', fontSize: 10.5, background: 'var(--paper)', border: '1px solid var(--rule-2)', borderRadius: 6, color: 'var(--ink)' }}>{traceOf.text}</pre>
                  </div>
                )}
                {open && (
                  <div style={{ padding: '4px 12px 10px 28px', fontSize: 11, color: 'var(--ink-2)' }}>
                    {j.comment && <div style={{ ...hint, marginBottom: 4 }}>{j.comment}</div>}
                    {tasks.length === 0 && <div style={hint}>{tr('Chargement des taches...', 'Loading tasks...')}</div>}
                    {tasks.map(t => (
                      <div key={t.tid}>
                        <div onClick={() => void showLog(j.jid, t.tid)} style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '2px 0', cursor: 'pointer' }}>
                          <span style={{ width: 60, color: t.state === TASK_ERROR ? 'var(--err)' : 'var(--ink-3)' }}>{t.state}</span>
                          <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={t.title}>{t.title}</span>
                          {t.state === 'active' && typeof t.progress === 'number' && (
                            <span style={{ color: 'var(--ink-3)', minWidth: 32, textAlign: 'right' }}>{Math.round(t.progress)}%</span>
                          )}
                          <button type="button" style={btn()}>Log</button>
                        </div>
                        {logOf?.tid === t.tid && (
                          <pre style={{ margin: '4px 0 8px', padding: 8, maxHeight: 260, overflow: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-all', fontSize: 10.5, background: 'var(--paper)', border: '1px solid var(--rule-2)', borderRadius: 6, color: 'var(--ink)' }}>{logOf.text}</pre>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
      {menu && (
        <JobMenu job={menu.job} pinned={pinned.includes(menu.job.jid)} x={menu.x} y={menu.y}
          onPick={c => pick(menu.job, c)} onClose={() => setMenu(null)} />
      )}
    </>
  )
}
