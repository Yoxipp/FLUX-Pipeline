// Render.tsx: Tractor farm render (ADR 0015).
//
// Three tabs: "Lancer" (submit a shot or a published USD, advanced team settings folded
// under it), "Jobs" (mine / team, pause, retry, kill) and "Occupation" (who uses the farm).
// Backend: routers/render.py, features/render/*. Jobs poll every 15 s, the farm every 30 s,
// only while the page is mounted.

import { useCallback, useEffect, useMemo, useState } from 'react'
import type { CSSProperties } from 'react'
import { toast } from 'sonner'
import { ChevronDown, ChevronRight, FolderOpen, Pause, Play, RotateCcw, Square } from 'lucide-react'
import { api } from '../api/client'
import type { RenderFarm, RenderJob, RenderSettings, RenderShot, RenderSubmitResult } from '../api/client'
import { startAdaptivePoll } from '../lib/adaptivePoll'
import { useProject } from '../ProjectContext'
import { useI18n } from '../i18n'
import { Select, SelectContent, SelectItem, SelectTrigger } from '../components/shared/ui'

const JOBS_POLL_MS = 15_000
const FARM_POLL_MS = 30_000
const ADV_KEY = 'flux.render.advanced'

type Tab = 'launch' | 'jobs' | 'farm'

function useTr() {
  const { lang } = useI18n()
  return { tr: (fr: string, en: string) => (lang === 'en' ? en : fr) }
}

const errMsg = (e: unknown) => (e instanceof Error ? e.message : String(e))

const btn = (primary = false, danger = false): CSSProperties => ({
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 5, padding: '5px 10px', fontSize: 11,
  borderRadius: 6, cursor: 'pointer', fontFamily: 'var(--sans)',
  border: `1px solid ${danger ? 'var(--err)' : primary ? 'var(--accent)' : 'var(--rule-2)'}`,
  background: primary && !danger ? 'var(--accent)' : 'var(--paper-2)',
  fontWeight: primary && !danger ? 700 : undefined,
  color: danger ? 'var(--err)' : primary ? 'var(--on-accent)' : 'var(--accent-hi)',
})
const input: CSSProperties = {
  width: '100%', boxSizing: 'border-box', padding: '5px 8px', fontSize: 11.5, borderRadius: 6,
  border: '1px solid var(--rule-2)', background: 'var(--paper-2)', color: 'var(--ink)', outline: 'none',
  fontFamily: 'var(--sans)',
}
const lbl: CSSProperties = { fontSize: 11, letterSpacing: 0.6, textTransform: 'uppercase', color: 'var(--ink-3)', marginBottom: 4 }
const card: CSSProperties = {
  border: '1px solid var(--rule-2)', borderRadius: 6, background: 'var(--paper-2)', boxShadow: 'var(--shadow-xs)', padding: 12,
}
const sel: CSSProperties = { width: '100%' }

const dirname = (p: string) => p.replace(/[\\/][^\\/]*$/, '')
const openFolder = (p: string) => { if (p) void window.electronAPI?.openPath?.(dirname(p)) }
// Render output paths are folders (<shot>/render/vNNN): open them as is.
const openDir = (p: string) => { if (p) void window.electronAPI?.openPath?.(p) }

// Job metadata can be an object or a JSON string; the output path lives in it.
function jobOutput(j: RenderJob): string {
  let m: unknown = j.metadata
  if (typeof m === 'string') { try { m = JSON.parse(m) } catch { m = null } }
  const o = (m as { output?: unknown } | null)?.output
  return typeof o === 'string' ? o : ''
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return <div><div style={lbl}>{label}</div>{children}</div>
}

