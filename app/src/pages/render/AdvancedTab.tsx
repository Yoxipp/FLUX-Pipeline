// AdvancedTab.tsx: team render settings (render.json of the FLUX project, backend team_settings.py).
// Grouped by topic: team and farm share, machine groups, excluded machines, hours, technical.
// One draft, one Save: only the changed keys are sent.

import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { ChevronDown, ChevronRight, Layers, Plus, Trash2, Users } from 'lucide-react'
import { api } from '../../api/client'
import type { RenderExitCode, RenderFarm, RenderFreezeWhen, RenderSettings, RenderShare, RenderShareBase } from '../../api/client'
import { MachinePicker } from './MachinePicker'
import {
  Banner, Check, Row, Section, ShareBaseInfo, Toggle, btn, capFromPercent, disabledIf, errMsg, hint, input, lbl, useTr, warnText,
} from './renderUi'

type Key = keyof RenderSettings

function changedKeys(a: RenderSettings, b: RenderSettings): Key[] {
  return (Object.keys(b) as Key[]).filter(k => JSON.stringify(a[k]) !== JSON.stringify(b[k]))
}

export function AdvancedTab({ project, settings, warning, farm, onSaved }: {
  project: string; settings: RenderSettings; warning: string | null; farm: RenderFarm | null
  onSaved: (r: { settings: RenderSettings; warning: string | null }) => void
}) {
  const { tr } = useTr()
  const [draft, setDraft] = useState<RenderSettings>(settings)
  const [saving, setSaving] = useState(false)
  const [editGroup, setEditGroup] = useState<string | null>(null)
  const [newGroup, setNewGroup] = useState('')
  const [techOpen, setTechOpen] = useState(false)
  const [codesDraft, setCodesDraft] = useState((settings.retry_exit_codes ?? []).join(', '))
  useEffect(() => { setDraft(settings); setCodesDraft((settings.retry_exit_codes ?? []).join(', ')) }, [settings])
  // Codes recorded from the team's failed renders (read when the tab opens, the backend refreshes them).
  const [seenCodes, setSeenCodes] = useState<RenderExitCode[]>([])
  useEffect(() => {
    let live = true
    api.renderExitCodes(project).then(r => { if (live) setSeenCodes(r.codes) }).catch(() => { if (live) setSeenCodes([]) })
    return () => { live = false }
  }, [project])
  const [knownProjects, setKnownProjects] = useState<{ name: string; jobs: number }[]>([])
  useEffect(() => {
    let live = true
    api.renderTractorProjects(project).then(r => { if (live) setKnownProjects(r.projects) }).catch(() => { if (live) setKnownProjects([]) })
    return () => { live = false }
  }, [project])

  const changed = useMemo(() => changedKeys(settings, draft), [settings, draft])
  const set = <K extends Key>(k: K, v: RenderSettings[K]) => setDraft(d => ({ ...d, [k]: v }))
  const counts = farm?.counts
  const blades = farm?.blades ?? []

  const save = async () => {
    if (!changed.length) return
    setSaving(true)
    try {
      const patch = Object.fromEntries(changed.map(k => [k, draft[k]])) as Partial<RenderSettings>
      onSaved(await api.renderSaveSettings(project, patch))
      toast.success(tr('Reglages enregistres', 'Settings saved'))
    } catch (e) { toast.error(errMsg(e)) }
    finally { setSaving(false) }
  }

  const num = (k: 'priority' | 'maxactive' | 'chunk_size' | 'max_task_minutes', label: string, help?: string) => (
    <Row label={label} help={help}>
      <input type="number" style={input} value={draft[k]}
        onChange={e => set(k, Math.max(k === 'maxactive' || k === 'max_task_minutes' ? 0 : 1, Math.round(Number(e.target.value) || 0)))} />
    </Row>
  )
  // Exit codes typed freely, parsed on blur: integers only, 0 dropped (success).
  const parseCodes = (s: string) => [...new Set(s.split(/[,\s]+/).filter(Boolean).map(x => Number(x)).filter(n => Number.isInteger(n) && n !== 0))]
  const addCode = (code: number) => {
    const next = [...new Set([...parseCodes(codesDraft), code])]
    setCodesDraft(next.join(', '))
    set('retry_exit_codes', next)
  }
  const txt = (k: 'tractor_project' | 'service_karma' | 'service_renderman' | 'husk_path' | 'houdini_path' | 'bridge_python' | 'bridge_script' | 'engine' | 'engine_user',
    label: string, placeholder?: string) => (
    <Row label={label}>
      <input style={input} value={draft[k]} placeholder={placeholder} onChange={e => set(k, e.target.value)} />
    </Row>
  )
  const shareField = (k: 'team_cap', label: string, help: string) => {
    const s: RenderShare = draft[k]
    const n = capFromPercent(s.percent, counts ? counts[s.of] : 0)
    return (
      <Row label={label} help={help}>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
          <input type="number" min={0} max={100} style={{ ...input, width: 70 }} value={s.percent}
            onChange={e => set(k, { ...s, percent: Math.max(0, Math.min(100, Math.round(Number(e.target.value) || 0))) })} />
          <span style={hint}>%</span>
          <Toggle value={s.of} onChange={id => set(k, { ...s, of: id as RenderShareBase })}
            options={[{ id: 'alive', label: tr('Machines allumees', 'Machines on') }, { id: 'free', label: tr('Machines libres', 'Free machines') }]} />
          <ShareBaseInfo />
          <span style={{ ...hint, display: 'inline-flex', alignItems: 'center', gap: 3 }}>{s.percent ? <><Layers size={11} />{n}</> : tr('off', 'off')}</span>
        </div>
      </Row>
    )
  }

  const groups = draft.host_groups
  const addGroup = () => {
    const name = newGroup.trim()
    if (!/^[A-Za-z0-9_.-]{1,64}$/.test(name)) { toast.error(tr('Nom de groupe : lettres, chiffres, _ . -', 'Group name: letters, digits, _ . -')); return }
    if (!groups[name]) set('host_groups', { ...groups, [name]: [] })
    setEditGroup(name); setNewGroup('')
  }
  const removeGroup = (name: string) => {
    const next = { ...groups }; delete next[name]
    set('host_groups', next)
    if (editGroup === name) setEditGroup(null)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <Banner color="var(--warn)">
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          <Users size={12} />{tr("Reglages de toute l'equipe", 'Whole team settings')}
        </span>
      </Banner>

      <Section title={tr('Equipe et part de la farm', 'Team and farm share')}>
        <Row label={tr('Equipe sur la farm', 'Team on the farm')}>
          <input style={input} value={draft.tractor_project} onChange={e => set('tractor_project', e.target.value)} />
          {knownProjects.length > 0 && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 6 }}>
              {knownProjects.map(p => (
                <button key={p.name} type="button" title={tr(`${p.jobs} job(s) en 90 jours`, `${p.jobs} job(s) in 90 days`)}
                  style={{ ...btn(), background: draft.tractor_project === p.name ? 'var(--accent-soft)' : 'var(--paper-2)' }}
                  onClick={() => set('tractor_project', p.name)}>{p.name}</button>
              ))}
            </div>
          )}
        </Row>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          {num('priority', tr('Priorite', 'Priority'), tr('1 = comme tout le monde. Plus haut = passe avant.', '1 = like everyone. Higher = goes first.'))}
          {num('chunk_size', tr('Images par tache', 'Frames per task'))}
        </div>
        {warning && <div style={warnText}>{warning}</div>}
        {shareField('team_cap', tr("Plafond de l'equipe", 'Team cap'), tr('Tous les jobs FLUX de l\'equipe. 0 = aucun.', "All the team's FLUX jobs. 0 = none."))}
      </Section>

      <Section title={tr('Groupes de PC', 'PC groups')}>
        {Object.entries(groups).map(([name, members]) => (
          <div key={name} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11.5 }}>
            <button type="button" onClick={() => setEditGroup(editGroup === name ? null : name)}
              style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1, textAlign: 'left', background: 'none', border: 'none', padding: '2px 0', cursor: 'pointer', color: 'var(--ink)', fontSize: 11.5 }}>
              {editGroup === name ? <ChevronDown size={12} /> : <ChevronRight size={12} />}<b>{name}</b>
              <span style={hint}>{members.length} {tr('machine(s)', 'machine(s)')}</span>
            </button>
            <button type="button" style={btn(false, true)} title={tr('Supprimer le groupe', 'Delete group')} onClick={() => removeGroup(name)}><Trash2 size={11} /></button>
          </div>
        ))}
        {editGroup && groups[editGroup] && (
          <MachinePicker blades={blades} selected={groups[editGroup]} hideOffline={false}
            onChange={names => set('host_groups', { ...groups, [editGroup]: names })} />
        )}
        <div style={{ display: 'flex', gap: 6 }}>
          <input style={{ ...input, width: 200 }} value={newGroup} placeholder={tr('Nouveau groupe', 'New group')}
            onChange={e => setNewGroup(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') addGroup() }} />
          <button type="button" style={{ ...btn(), ...disabledIf(!newGroup.trim()) }} onClick={addGroup}>{tr('Ajouter', 'Add')}</button>
        </div>
      </Section>

      <Section title={tr('PC exclus', 'Excluded PCs')}>
        <MachinePicker blades={blades} selected={draft.exclude_hosts} hideOffline={false} onChange={names => set('exclude_hosts', names)} />
      </Section>

      <Section title={tr('Horaires', 'Hours')}>
        <Check label={tr('Plage de rendu', 'Render window')}
          checked={draft.schedule.enabled} onChange={v => set('schedule', { ...draft.schedule, enabled: v })} />
        {draft.schedule.enabled && (
          <div style={{ display: 'flex', gap: 10, alignItems: 'flex-end', flexWrap: 'wrap' }}>
            <div style={{ width: 90 }}><Row label={tr('Debut', 'Start')}><input style={input} value={draft.schedule.start} placeholder="18:00" onChange={e => set('schedule', { ...draft.schedule, start: e.target.value })} /></Row></div>
            <div style={{ width: 90 }}><Row label={tr('Fin', 'End')}><input style={input} value={draft.schedule.end} placeholder="08:00" onChange={e => set('schedule', { ...draft.schedule, end: e.target.value })} /></Row></div>
            <Check label={tr('Tuer les taches restantes a la fin', 'Kill remaining tasks at the end')}
              checked={draft.schedule.kill_at_end} onChange={v => set('schedule', { ...draft.schedule, kill_at_end: v })} />
          </div>
        )}
        <div style={hint}>{tr('Pas encore actif', 'Not active yet')}</div>
      </Section>

      <div style={{ border: '1px solid var(--rule-2)', borderRadius: 6, background: 'var(--paper-2)', padding: 12 }}>
        <button type="button" onClick={() => setTechOpen(o => !o)}
          style={{ display: 'flex', alignItems: 'center', gap: 6, width: '100%', textAlign: 'left', background: 'none', border: 'none', padding: 0, cursor: 'pointer', ...lbl, marginBottom: 0 }}>
          {techOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}{tr('Technique', 'Technical')}
        </button>
        {techOpen && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 10 }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              <Row label={tr('Moteur par defaut', 'Default renderer')}>
                <Toggle value={draft.renderer} onChange={id => set('renderer', id as RenderSettings['renderer'])}
                  options={[{ id: 'karma', label: 'Karma' }, { id: 'renderman', label: 'RenderMan' }]} />
              </Row>
              <Row label={tr('Gel par defaut', 'Freeze by default')}>
                <Check label={tr('Geler la version', 'Freeze the version')} checked={draft.freeze_by_default} onChange={v => set('freeze_by_default', v)} />
              </Row>
              <Row label={tr('Gel d\'un job programme', 'Scheduled job freeze')}>
                <Toggle value={draft.freeze_when} onChange={id => set('freeze_when', id as RenderFreezeWhen)}
                  options={[{ id: 'start', label: tr('Au demarrage', 'At start') }, { id: 'submit', label: tr('Au lancement', 'At submit') }]} />
              </Row>
              {txt('houdini_path', tr('Houdini des blades', 'Blades Houdini'), 'C:/Program Files/Side Effects Software/Houdini 20.5.445')}
              {txt('service_karma', 'Service Karma', 'PixarRender')}
              {txt('service_renderman', 'Service RenderMan', 'PixarRender')}
              <Row label={tr('Envkeys (separes par des virgules)', 'Envkeys (comma separated)')}>
                <input style={input} value={draft.envkeys.join(', ')}
                  onChange={e => set('envkeys', e.target.value.split(',').map(x => x.trim()).filter(Boolean))} />
              </Row>
              {num('maxactive', tr('Maximum fixe par job (0 = aucun)', 'Fixed max per job (0 = none)'))}
              {num('max_task_minutes', tr('Duree max d\'un morceau (min)', 'Max time per chunk (min)'),
                tr('Au-dela, Tractor le tue et le met en erreur. 0 = sans limite.', 'Past it, Tractor kills it (error). 0 = no limit.'))}
              <Row label={tr('Relancer sur les codes', 'Retry on exit codes')}
                help={tr('Codes de sortie de husk passagers (licence, reseau), separes par des virgules. Vide = jamais.', 'Transient husk exit codes (license, network), comma separated. Empty = never.')}>
                <input style={input} value={codesDraft} placeholder="3, 4"
                  onChange={e => setCodesDraft(e.target.value)}
                  onBlur={() => set('retry_exit_codes', parseCodes(codesDraft))} />
                {seenCodes.length > 0 && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 6, alignItems: 'center' }}>
                    <span style={hint}>{tr('Vus sur vos rendus :', 'Seen on your renders:')}</span>
                    {seenCodes.map(c => {
                      const inDraft = draft.retry_exit_codes.includes(c.code)
                      const canAdd = c.proposed && !inDraft
                      const tip = [c.label, `${c.count} ${tr('fois', 'times')}`, c.last_title && `${tr('dernier', 'last')} : ${c.last_title}`, c.last_seen.slice(0, 16)]
                        .filter(Boolean).join(' · ')
                      return (
                        <button key={c.code} type="button" title={tip} disabled={!canAdd}
                          onClick={() => addCode(c.code)}
                          style={{ ...btn(), ...disabledIf(!canAdd), background: inDraft ? 'var(--accent-soft)' : 'var(--paper-2)' }}>
                          {canAdd && <Plus size={10} />}{c.code} <span style={{ color: 'var(--ink-3)' }}>x{c.count}</span>
                        </button>
                      )
                    })}
                  </div>
                )}
              </Row>
              {txt('husk_path', 'Husk')}
              {txt('engine', 'Engine (host:port)', 'TRACTOR_ENGINE')}
              {txt('engine_user', tr('Login moteur', 'Engine login'), 'root')}
              {txt('bridge_python', 'Bridge Python')}
              {txt('bridge_script', 'Bridge script')}
            </div>
            <Check label={tr('Simulation (rien envoye)', 'Simulation (nothing sent)')}
              checked={draft.dry_run} onChange={v => set('dry_run', v)} />
          </div>
        )}
      </div>

      {/* Sticky over the scroll container's 16 px bottom padding (Render.tsx), else content shows under it. */}
      <div style={{ position: 'sticky', bottom: -16, zIndex: 2, display: 'flex', gap: 8, alignItems: 'center',
        margin: '0 -16px -16px', padding: '10px 16px 16px', background: 'var(--paper)', borderTop: '1px solid var(--rule-2)' }}>
        <button type="button" style={{ ...btn(true), ...disabledIf(saving || !changed.length) }} onClick={() => void save()}>
          {changed.length ? tr(`Enregistrer (${changed.length})`, `Save (${changed.length})`) : tr('Enregistrer', 'Save')}
        </button>
        <button type="button" style={{ ...btn(), ...disabledIf(!changed.length) }} onClick={() => setDraft(settings)}>{tr('Annuler', 'Cancel')}</button>
      </div>
    </div>
  )
}
