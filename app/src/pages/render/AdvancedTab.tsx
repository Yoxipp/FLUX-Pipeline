// AdvancedTab.tsx: team render settings (render.json of the FLUX project, backend team_settings.py).
// Grouped by topic: team and farm share, machine groups, excluded machines, hours, technical.
// One draft, one Save: only the changed keys are sent.

import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { ChevronDown, ChevronRight, Trash2 } from 'lucide-react'
import { api } from '../../api/client'
import type { RenderFarm, RenderSettings, RenderShare, RenderShareBase } from '../../api/client'
import { MachinePicker } from './MachinePicker'
import {
  Banner, Check, Row, Section, Toggle, btn, capFromPercent, disabledIf, errMsg, hint, input, lbl, useTr, warnText,
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
  useEffect(() => { setDraft(settings) }, [settings])
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

  const num = (k: 'priority' | 'maxactive' | 'chunk_size', label: string, help?: string) => (
    <Row label={label} help={help}>
      <input type="number" style={input} value={draft[k]}
        onChange={e => set(k, Math.max(k === 'maxactive' ? 0 : 1, Math.round(Number(e.target.value) || 0)))} />
    </Row>
  )
  const txt = (k: 'tractor_project' | 'service_karma' | 'service_renderman' | 'husk_path' | 'bridge_python' | 'bridge_script' | 'engine' | 'engine_user',
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
            options={[{ id: 'alive', label: tr('des blades allumes', 'of alive blades') }, { id: 'free', label: tr('des blades libres', 'of free blades') }]} />
          <span style={hint}>{s.percent ? tr(`= ${n} maintenant`, `= ${n} right now`) : tr('desactive', 'off')}</span>
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
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 720 }}>
      <Banner color="var(--warn)">{tr(
        'Ces reglages valent pour toute ton equipe (fichier render.json du projet). Priorite et part de farm touchent aussi les autres equipes.',
        'These settings apply to your whole team (render.json of the project). Priority and farm share also affect other teams.')}</Banner>

      <Section title={tr('Equipe et part de la farm', 'Team and farm share')}>
        <Row label={tr('Projet Tractor (equipe)', 'Tractor project (team)')}
          help={tr("Nom de l'equipe sur la farm. Reprendre celui de l'equipe s'il existe deja.", "Team name on the farm. Reuse the team's one if it already exists.")}>
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
          {num('priority', tr('Priorite (defaut 1)', 'Priority (default 1)'),
            tr("Plus grand = passe avant. Tous les jobs de l'ecole sont a 1 : rester a 1 pour etre a egalite.",
              'Higher goes first. Every school job is at 1: stay at 1 to be even.'))}
          {num('chunk_size', tr('Images par morceau (chunk)', 'Frames per chunk'))}
        </div>
        {warning && <div style={warnText}>{warning}</div>}
        {shareField('team_cap', tr("Plafond de toute l'equipe", 'Whole team cap'),
          tr("Budget partage par tous les jobs FLUX de l'equipe. Tant qu'un FLUX de l'equipe est ouvert, il repartit ce budget entre les jobs. 0 = pas de plafond. Un job peut en plus etre limite au lancement.",
            'Budget shared by every FLUX job of the team. While a FLUX of the team is open, it splits this budget between the jobs. 0 = no cap. A job can also be limited at launch.'))}
      </Section>

      <Section title={tr('Groupes de machines', 'Machine groups')}
        note={<div style={hint}>{tr("Groupes de l'equipe, proposes au lancement (ex. nos postes, salle 17 du soir).", 'Team groups, offered at launch (e.g. our desks, room 17 at night).')}</div>}>
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

      <Section title={tr('Machines exclues', 'Excluded machines')}
        note={<div style={hint}>{tr("L'equipe ne rend jamais sur ces machines (sauf si on les choisit a la main au lancement).", 'The team never renders on these machines (unless picked by hand at launch).')}</div>}>
        <MachinePicker blades={blades} selected={draft.exclude_hosts} hideOffline={false} onChange={names => set('exclude_hosts', names)} />
      </Section>

      <Section title={tr('Horaires', 'Hours')}>
        <Check label={tr('Activer une plage de rendu (sinon rendu a toute heure)', 'Enable a render window (otherwise render at any hour)')}
          checked={draft.schedule.enabled} onChange={v => set('schedule', { ...draft.schedule, enabled: v })} />
        {draft.schedule.enabled && (
          <div style={{ display: 'flex', gap: 10, alignItems: 'flex-end', flexWrap: 'wrap' }}>
            <div style={{ width: 90 }}><Row label={tr('Debut', 'Start')}><input style={input} value={draft.schedule.start} placeholder="18:00" onChange={e => set('schedule', { ...draft.schedule, start: e.target.value })} /></Row></div>
            <div style={{ width: 90 }}><Row label={tr('Fin', 'End')}><input style={input} value={draft.schedule.end} placeholder="08:00" onChange={e => set('schedule', { ...draft.schedule, end: e.target.value })} /></Row></div>
            <Check label={tr('Tuer les taches restantes a la fin', 'Kill remaining tasks at the end')}
              checked={draft.schedule.kill_at_end} onChange={v => set('schedule', { ...draft.schedule, kill_at_end: v })} />
          </div>
        )}
        <div style={hint}>{tr('Pas encore applique sur la farm (stocke seulement).', 'Not applied on the farm yet (stored only).')}</div>
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
              {txt('service_karma', 'Service Karma', 'PixarRender')}
              {txt('service_renderman', 'Service RenderMan', 'PixarRender')}
              <Row label={tr('Envkeys (separes par des virgules)', 'Envkeys (comma separated)')}>
                <input style={input} value={draft.envkeys.join(', ')}
                  onChange={e => set('envkeys', e.target.value.split(',').map(x => x.trim()).filter(Boolean))} />
              </Row>
              {num('maxactive', tr('Maximum fixe par job (0 = aucun)', 'Fixed max per job (0 = none)'))}
              {txt('husk_path', 'Husk')}
              {txt('engine', 'Engine (host:port)', 'TRACTOR_ENGINE')}
              {txt('engine_user', tr('Login moteur', 'Engine login'), 'root')}
              {txt('bridge_python', 'Bridge Python')}
              {txt('bridge_script', 'Bridge script')}
            </div>
            <Check label={tr('Mode simulation (rien envoye a la farm)', 'Simulation mode (nothing sent to the farm)')}
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