function Toggle({ value, options, onChange }: {
  value: string; options: { id: string; label: string }[]; onChange: (id: string) => void
}) {
  return (
    <div style={{ display: 'inline-flex', gap: 4 }}>
      {options.map(o => (
        <button key={o.id} type="button" onClick={() => onChange(o.id)}
          style={{ ...btn(), background: value === o.id ? 'var(--accent-soft)' : 'var(--paper-2)', borderColor: value === o.id ? 'var(--rule-3)' : 'var(--rule-2)' }}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

function Banner({ children, color = 'var(--ink-2)' }: { children: React.ReactNode; color?: string }) {
  return (
    <div style={{ padding: '6px 10px', fontSize: 11.5, borderRadius: 6, border: '1px solid var(--rule-2)', background: 'var(--paper-2)', color }}>
      {children}
    </div>
  )
}

// ── Advanced settings draft (strings for the inputs, converted on save) ─────────────
interface Draft {
  tractor_project: string; priority: string; maxactive: string; chunk_size: string
  sch_enabled: boolean; sch_start: string; sch_end: string; sch_kill: boolean
  service_karma: string; service_renderman: string; envkeys: string
  husk_path: string; bridge_python: string; bridge_script: string; engine: string; dry_run: boolean
}
const toDraft = (s: RenderSettings): Draft => ({
  tractor_project: s.tractor_project, priority: String(s.priority), maxactive: String(s.maxactive), chunk_size: String(s.chunk_size),
  sch_enabled: s.schedule.enabled, sch_start: s.schedule.start, sch_end: s.schedule.end, sch_kill: s.schedule.kill_at_end,
  service_karma: s.service_karma, service_renderman: s.service_renderman, envkeys: s.envkeys.join(', '),
  husk_path: s.husk_path, bridge_python: s.bridge_python, bridge_script: s.bridge_script, engine: s.engine, dry_run: s.dry_run,
})
function diffPatch(s: RenderSettings, d: Draft): Partial<RenderSettings> {
  const base = toDraft(s)
  const p: Record<string, unknown> = {}
  const num = (k: 'priority' | 'maxactive' | 'chunk_size') => { if (d[k] !== base[k]) p[k] = Number(d[k]) }
  const txt = (k: 'tractor_project' | 'service_karma' | 'service_renderman' | 'husk_path' | 'bridge_python' | 'bridge_script' | 'engine') => {
    if (d[k] !== base[k]) p[k] = d[k].trim()
  }
  num('priority'); num('maxactive'); num('chunk_size')
  ;(['tractor_project', 'service_karma', 'service_renderman', 'husk_path', 'bridge_python', 'bridge_script', 'engine'] as const).forEach(txt)
  if (d.envkeys !== base.envkeys) p.envkeys = d.envkeys.split(',').map(x => x.trim()).filter(Boolean)
  if (d.dry_run !== base.dry_run) p.dry_run = d.dry_run
  const sch: Record<string, unknown> = {}
  if (d.sch_enabled !== base.sch_enabled) sch.enabled = d.sch_enabled
  if (d.sch_start !== base.sch_start) sch.start = d.sch_start.trim()
  if (d.sch_end !== base.sch_end) sch.end = d.sch_end.trim()
  if (d.sch_kill !== base.sch_kill) sch.kill_at_end = d.sch_kill
  if (Object.keys(sch).length) p.schedule = sch
  return p as Partial<RenderSettings>
}

export function Render() {
  const { project } = useProject()
  const { tr } = useTr()
  const [tab, setTab] = useState<Tab>('launch')
  const [settings, setSettings] = useState<RenderSettings | null>(null)
  const [settingsWarning, setSettingsWarning] = useState<string | null>(null)
  const [shots, setShots] = useState<RenderShot[]>([])

  // launch form
  const [source, setSource] = useState<'shot' | 'usd'>('shot')
  const [shotKey, setShotKey] = useState('')
  const [usdPath, setUsdPath] = useState('')
  const [frameStart, setFrameStart] = useState('')
  const [frameEnd, setFrameEnd] = useState('')
  const [renderer, setRenderer] = useState<'karma' | 'renderman'>('karma')
  const [freeze, setFreeze] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<RenderSubmitResult | null>(null)

  // advanced
  const [advOpen, setAdvOpen] = useState(() => { try { return localStorage.getItem(ADV_KEY) === '1' } catch { return false } })
  const [draft, setDraft] = useState<Draft | null>(null)
  const [saving, setSaving] = useState(false)

  // jobs / farm
  const [mine, setMine] = useState(true)
  const [jobs, setJobs] = useState<RenderJob[]>([])
  const [jobsDry, setJobsDry] = useState(false)
  const [farm, setFarm] = useState<RenderFarm | null>(null)

  const applySettings = useCallback((r: { settings: RenderSettings; warning: string | null }, first: boolean) => {
    setSettings(r.settings)
    setSettingsWarning(r.warning)
    setDraft(toDraft(r.settings))
    if (first) { setRenderer(r.settings.renderer); setFreeze(r.settings.freeze_by_default) }
  }, [])

  useEffect(() => {
    if (!project) return
    let live = true
    api.renderSettings(project).then(r => { if (live) applySettings(r, true) })
      .catch(e => toast.error(`${tr('Reglages de rendu indisponibles', 'Render settings unavailable')} : ${errMsg(e)}`))
    api.renderShots(project).then(r => { if (live) setShots(r.shots) }).catch(() => { if (live) setShots([]) })
    return () => { live = false }
  }, [project]) // eslint-disable-line react-hooks/exhaustive-deps

  const loadJobs = useCallback(async () => {
    if (!project) return
    try {
      const r = await api.renderJobs(project, mine)
      setJobs(r.jobs ?? [])
      setJobsDry(!!r.dry_run)
      for (const f of r.finished ?? []) {
        toast.success(`${tr('Rendu termine', 'Render finished')} : ${f.title}`, {
          action: f.output ? { label: tr('Ouvrir', 'Open'), onClick: () => openDir(f.output!) } : undefined,
        })
      }
    } catch (e) { toast.error(`${tr('Jobs indisponibles', 'Jobs unavailable')} : ${errMsg(e)}`) }
  }, [project, mine]) // eslint-disable-line react-hooks/exhaustive-deps

  const loadFarm = useCallback(async () => {
    if (!project) return
    try { setFarm(await api.renderFarm(project)) }
    catch (e) { toast.error(`${tr('Farm indisponible', 'Farm unavailable')} : ${errMsg(e)}`) }
  }, [project]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    void loadJobs()
    const stop = startAdaptivePoll('render-jobs', JOBS_POLL_MS, async () => { await loadJobs() })
    const onRefresh = () => { void loadJobs() }
    window.addEventListener('flux:refresh', onRefresh)
    return () => { stop(); window.removeEventListener('flux:refresh', onRefresh) }
  }, [loadJobs])
  useEffect(() => {
    void loadFarm()
    const stop = startAdaptivePoll('render-farm', FARM_POLL_MS, async () => { await loadFarm() })
    const onRefresh = () => { void loadFarm() }
    window.addEventListener('flux:refresh', onRefresh)
    return () => { stop(); window.removeEventListener('flux:refresh', onRefresh) }
  }, [loadFarm])

  const shotId = (s: RenderShot) => `${s.seq}/${s.shot}`
  const pickShot = (id: string) => {
    setShotKey(id)
    const s = shots.find(x => shotId(x) === id)
    if (s) { setFrameStart(String(s.frame_start)); setFrameEnd(String(s.frame_end)) }
  }

  const browseUsd = async () => {
    const p = await window.electronAPI?.openFile?.([{ name: 'USD', extensions: ['usd', 'usda', 'usdc'] }])
    if (p) setUsdPath(p)
  }

  const canSubmit = !submitting && (source === 'shot' ? !!shotKey : !!usdPath.trim())
  const submit = async () => {
    if (!project || !canSubmit) return
    const body: Parameters<typeof api.renderSubmit>[0] = { project, renderer, freeze }
    if (source === 'shot') { const [seq, shot] = shotKey.split('/'); body.seq = seq; body.shot = shot }
    else body.usd_path = usdPath.trim()
    if (frameStart !== '') body.frame_start = Number(frameStart)
    if (frameEnd !== '') body.frame_end = Number(frameEnd)
    setSubmitting(true)
    try {
      const r = await api.renderSubmit(body)
      setResult(r)
      if (r.dry_run) {
        toast.success(tr("Simulation : job ecrit, rien n'est envoye a la farm", 'Simulation: job written, nothing sent to the farm'), {
          action: { label: tr('Ouvrir le dossier', 'Open folder'), onClick: () => openFolder(r.files.alf) },
        })
      } else toast.success(`${tr('Job envoye', 'Job sent')} (jid ${r.jid})`)
      void loadJobs()
    } catch (e) { toast.error(errMsg(e)) }
    finally { setSubmitting(false) }
  }

  const jobAction = async (j: RenderJob, action: 'kill' | 'retry' | 'pause' | 'resume') => {
    if (!project) return
    if (action === 'kill' && !window.confirm(tr(`Arreter le job "${j.title}" ?`, `Kill job "${j.title}"?`))) return
    try { await api.renderJobAction(project, j.jid, action); void loadJobs() }
    catch (e) { toast.error(errMsg(e)) }
  }

  const toggleAdv = () => {
    setAdvOpen(o => { try { localStorage.setItem(ADV_KEY, o ? '0' : '1') } catch { /* private window */ } return !o })
  }

  const patch = useMemo(() => (settings && draft ? diffPatch(settings, draft) : {}), [settings, draft])
  const saveAdvanced = async () => {
    if (!project || !Object.keys(patch).length) return
    setSaving(true)
    try {
      applySettings(await api.renderSaveSettings(project, patch), false)
      toast.success(tr('Reglages enregistres', 'Settings saved'))
      void loadFarm()
    } catch (e) { toast.error(errMsg(e)) }
    finally { setSaving(false) }
  }
  const setD = <K extends keyof Draft>(k: K, v: Draft[K]) => setDraft(d => (d ? { ...d, [k]: v } : d))

  if (!project) {
    return <div style={{ padding: 24, fontSize: 12, color: 'var(--ink-3)' }}>{tr('Ouvre un projet pour lancer un rendu.', 'Open a project to launch a render.')}</div>
  }

  const tabs: { id: Tab; label: string }[] = [
    { id: 'launch', label: tr('Lancer', 'Launch') }, { id: 'jobs', label: 'Jobs' }, { id: 'farm', label: tr('Occupation', 'Usage') },
  ]
  const txtField = (label: string, k: keyof Draft, placeholder?: string) => (
    <Row label={label}>
      <input style={input} value={draft ? String(draft[k]) : ''} placeholder={placeholder} onChange={e => setD(k, e.target.value as never)} />
    </Row>
  )
  const chk = (label: string, k: 'sch_enabled' | 'sch_kill' | 'dry_run') => (
    <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11.5, color: 'var(--ink-2)', cursor: 'pointer' }}>
      <input type="checkbox" checked={!!draft?.[k]} onChange={e => setD(k, e.target.checked)} />{label}
    </label>
  )

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
      <div className="page-toolbar" style={{ gap: 6 }}>
        <Toggle value={tab} options={tabs} onChange={id => setTab(id as Tab)} />
      </div>

      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
        {settings?.dry_run && (
          <Banner>{tr(
            "Mode simulation : la farm n'est pas encore configuree (phase 0). Les jobs sont ecrits, pas envoyes.",
            'Simulation mode: the farm is not configured yet (phase 0). Jobs are written, not sent.')}</Banner>
        )}

        {tab === 'launch' && (
          <>
            <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 640 }}>
              <div style={lbl}>{tr('Lancer un rendu', 'Launch a render')}</div>
              <Toggle value={source} onChange={id => setSource(id as 'shot' | 'usd')}
                options={[{ id: 'shot', label: 'Shot' }, { id: 'usd', label: tr('USD publie', 'Published USD') }]} />

              {source === 'shot' ? (
                <Row label="Shot">
                  <Select value={shotKey} onValueChange={pickShot}>
                    <SelectTrigger style={sel}>{!shotKey && <span style={{ color: 'var(--ink-3)' }}>{tr('Choisir un shot', 'Pick a shot')}</span>}</SelectTrigger>
                    <SelectContent>
                      {shots.map(s => (
                        <SelectItem key={shotId(s)} value={shotId(s)} disabled={!s.has_stage}>
                          {s.seq} / {s.shot}{!s.has_stage ? ` (${tr('pas de stage', 'no stage')})` : ''}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Row>
              ) : (
                <Row label={tr('Fichier USD', 'USD file')}>
                  <div style={{ display: 'flex', gap: 6 }}>
                    <input style={input} value={usdPath} placeholder="C:\...\shot.usd" onChange={e => setUsdPath(e.target.value)} />
                    <button type="button" style={btn()} onClick={() => void browseUsd()}>{tr('Parcourir', 'Browse')}</button>
                  </div>
                </Row>
              )}

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10 }}>
                <Row label={tr('Image debut', 'Start frame')}>
                  <input type="number" style={input} value={frameStart} onChange={e => setFrameStart(e.target.value)} />
                </Row>
                <Row label={tr('Image fin', 'End frame')}>
                  <input type="number" style={input} value={frameEnd} onChange={e => setFrameEnd(e.target.value)} />
                </Row>
                <Row label={tr('Moteur', 'Renderer')}>
                  <Select value={renderer} onValueChange={v => setRenderer(v as 'karma' | 'renderman')}>
                    <SelectTrigger style={sel} />
                    <SelectContent>
                      <SelectItem value="karma">Karma</SelectItem>
                      <SelectItem value="renderman">RenderMan</SelectItem>
                    </SelectContent>
                  </Select>
                </Row>
              </div>

              <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11.5, color: 'var(--ink-2)', cursor: 'pointer' }}>
                <input type="checkbox" checked={freeze} onChange={e => setFreeze(e.target.checked)} />
                {tr('Geler la version', 'Freeze the version')}
              </label>

              <div>
                <button type="button" style={{ ...btn(true), opacity: canSubmit ? 1 : 0.45, pointerEvents: canSubmit ? 'auto' : 'none' }} onClick={() => void submit()}>
                  <Play size={11} strokeWidth={2} />{submitting ? tr('Envoi...', 'Sending...') : tr('Lancer', 'Launch')}
                </button>
              </div>

              {result && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 11.5, color: 'var(--ink-2)' }}>
                  <div>{result.title}{result.frames ? ` (${result.frames})` : ''}</div>
                  {result.warnings.map((w, i) => <div key={i} style={{ color: 'var(--warn)' }}>{w}</div>)}
                  {result.priority_warning && <div style={{ color: 'var(--warn)' }}>{result.priority_warning}</div>}
                </div>
              )}
            </div>

            <div style={{ ...card, maxWidth: 640 }}>
              <button type="button" onClick={toggleAdv}
                style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'none', border: 'none', padding: 0, cursor: 'pointer', ...lbl, marginBottom: 0 }}>
                {advOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}{tr('Reglages avances', 'Advanced settings')}
              </button>
              {advOpen && draft && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 10 }}>
                  <div style={{ fontSize: 11.5, color: 'var(--warn)' }}>
                    {tr('Ces reglages touchent les autres equipes (priorite, nombre de blades).', 'These settings affect other teams (priority, number of blades).')}
                  </div>
                  {settingsWarning && <div style={{ fontSize: 11.5, color: 'var(--warn)' }}>{settingsWarning}</div>}
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                    {txtField('Tractor project', 'tractor_project')}
                    {txtField(tr('Priorite (1 a 10000)', 'Priority (1 to 10000)'), 'priority')}
                    {txtField('Max active', 'maxactive')}
                    {txtField('Chunk size', 'chunk_size')}
                    {txtField('Service Karma', 'service_karma')}
                    {txtField('Service RenderMan', 'service_renderman')}
                    {txtField(tr('Envkeys (separes par des virgules)', 'Envkeys (comma separated)'), 'envkeys')}
                    {txtField('Engine (host:port)', 'engine')}
                    {txtField('Husk', 'husk_path')}
                    {txtField('Bridge Python', 'bridge_python')}
                    {txtField('Bridge script', 'bridge_script')}
                  </div>
                  <div style={{ display: 'flex', alignItems: 'flex-end', gap: 14, flexWrap: 'wrap' }}>
                    {chk(tr('Plage horaire', 'Schedule'), 'sch_enabled')}
                    <div style={{ width: 90 }}>{txtField(tr('Debut', 'Start'), 'sch_start', '18:00')}</div>
                    <div style={{ width: 90 }}>{txtField('Fin', 'sch_end', '08:00')}</div>
                    {chk(tr('Tuer les taches a la fin', 'Kill tasks at end'), 'sch_kill')}
                  </div>
                  {chk(tr('Mode simulation (rien envoye a la farm)', 'Simulation mode (nothing sent to the farm)'), 'dry_run')}
                  <div>
                    <button type="button" style={{ ...btn(true), opacity: saving || !Object.keys(patch).length ? 0.45 : 1, pointerEvents: saving || !Object.keys(patch).length ? 'none' : 'auto' }}
                      onClick={() => void saveAdvanced()}>{tr('Enregistrer', 'Save')}</button>
                  </div>
                </div>
              )}
            </div>
          </>
        )}

        {tab === 'jobs' && (
          <>
            <Toggle value={mine ? 'mine' : 'team'} onChange={id => setMine(id === 'mine')}
              options={[{ id: 'mine', label: tr('Mes jobs', 'My jobs') }, { id: 'team', label: tr('Equipe', 'Team') }]} />
            {jobs.length === 0 ? (
              <div style={{ fontSize: 12, color: 'var(--ink-3)' }}>
                {jobsDry ? tr('Mode simulation : aucun job sur la farm', 'Simulation mode: no job on the farm') : tr('Aucun job.', 'No jobs.')}
              </div>
            ) : (
              <div style={{ ...card, padding: 0, overflow: 'hidden' }}>
                {jobs.map(j => {
                  const pct = j.numTasks > 0 ? Math.round((j.numDone / j.numTasks) * 100) : 0
                  const out = jobOutput(j)
                  return (
                    <div key={j.jid} style={{ display: 'grid', gridTemplateColumns: 'minmax(120px,2fr) 90px minmax(100px,1.5fr) 60px 60px auto', gap: 10, alignItems: 'center', padding: '8px 12px', borderBottom: '1px solid var(--rule-2)', fontSize: 11.5, color: 'var(--ink)' }}>
                      <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={j.title}>{j.title}</div>
                      <div style={{ color: 'var(--ink-3)' }}>{j.user}</div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <div style={{ flex: 1, height: 6, borderRadius: 3, background: 'var(--rule-2)', overflow: 'hidden' }}>
                          <div style={{ width: `${pct}%`, height: '100%', background: 'var(--accent)' }} />
                        </div>
                        <span style={{ color: 'var(--ink-3)', minWidth: 28 }}>{pct}%</span>
                      </div>
                      <div style={{ color: j.numError > 0 ? 'var(--err)' : 'var(--ink-3)' }} title={tr('Erreurs', 'Errors')}>{j.numError} {tr('err.', 'err.')}</div>
                      <div style={{ color: 'var(--ink-3)' }} title={tr('Actifs', 'Active')}>{j.numActive} {tr('act.', 'act.')}</div>
                      <div style={{ display: 'flex', gap: 4, justifyContent: 'flex-end' }}>
                        {j.numActive > 0
                          ? <button type="button" style={btn()} title="Pause" onClick={() => void jobAction(j, 'pause')}><Pause size={11} /></button>
                          : <button type="button" style={btn()} title={tr('Reprendre', 'Resume')} onClick={() => void jobAction(j, 'resume')}><Play size={11} /></button>}
                        {j.numError > 0 && <button type="button" style={btn()} title={tr('Relancer les erreurs', 'Retry errors')} onClick={() => void jobAction(j, 'retry')}><RotateCcw size={11} /></button>}
                        <button type="button" style={btn(false, true)} title={tr('Arreter', 'Kill')} onClick={() => void jobAction(j, 'kill')}><Square size={11} /></button>
                        {out && <button type="button" style={btn()} title={tr('Ouvrir le dossier', 'Open folder')} onClick={() => openDir(out)}><FolderOpen size={11} /></button>}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </>
        )}

        {tab === 'farm' && (
          <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 10, maxWidth: 640 }}>
            {!farm ? <div style={{ fontSize: 12, color: 'var(--ink-3)' }}>{tr('Chargement...', 'Loading...')}</div> : (() => {
              const entries = Object.entries(farm.active_by_project).sort((a, b) => b[1] - a[1])
              const max = Math.max(1, ...entries.map(e => e[1]))
              return (
                <>
                  <div style={{ fontSize: 11.5, color: 'var(--ink-2)' }}>
                    {farm.blades.length} blades. {farm.schedule.enabled
                      ? tr(`Rendu de ${farm.schedule.start} a ${farm.schedule.end}${farm.schedule.kill_at_end ? `, taches restantes tuees a ${farm.schedule.end}` : ''}`,
                           `Render from ${farm.schedule.start} to ${farm.schedule.end}${farm.schedule.kill_at_end ? `, remaining tasks killed at ${farm.schedule.end}` : ''}`)
                      : tr('Rendu de jour autorise', 'Daytime rendering allowed')}
                  </div>
                  {entries.length === 0 && (
                    <div style={{ fontSize: 12, color: 'var(--ink-3)' }}>
                      {farm.dry_run ? tr('Mode simulation : aucun job sur la farm', 'Simulation mode: no job on the farm') : tr('La farm est libre.', 'The farm is idle.')}
                    </div>
                  )}
                  {entries.map(([name, n]) => {
                    const own = name === farm.tractor_project
                    return (
                      <div key={name} style={{ display: 'grid', gridTemplateColumns: '140px 1fr 36px', gap: 10, alignItems: 'center', fontSize: 11.5 }}>
                        <div style={{ color: own ? 'var(--accent-hi)' : 'var(--ink-2)', fontWeight: own ? 700 : undefined }}>{name}</div>
                        <div style={{ height: 8, borderRadius: 4, background: 'var(--rule-2)', overflow: 'hidden' }}>
                          <div style={{ width: `${(n / max) * 100}%`, height: '100%', background: own ? 'var(--accent)' : 'var(--ink-4)' }} />
                        </div>
                        <div style={{ color: 'var(--ink-3)', textAlign: 'right' }}>{n}</div>
                      </div>
                    )
                  })}
                </>
              )
            })()}
          </div>
        )}
      </div>
    </div>
  )
}
