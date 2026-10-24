// LaunchTab.tsx: submit a shot or a published USD to Tractor.
// Default view = what / frames / renderer / Launch. "Where" (machines) and "When" are folded with a
// one-line summary; team-wide settings live in the Advanced tab. How much of the farm a team gets is
// the engine's Shares (limits.config), not a FLUX setting.

import { useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'
import { Ban, ChevronDown, ChevronRight, Play, Snowflake } from 'lucide-react'
import { api } from '../../api/client'
import type {
  RenderFarm, RenderFreezeWhen, RenderLastForm, RenderSettings, RenderShareBase, RenderShot, RenderSubmitResult,
} from '../../api/client'
import { Select, SelectContent, SelectItem, SelectTrigger } from '../../components/shared/ui'
import { DenoiseForm } from './DenoiseForm'
import { MachinePicker } from './MachinePicker'
import {
  Check, Row, Toggle, btn, card, disabledIf, errMsg, hint, input, lbl, openFolder, sel, useTr, warnText,
} from './renderUi'

type Source = 'shot' | 'usd'

function Fold({ title, summary, open, onToggle, children }: {
  title: string; summary: string; open: boolean; onToggle: () => void; children: React.ReactNode
}) {
  return (
    <div style={{ borderTop: '1px solid var(--rule-2)', paddingTop: 10 }}>
      <button type="button" onClick={onToggle}
        style={{ display: 'flex', alignItems: 'center', gap: 6, width: '100%', background: 'none', border: 'none', padding: 0, cursor: 'pointer', textAlign: 'left' }}>
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        <span style={{ ...lbl, marginBottom: 0 }}>{title}</span>
        {!open && <span style={{ ...hint, marginLeft: 6 }}>{summary}</span>}
      </button>
      {open && <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 10 }}>{children}</div>}
    </div>
  )
}

