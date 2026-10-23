// LaunchTab.tsx: submit a shot or a published USD to Tractor.
// Default view = what / frames / renderer / Launch. "Where and how much" (farm share, machines)
// and "When" are folded with a one-line summary; team-wide settings live in the Advanced tab.

import { useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'
import { ChevronDown, ChevronRight, Play } from 'lucide-react'
import { api } from '../../api/client'
import type { RenderFarm, RenderLastForm, RenderSettings, RenderShareBase, RenderShot, RenderSubmitResult } from '../../api/client'
import { Select, SelectContent, SelectItem, SelectTrigger } from '../../components/shared/ui'
import { MachinePicker } from './MachinePicker'
import {
  Check, Row, Toggle, btn, capFromPercent, card, disabledIf, errMsg, hint, input, lbl, openFolder, sel, useTr, warnText,
} from './renderUi'

type Source = 'shot' | 'usd'
const SHARE_PRESETS = [10, 25, 50]

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
  const [renderer, setRenderer] = useState<'karma' | 'renderman'>(settings?.renderer ?? 'karma')
  const [freeze, setFreeze] = useState(settings?.freeze_by_default ?? true)
  const [startAt, setStartAt] = useState('')   // "YYYY-MM-DDTHH:MM", empty = now
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<RenderSubmitResult | null>(null)

  // where and how much
  const [whereOpen, setWhereOpen] = useState(false)
  const [whenOpen, setWhenOpen] = useState(false)
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

  // ── share preview (same rule as the backend) ──
  const counts = farm?.counts
  const pool = (of: RenderShareBase) => (counts ? counts[of] : 0)
  const share = limitJob ? { percent: sharePct, of: shareOf } : { percent: 0, of: shareOf }
  const jobCap = capFromPercent(share.percent, pool(share.of))
  const teamCap = settings ? capFromPercent(settings.team_cap.percent, pool(settings.team_cap.of)) : 0
  function teamCapSummary() {
    return teamCap ? tr(`gere par l'equipe (plafond ${teamCap})`, `managed by the team (cap ${teamCap})`) : tr('sans limite', 'no limit')
  }
  const ofLabel = (of: RenderShareBase) => (of === 'free' ? tr('libres maintenant', 'free right now') : tr('allumes', 'alive'))
  const shareSummary = share.percent
    ? tr(`${share.percent} % des blades ${ofLabel(share.of)} (${jobCap} en parallele)`, `${share.percent} % of ${ofLabel(share.of)} blades (${jobCap} at once)`)
    : teamCapSummary()
  const teamGroups = settings?.host_groups ?? {}
  const pickedCount = new Set([...hosts, ...groups.flatMap(g => teamGroups[g] ?? [])]).size
  const whereSummary = `${targetMode === 'any' ? tr('Toute la farm', 'Whole farm') : tr(`${pickedCount} machine(s)`, `${pickedCount} machine(s)`)}, ${shareSummary}`

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
  const whenSummary = `${startAt ? startAt.replace('T', ' ') : tr('Maintenant', 'Now')}, ${freeze ? tr('version gelee', 'version frozen') : tr('version LAST', 'LAST version')}`

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
    if (typeof l.limit_job === 'boolean') setLimitJob(l.limit_job)
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
      source, seq, shot: shot ?? '', usd_path: usdPath, renderer, freeze, limit_job: limitJob,
      share_percent: sharePct, share_of: shareOf, target: targetMode, hosts, groups,
    }
    const t = window.setTimeout(() => { api.renderSaveLast(project, form).catch(() => { /* not critical */ }) }, 800)
    return () => window.clearTimeout(t)
  }, [project, source, seq, shotKey, usdPath, renderer, freeze, limitJob, sharePct, shareOf, targetMode, hosts, groups])

  const targetEmpty = targetMode === 'pick' && pickedCount === 0
  const canSubmit = !submitting && !targetEmpty && (source === 'shot' ? !!shotKey : !!usdPath.trim())
  const submit = async () => {
    if (!canSubmit) return
    const body: Parameters<typeof api.renderSubmit>[0] = { project, renderer, freeze }
    if (source === 'shot') { const [seq, shot] = shotKey.split('/'); body.seq = seq; body.shot = shot }
    else body.usd_path = usdPath.trim()
    if (frameStart !== '') body.frame_start = Number(frameStart)
    if (frameEnd !== '') body.frame_end = Number(frameEnd)
    if (startAt) body.start_at = startAt
    body.share_percent = limitJob ? sharePct : 0
    body.share_of = shareOf
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
    <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 720 }}>
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
            <SelectTrigger style={sel} />
            <SelectContent>
              <SelectItem value="karma">Karma</SelectItem>
              <SelectItem value="renderman">RenderMan</SelectItem>
            </SelectContent>
          </Select>
        </Row>
      </div>

      <Fold title={tr('Ou et combien', 'Where and how much')} summary={whereSummary} open={whereOpen} onToggle={() => setWhereOpen(o => !o)}>
        <Row label={tr('Part de la farm pour ce job', 'Farm share for this job')}
          help={tr('Nombre maximum de morceaux (chunks) rendus en meme temps. 1 blade = 1 morceau.',
            'Max chunks rendered at once. 1 blade = 1 chunk.')}>
          <Check label={tr('Limiter ce job (sinon gere par le plafond de l\'equipe)', 'Limit this job (otherwise managed by the team cap)')}
            checked={limitJob} onChange={setLimitJob} />
          {limitJob && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center', marginTop: 6 }}>
              <Toggle value={SHARE_PRESETS.includes(sharePct) ? String(sharePct) : 'other'}
                onChange={id => {
                  if (id === 'other') { if (SHARE_PRESETS.includes(sharePct)) setSharePct(33) }
                  else setSharePct(Number(id))
                }}
                options={[...SHARE_PRESETS.map(p => ({ id: String(p), label: `${p} %` })), { id: 'other', label: tr('Autre', 'Other') }]} />
              {!SHARE_PRESETS.includes(sharePct) && (
                <input type="number" min={1} max={100} style={{ ...input, width: 70 }} value={sharePct}
                  onChange={e => setSharePct(Math.max(1, Math.min(100, Number(e.target.value) || 1)))} />
              )}
              <Toggle value={shareOf} onChange={id => setShareOf(id as RenderShareBase)}
                options={[{ id: 'free', label: tr('des blades libres', 'of free blades') }, { id: 'alive', label: tr('des blades allumes', 'of alive blades') }]} />
            </div>
          )}
          <div style={{ ...hint, marginTop: 4 }}>
            {counts ? tr(`Farm : ${counts.alive} allumes, ${counts.free} libres. Ce job : ${shareSummary}.`,
              `Farm: ${counts.alive} alive, ${counts.free} free. This job: ${shareSummary}.`) : tr('Etat de la farm inconnu', 'Farm state unknown')}
            {teamCap ? tr(` Plafond de l'equipe (tous ses jobs) : ${teamCap}.`, ` Team cap (all its jobs): ${teamCap}.`) : ''}
          </div>
        </Row>

        <Row label={tr('Machines', 'Machines')}>
          <Toggle value={targetMode} onChange={id => setTargetMode(id as 'any' | 'pick')}
            options={[{ id: 'any', label: tr('Toute la farm', 'Whole farm') }, { id: 'pick', label: tr('Choisir', 'Pick') }]} />
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
              {farm && !farm.host_targeting_verified && (
                <div style={warnText}>{tr("Ciblage par nom de PC pas encore valide sur le moteur de l'ecole (job test a faire).",
                  'Targeting by PC name not validated on the school engine yet (test job pending).')}</div>
              )}
            </div>
          )}
          {(settings?.exclude_hosts.length ?? 0) > 0 && (
            <div style={{ ...hint, marginTop: 4 }}>{tr('Jamais sur', 'Never on')} : {settings!.exclude_hosts.join(', ')}</div>
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
        <Check label={tr('Geler la version (conseille)', 'Freeze the version (recommended)')} checked={freeze} onChange={setFreeze} />
      </Fold>

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
          {result.warnings.map((w, i) => <div key={i} style={warnText}>{w}</div>)}
          {result.priority_warning && <div style={warnText}>{result.priority_warning}</div>}
        </div>
      )}
    </div>
  )
}
