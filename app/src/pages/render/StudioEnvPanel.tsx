// StudioEnvPanel.tsx: "Environnement du studio" of the Avance tab (ADR 0063).
// A studio = one workspace. CONFIG/studio.json links to an environment file holding what is specific to this
// studio's farm (engine, blade paths, limit tags, room pattern...). FLUX ships it empty. Changing the link
// switches the whole environment at once. Writing needs the project role lead or supervisor (backend 403 otherwise).
// Precedence of a render setting: render.json of the project > this environment > empty.

import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Building2, ChevronDown } from 'lucide-react'
import { studioEnvApi } from '../../api/studioEnv'
import type { StudioEnvState, StudioFarmValues } from '../../api/studioEnv'
import { Check, Row, Toggle, btn, card, disabledIf, errMsg, hint, input, lbl, useTr, warnText } from './renderUi'

type TextKey = Exclude<keyof StudioFarmValues, 'priority' | 'forbid_drive_letters' | 'envkeys' | 'renderer'>

export function StudioEnvPanel({ project, onChanged }: { project: string; onChanged?: () => void }) {
  const { tr } = useTr()
  const [open, setOpen] = useState(false)
  const [state, setState] = useState<StudioEnvState | null>(null)
  const [draft, setDraft] = useState<StudioFarmValues | null>(null)
  const [link, setLink] = useState('')
  const [create, setCreate] = useState(false)
  const [busy, setBusy] = useState(false)

  const apply = useCallback((s: StudioEnvState) => { setState(s); setDraft(s.values); setLink(s.link) }, [])
  useEffect(() => {
    if (!open) return
    let live = true
    studioEnvApi.get(project).then(s => { if (live) apply(s) }).catch(e => { if (live) toast.error(errMsg(e)) })
    return () => { live = false }
  }, [open, project, apply])

  const changedKeys = (state && draft)
    ? (Object.keys(draft) as (keyof StudioFarmValues)[]).filter(k => JSON.stringify(state.values[k]) !== JSON.stringify(draft[k]))
    : []
  const set = <K extends keyof StudioFarmValues>(k: K, v: StudioFarmValues[K]) => setDraft(d => (d ? { ...d, [k]: v } : d))

  const run = async (work: () => Promise<StudioEnvState>, ok: string) => {
    setBusy(true)
    try { apply(await work()); toast.success(ok); onChanged?.() }
    catch (e) { toast.error(errMsg(e)) }
    finally { setBusy(false) }
  }
  const saveLink = () => run(() => studioEnvApi.setLink(project, link.trim(), create),
    tr("Lien de l'environnement enregistre", 'Environment link saved'))
  const saveValues = () => {
    if (!draft) return
    const patch = Object.fromEntries(changedKeys.map(k => [k, draft[k]])) as Partial<StudioFarmValues>
    return run(() => studioEnvApi.save(project, patch), tr("Environnement du studio enregistre", 'Studio environment saved'))
  }

  if (!open) {
    return (
      <div>
        <button type="button" style={btn()} onClick={() => setOpen(true)}>
          <Building2 size={12} />{tr('Environnement du studio', 'Studio environment')}
        </button>
      </div>
    )
  }

  const field = (k: TextKey, label: string, placeholder?: string, help?: string) => (
    <Row label={label} help={help}>
      <input style={input} value={draft?.[k] ?? ''} placeholder={placeholder} onChange={e => set(k, e.target.value as never)} />
    </Row>
  )
  const hasFile = !!state?.exists
  const linkChanged = !!state && link.trim() !== state.link

  return (
    <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 10 }}>
      <button type="button" onClick={() => setOpen(false)}
        style={{ display: 'flex', alignItems: 'center', gap: 6, width: '100%', textAlign: 'left', background: 'none', border: 'none', padding: 0, cursor: 'pointer', ...lbl, marginBottom: 0 }}>
        <ChevronDown size={12} />{tr('Environnement du studio', 'Studio environment')}
      </button>
      <div style={hint}>
        {tr("Ce qui est propre a la farm de ce studio (moteur, chemins des blades, tags, salles). Vide par defaut. Priorite : reglage du projet, puis cet environnement, puis vide. Role lead ou supervisor requis pour modifier.",
          "What is specific to this studio's farm (engine, blade paths, tags, rooms). Empty by default. Precedence: project setting, then this environment, then empty. Project role lead or supervisor required to edit.")}
      </div>

      <Row label={tr("Lien vers le fichier d'environnement", 'Link to the environment file')}
        help={tr("Chemin relatif au dossier FLUX ou chemin complet (reseau). Changer le lien change tout l'environnement d'un coup.",
          'Path relative to the FLUX folder, or full (network) path. Changing the link switches the whole environment.')}>
        <div style={{ display: 'flex', gap: 6 }}>
          <input style={input} value={link} placeholder="CONFIG/environment.json" onChange={e => setLink(e.target.value)} />
          <button type="button" style={{ ...btn(), ...disabledIf(busy || !linkChanged) }} onClick={() => void saveLink()}>
            {tr('Enregistrer le lien', 'Save link')}
          </button>
        </div>
        <div style={{ marginTop: 6 }}>
          <Check label={tr("Creer le fichier (vide) s'il n'existe pas", "Create the (empty) file if it does not exist")} checked={create} onChange={setCreate} />
        </div>
        {state && (state.link
          ? (hasFile
            ? <div style={{ ...hint, marginTop: 4 }}>{tr('Fichier :', 'File:')} {state.path}</div>
            : <div style={{ ...warnText, marginTop: 4 }}>{tr('Fichier introuvable :', 'File not found:')} {state.path}</div>)
          : <div style={{ ...hint, marginTop: 4 }}>{tr("Aucun environnement lie : tous les reglages de farm sont vides.", 'No environment linked: every farm setting is empty.')}</div>)}
      </Row>

      {hasFile && draft && state && (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            {field('engine', tr('Moteur Tractor (hote:port)', 'Tractor engine (host:port)'), 'host:5600')}
            {field('engine_user', tr('Compte du moteur', 'Engine login'), '',
              tr('Vide = le nom de l\'utilisateur FLUX', 'Empty = the FLUX user name'))}
            {field('engine_config_dir', tr('Dossier de config du moteur (reseau)', 'Engine config folder (network)'), '\\\\server\\tractor\\config')}
            {field('bridge_python', tr('Python de Tractor (postes)', 'Tractor Python (workstations)'), '', tr('Python 2.7 de Tractor, lance le pont', "Tractor's Python 2.7, runs the bridge"))}
            {field('blade_tractor_python', tr('Python de Tractor (blades)', 'Tractor Python (blades)'), '', tr('Pour le gel au demarrage', 'For freeze at start'))}
            {field('houdini_path', tr('Dossier Houdini des blades', 'Blades Houdini folder'), '', tr('Pour le gel au demarrage', 'For freeze at start'))}
            {field('denoise_path', tr('denoise_batch des blades', 'Blades denoise_batch'), '', tr('Pour le denoise RenderMan', 'For RenderMan denoise'))}
            {field('husk_path', 'Husk', '', tr('Vide = husk du PATH des blades', 'Empty = husk from the blades PATH'))}
            <Row label={tr('Moteur de rendu par defaut', 'Default renderer')}>
              <Toggle value={draft.renderer} onChange={id => set('renderer', id as StudioFarmValues['renderer'])}
                options={[{ id: '', label: tr('Au lancement', 'At launch') }, { id: 'karma', label: 'Karma' }, { id: 'renderman', label: 'RenderMan' }]} />
            </Row>
            <Row label={tr('Priorite par defaut', 'Default priority')}>
              <input type="number" min={1} max={10000} style={input} value={draft.priority}
                onChange={e => set('priority', Math.max(1, Math.min(10000, Math.round(Number(e.target.value) || 1))))} />
            </Row>
            {field('render_tag', tr('Tag de limite des rendus', 'Render limit tag'), 'husk', tr('Tag implicite de Tractor pour les commandes husk', 'Tractor implicit tag of husk commands'))}
            {field('default_share', tr('Part par defaut', 'Default share'), 'default', tr('Part des projets que la farm ne liste pas', 'Share of projects the farm does not list'))}
            {field('denoise_tag', tr('Tag de limite du denoise', 'Denoise limit tag'), '', tr('Vide = aucun tag ajoute', 'Empty = no tag added'))}
            {field('room_pattern', tr('Motif des salles (regex)', 'Room pattern (regex)'), '^([A-Za-z]+)(\\d{2})',
              tr('Groupes entre parentheses = nom de la salle. Vide = pas de salles.', 'Parenthesis groups = room name. Empty = no rooms.'))}
            {field('service_karma', 'Service Karma')}
            {field('service_renderman', 'Service RenderMan')}
            <Row label={tr('Envkeys (separes par des virgules)', 'Envkeys (comma separated)')}>
              <input style={input} value={draft.envkeys.join(', ')}
                onChange={e => set('envkeys', e.target.value.split(',').map(x => x.trim()).filter(Boolean))} />
            </Row>
          </div>
          <Check label={tr('Refuser les chemins avec lettre de lecteur (le service de la farm n\'a pas de lecteurs)', 'Refuse drive letter paths (the farm service has no drive letters)')}
            checked={draft.forbid_drive_letters} onChange={v => set('forbid_drive_letters', v)} />
          <div style={{ display: 'flex', gap: 8 }}>
            <button type="button" style={{ ...btn(true), ...disabledIf(busy || !changedKeys.length) }} onClick={() => void saveValues()}>
              {changedKeys.length ? tr(`Enregistrer (${changedKeys.length})`, `Save (${changedKeys.length})`) : tr('Enregistrer', 'Save')}
            </button>
            <button type="button" style={{ ...btn(), ...disabledIf(!changedKeys.length) }} onClick={() => setDraft(state.values)}>{tr('Annuler', 'Cancel')}</button>
          </div>
        </>
      )}
    </div>
  )
}