export function LaunchTab({ project, settings, shots, farm, onSubmitted }: {
  project: string; settings: RenderSettings | null; shots: RenderShot[]; farm: RenderFarm | null; onSubmitted: () => void
}) {
  const { tr, locale } = useTr()
  const [source, setSource] = useState<Source>('shot')
  const [shotKey, setShotKey] = useState('')
  const [usdPath, setUsdPath] = useState('')
  const [frameStart, setFrameStart] = useState('')
  const [frameEnd, setFrameEnd] = useState('')
  const [renderer, setRenderer] = useState<'karma' | 'renderman' | ''>(settings?.renderer ?? '')
  const [freeze, setFreeze] = useState(settings?.freeze_by_default ?? true)
  const [freezeWhen, setFreezeWhen] = useState<RenderFreezeWhen>(settings?.freeze_when ?? 'start')
  const [startAt, setStartAt] = useState('')   // "YYYY-MM-DDTHH:MM", empty = now
  const [priority, setPriority] = useState(settings?.priority ?? 1)   // this job only (team default first)
  const [denoise, setDenoise] = useState(false)   // RenderMan denoise_batch after the render
  const [denoiseCross, setDenoiseCross] = useState(settings?.denoise_crossframe ?? true)
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<RenderSubmitResult | null>(null)

  // where and how much
  const [whereOpen, setWhereOpen] = useState(false)
  const [whenOpen, setWhenOpen] = useState(false)
  const [denoiseOpen, setDenoiseOpen] = useState(false)
  const [limitJob, setLimitJob] = useState(false)   // off = the team cap manages it (2026-10-23)
  const [sharePct, setSharePct] = useState(25)
  const [shareOf, setShareOf] = useState<RenderShareBase>('free')
  const [targetMode, setTargetMode] = useState<'any' | 'pick'>('any')
  const [hosts, setHosts] = useState<string[]>([])
  const [groups, setGroups] = useState<string[]>([])

  // ── sequence, then shot ──
  const [seq, setSeq] = useState('')
  const seqs = useMemo(() => [...new Set(shots.map(s => s.seq))].sort(), [shots])
  const seqShots = useMemo(() => shots.filter(s => s.seq === seq), [shots, seq])
  const pickSeq = (q: string) => {
    setSeq(q)
    const only = shots.filter(s => s.seq === q && s.has_stage)
    if (only.length === 1) pickShot(shotId(only[0]))
    else { setShotKey(''); setFrameStart(''); setFrameEnd('') }
  }

  const shotId = (s: RenderShot) => `${s.seq}/${s.shot}`
  const pickShot = (id: string) => {
    setShotKey(id)
    const s = shots.find(x => shotId(x) === id)
    setFrameStart(s?.frame_start != null ? String(s.frame_start) : '')
    setFrameEnd(s?.frame_end != null ? String(s.frame_end) : '')
  }
  // Frame range read from the USD root layer, as soon as a file is picked.
  const detectUsdRange = async (p: string) => {
    if (!p.trim()) return
    try {
      const r = await api.renderUsdRange(project, p.trim())
      setFrameStart(r.frame_start != null ? String(r.frame_start) : '')
      setFrameEnd(r.frame_end != null ? String(r.frame_end) : '')
      if (r.frame_start == null) toast.message(tr('Pas de plage dans ce USD : la saisir', 'No frame range in this USD: type it'))
    } catch (e) { toast.error(errMsg(e)) }
  }
  // USD library of the project (assemblies and components with a LAST), proposed before browsing.
  const [libItems, setLibItems] = useState<{ label: string; path: string }[]>([])
  useEffect(() => {
    if (source !== 'usd' || libItems.length) return
    let live = true
    api.getUsdLibrary(project).then(lib => {
      if (!live) return
      const sets = lib.assemblies.map(a => ({ label: `${tr('Set', 'Set')} · ${a.name}`, path: a.file }))
      const comps = lib.components.filter(c => c.last).map(c => ({ label: `${tr('Asset', 'Asset')} · ${c.name}`, path: c.last! }))
      setLibItems([...sets, ...comps].sort((a, b) => a.label.localeCompare(b.label)))
    }).catch(() => { /* no library: browse only */ })
    return () => { live = false }
  }, [project, source]) // eslint-disable-line react-hooks/exhaustive-deps
  const browseUsd = async () => {
    const p = await window.electronAPI?.openFile?.([{ name: 'USD', extensions: ['usd', 'usda', 'usdc'] }])
    if (p) { setUsdPath(p); void detectUsdRange(p) }
  }
  const pickSource = (s: Source) => {
    setSource(s)
    if (s === 'shot') { if (shotKey) pickShot(shotKey); else { setFrameStart(''); setFrameEnd('') } }
    else if (usdPath.trim()) void detectUsdRange(usdPath)
    else { setFrameStart(''); setFrameEnd('') }
  }

  const teamGroups = settings?.host_groups ?? {}
  const pickedCount = new Set([...hosts, ...groups.flatMap(g => teamGroups[g] ?? [])]).size
  const whereSummary = targetMode === 'any' ? tr('Toute la farm', 'Whole farm') : `${pickedCount} PC`

  // ── when ──
  const pad = (n: number) => String(n).padStart(2, '0')
  const isoDay = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
  const dayOptions = Array.from({ length: 7 }, (_, i) => {
    const d = new Date(); d.setDate(d.getDate() + i)
    const name = i === 0 ? tr("Aujourd'hui", 'Today') : i === 1 ? tr('Demain', 'Tomorrow')
      : d.toLocaleDateString(locale, { weekday: 'short', day: '2-digit', month: '2-digit' })
    return { value: isoDay(d), label: name }
  })
  const [atDay, atTime] = startAt ? startAt.split('T') : ['', '']
  const [atHour, atMin] = atTime ? atTime.split(':') : ['', '']
  const setWhen = (day: string, hour: string, min: string) => setStartAt(day ? `${day}T${hour || '20'}:${min || '00'}` : '')
  const freezeAtStart = freeze && !!startAt && freezeWhen === 'start'
  const freezeSummary = !freeze ? 'LAST' : freezeAtStart ? tr('gele au demarrage', 'frozen at start') : tr('gele', 'frozen')
  const whenSummary = `${startAt ? startAt.replace('T', ' ') : tr('Maintenant', 'Now')}  ·  ${freezeSummary}`

  // ── last form of this artist: restored once shots are known, saved (debounced) on change ──
  const restored = useRef(false)
  const lastRef = useRef<Partial<RenderLastForm> | null>(null)
  const [lastReady, setLastReady] = useState(false)
  useEffect(() => {
    let live = true
    api.renderLast(project).then(r => { if (live) lastRef.current = r.last })
      .catch(() => { /* first launch or offline: empty form */ })
      .finally(() => { if (live) setLastReady(true) })
    return () => { live = false }
  }, [project])
  useEffect(() => {
    if (restored.current || !lastReady) return
    const l = lastRef.current ?? {}
    if (l.source === 'shot' && l.seq && !shots.length) return  // wait for the shot list
    restored.current = true
    if (l.renderer) setRenderer(l.renderer)
    if (typeof l.freeze === 'boolean') setFreeze(l.freeze)
    if (l.freeze_when === 'start' || l.freeze_when === 'submit') setFreezeWhen(l.freeze_when)
    if (typeof l.limit_job === 'boolean') setLimitJob(l.limit_job)
    if (typeof l.denoise === 'boolean') setDenoise(l.denoise)
    if (typeof l.denoise_crossframe === 'boolean') setDenoiseCross(l.denoise_crossframe)
    if (typeof l.share_percent === 'number' && l.share_percent > 0) setSharePct(l.share_percent)
    if (l.share_of) setShareOf(l.share_of)
    if (l.target) setTargetMode(l.target)
    if (Array.isArray(l.hosts)) setHosts(l.hosts)
    if (Array.isArray(l.groups)) setGroups(l.groups.filter(g => g in (settings?.host_groups ?? {})))
    if (l.source === 'usd' && l.usd_path) { setSource('usd'); setUsdPath(l.usd_path); void detectUsdRange(l.usd_path) }
    else if (l.seq && seqs.includes(l.seq)) {
      setSeq(l.seq)
      const s = shots.find(x => x.seq === l.seq && x.shot === l.shot && x.has_stage)
      if (s) pickShot(shotId(s))
    }
  }, [lastReady, shots]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!restored.current) return
    const [, shot] = shotKey.split('/')
    const form: RenderLastForm = {
      source, seq, shot: shot ?? '', usd_path: usdPath, renderer: renderer as 'karma' | 'renderman', freeze, limit_job: limitJob,
      share_percent: sharePct, share_of: shareOf, target: targetMode, hosts, groups, freeze_when: freezeWhen,
      denoise, denoise_crossframe: denoiseCross,
    }
    const t = window.setTimeout(() => { api.renderSaveLast(project, form).catch(() => { /* not critical */ }) }, 800)
    return () => window.clearTimeout(t)
  }, [project, source, seq, shotKey, usdPath, renderer, freeze, freezeWhen, limitJob, sharePct, shareOf, targetMode, hosts, groups,
    denoise, denoiseCross])

  const targetEmpty = targetMode === 'pick' && pickedCount === 0
  const canSubmit = !submitting && !targetEmpty && !!renderer && (source === 'shot' ? !!shotKey : !!usdPath.trim())
  const submit = async () => {
    if (!canSubmit) return
    const body: Parameters<typeof api.renderSubmit>[0] = { project, renderer: renderer as 'karma' | 'renderman', freeze, priority }
    if (denoise && renderer === 'renderman') { body.denoise = true; body.denoise_crossframe = denoiseCross }
    if (source === 'shot') { const [seq, shot] = shotKey.split('/'); body.seq = seq; body.shot = shot }
    else body.usd_path = usdPath.trim()
    if (frameStart !== '') body.frame_start = Number(frameStart)
    if (frameEnd !== '') body.frame_end = Number(frameEnd)
    if (startAt) { body.start_at = startAt; body.freeze_when = freezeWhen }
    body.share_percent = 0   // never a FLUX cap per job: the engine's Shares share the farm
    if (targetMode === 'pick') { body.hosts = hosts; body.groups = groups }
    setSubmitting(true)
    try {
      const r = await api.renderSubmit(body)
      setResult(r)
      if (r.dry_run) {
        toast.success(tr("Simulation : job ecrit, rien n'est envoye a la farm", 'Simulation: job written, nothing sent to the farm'), {
          action: { label: tr('Ouvrir le dossier', 'Open folder'), onClick: () => openFolder(r.files.alf) },
        })
      } else if (startAt) {
        const when = (r.start_at || startAt).replace('T', ' ')
        toast.success(tr(`Job envoye (jid ${r.jid}), demarrera le ${when}`, `Job sent (jid ${r.jid}), will start on ${when}`))
      } else toast.success(`${tr('Job envoye', 'Job sent')} (jid ${r.jid})`)
      onSubmitted()
    } catch (e) { toast.error(errMsg(e)) }
    finally { setSubmitting(false) }
  }

  return (
    <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 12 }}>
      <Toggle value={source} onChange={id => pickSource(id as Source)}
        options={[{ id: 'shot', label: 'Shot' }, { id: 'usd', label: tr('USD publie', 'Published USD') }]} />

      {source === 'shot' ? (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          <Row label={tr('Sequence', 'Sequence')}>
            <Select value={seq} onValueChange={pickSeq}>
              <SelectTrigger style={sel}>{!seq && <span style={{ color: 'var(--ink-3)' }}>{tr('Choisir', 'Pick')}</span>}</SelectTrigger>
              <SelectContent>
                {seqs.map(q => <SelectItem key={q} value={q}>{q}</SelectItem>)}
              </SelectContent>
            </Select>
          </Row>
          <Row label="Shot">
            <Select value={shotKey} onValueChange={pickShot}>
              <SelectTrigger style={{ ...sel, ...disabledIf(!seq) }}>{!shotKey && <span style={{ color: 'var(--ink-3)' }}>{tr('Choisir', 'Pick')}</span>}</SelectTrigger>
              <SelectContent>
                {seqShots.map(s => (
                  <SelectItem key={shotId(s)} value={shotId(s)} disabled={!s.has_stage}>
                    {s.shot}{!s.has_stage ? ` (${tr('pas de stage', 'no stage')})` : ''}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Row>
        </div>
      ) : (
        <Row label={tr('Fichier USD', 'USD file')}>
          {libItems.length > 0 && (
            <div style={{ marginBottom: 6 }}>
              <div style={{ ...hint, marginBottom: 3 }}>{tr('Bibliotheque USD du projet, ou parcourir plus bas', 'Project USD library, or browse below')}</div>
              <Select value={libItems.some(i => i.path === usdPath) ? usdPath : undefined}
                onValueChange={p => { setUsdPath(p); void detectUsdRange(p) }}>
                <SelectTrigger style={sel} title={tr('Bibliotheque USD du projet', 'Project USD library')} />
                <SelectContent>
                  {libItems.map(i => <SelectItem key={i.path} value={i.path}>{i.label}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          )}
          <div style={{ display: 'flex', gap: 6 }}>
            <input style={input} value={usdPath} placeholder="\\serveur\...\shot.usd" onChange={e => setUsdPath(e.target.value)}
              onBlur={() => void detectUsdRange(usdPath)} />
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
            <SelectTrigger style={sel}>{!renderer && <span style={{ color: 'var(--ink-3)' }}>{tr('Choisir', 'Pick')}</span>}</SelectTrigger>
            <SelectContent>
              <SelectItem value="karma">Karma</SelectItem>
              <SelectItem value="renderman">RenderMan</SelectItem>
            </SelectContent>
          </Select>
        </Row>
        <Row label={tr('Priorite', 'Priority')}
          help={tr('Defaut 1, >1 = prend une part de la farm aux autres groupes', 'Default 1, >1 = takes farm share from other groups')}>
          <input type="number" min={1} max={10000} style={input} value={priority}
            onChange={e => setPriority(Math.max(1, Math.min(10000, Math.round(Number(e.target.value) || 1))))} />
        </Row>
      </div>

      {/* How much of the farm: the engine's Shares (limits.config) decide, not FLUX (2026-10-23). */}
      <Fold title={tr('Ou', 'Where')} summary={whereSummary} open={whereOpen} onToggle={() => setWhereOpen(o => !o)}>
        <Row label={tr('Machines', 'Machines')}>
          <Toggle value={targetMode} onChange={id => setTargetMode(id as 'any' | 'pick')}
            options={[{ id: 'any', label: tr('Toute la farm', 'Whole farm') }, { id: 'pick', label: tr('Choisir les PC', 'Pick PCs') }]} />
          {targetMode === 'pick' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
              {Object.keys(teamGroups).length > 0 && (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
                  {Object.entries(teamGroups).map(([g, m]) => (
                    <Check key={g} label={`${g} (${m.length})`} checked={groups.includes(g)}
                      onChange={v => setGroups(v ? [...groups, g] : groups.filter(x => x !== g))} />
                  ))}
                </div>
              )}
              <MachinePicker blades={farm?.blades ?? []} selected={hosts} onChange={setHosts} />
            </div>
          )}
          {(settings?.exclude_hosts.length ?? 0) > 0 && (
            <div style={{ ...hint, marginTop: 4, display: 'flex', alignItems: 'center', gap: 4 }}>
              <Ban size={11} />{settings!.exclude_hosts.join(', ')}
            </div>
          )}
        </Row>
      </Fold>

      <Fold title={tr('Quand', 'When')} summary={whenSummary} open={whenOpen} onToggle={() => setWhenOpen(o => !o)}>
        <Row label={tr('Lancer a', 'Start at')}>
          <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr', gap: 6 }}>
            <Select value={atDay || 'now'} onValueChange={v => setWhen(v === 'now' ? '' : v, atHour, atMin)}>
              <SelectTrigger style={sel} />
              <SelectContent>
                <SelectItem value="now">{tr('Maintenant', 'Now')}</SelectItem>
                {dayOptions.map(o => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
              </SelectContent>
            </Select>
            {atDay && (
              <>
                <Select value={atHour} onValueChange={v => setWhen(atDay, v, atMin)}>
                  <SelectTrigger style={sel} />
                  <SelectContent>
                    {Array.from({ length: 24 }, (_, h) => <SelectItem key={h} value={pad(h)}>{pad(h)} h</SelectItem>)}
                  </SelectContent>
                </Select>
                <Select value={atMin} onValueChange={v => setWhen(atDay, atHour, v)}>
                  <SelectTrigger style={sel} />
                  <SelectContent>
                    {['00', '15', '30', '45'].map(m => <SelectItem key={m} value={m}>{m} min</SelectItem>)}
                  </SelectContent>
                </Select>
              </>
            )}
          </div>
        </Row>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <Check label={tr('Geler la version', 'Freeze the version')} checked={freeze} onChange={setFreeze} />
          {freeze && atDay && (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <Snowflake size={11} style={{ color: 'var(--ink-3)' }} />
              <Toggle value={freezeWhen} onChange={id => setFreezeWhen(id as RenderFreezeWhen)}
                options={[
                  { id: 'start', label: tr('Au demarrage', 'At start'), title: tr('Derniers publishs au moment du rendu', 'Latest publishes when the render starts') },
                  { id: 'submit', label: tr('Maintenant', 'Now'), title: tr('Versions publiees en ce moment', 'Versions published right now') },
                ]} />
            </span>
          )}
        </div>
      </Fold>

      {renderer === 'renderman' && (
        <Fold title="Denoise" summary={denoise ? tr(`Apres le rendu${denoiseCross ? ' · crossframe' : ''}`, `After the render${denoiseCross ? ' · crossframe' : ''}`) : tr('Non', 'No')}
          open={denoiseOpen} onToggle={() => setDenoiseOpen(o => !o)}>
          <Row label={tr('Apres ce rendu', 'After this render')}
            help={tr('Vers vNNN/denoised, AOV de denoise requis', 'Into vNNN/denoised, denoise AOVs required')}>
            <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
              <Check label={tr('Denoiser apres', 'Denoise after')} checked={denoise} onChange={setDenoise} />
              {denoise && <Check label={tr('Entre images (crossframe)', 'Crossframe')} checked={denoiseCross} onChange={setDenoiseCross} />}
            </div>
          </Row>
        </Fold>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <button type="button" style={{ ...btn(true), ...disabledIf(!canSubmit) }} onClick={() => void submit()}>
          <Play size={11} strokeWidth={2} />{submitting ? tr('Envoi...', 'Sending...') : tr('Lancer', 'Launch')}
        </button>
        {targetEmpty && <span style={warnText}>{tr('Aucune machine choisie', 'No machine picked')}</span>}
      </div>

      {result && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 11.5, color: 'var(--ink-2)' }}>
          <div>{result.title}{result.frames ? ` (${result.frames})` : ''}</div>
          <div style={hint}>
            {result.maxactive ? tr(`${result.maxactive} morceaux en parallele max`, `${result.maxactive} chunks at once max`) : tr('Sans limite', 'No limit')}
            {result.service ? ` ; service : ${result.service}` : ''}
          </div>
          {result.denoise && <div style={hint}>{tr(`Denoise apres le rendu : ${result.denoise}`, `Denoise after the render: ${result.denoise}`)}</div>}
          {result.warnings.map((w, i) => <div key={i} style={warnText}>{w}</div>)}
          {result.priority_warning && <div style={warnText}>{result.priority_warning}</div>}
        </div>
      )}

      <DenoiseForm project={project} settings={settings} onSubmitted={onSubmitted} />
    </div>
  )
}
