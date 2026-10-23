// AdvancedSettings — project.json of the active project and the publish switches of
// this machine (.tx, USD proxy, portable paths; decision D1). Every write is validated
// by the backend, nothing is saved on error.
// Retake 06: one form, two places in the Settings page.
//   part="project"  -> Settings > Projet : everyday project values (fps, resolution).
//   part="advanced" -> Settings > Avance (after typing "Understand", N8): USD units, OCIO,
//                      env, LAST storage, actions graph, publish switches of this machine.
// Both parts load and save the whole project.json, so neither drops the other's values.

import { useEffect, useState } from 'react'
import { AlertTriangle, ExternalLink, RotateCcw, Save, Workflow } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { AdvancedProject, AdvancedSwitch } from '../api/client'
import { Btn, SecTitle } from '../components/shared/ui'
import { useProject } from '../ProjectContext'
import { useFlowRights } from './flow_editor/useFlowRights'

const errMsg = (e: unknown): string => (e instanceof Error ? e.message : String(e))
const mono = { fontFamily: 'var(--mono)', fontSize: 11 } as const
const inputStyle = {
  padding: '5px 8px', fontSize: 11, fontFamily: 'var(--mono)', background: 'var(--paper-2)', color: 'var(--ink)',
  border: '1px solid var(--rule-2)', borderRadius: 5, outline: 'none', boxSizing: 'border-box',
} as const

const SWITCH_LABELS: Record<string, { label: string; help: string }> = {
  conform_tx:              { label: 'Textures .tx au publish', help: 'Un publish de texture ecrit aussi un .tx mippe (OpenImageIO).' },
  conform_tx_colorconvert: { label: 'Convertir la couleur dans le .tx', help: 'Les maps couleur passent en lineaire dans le .tx (sinon espace source).' },
  proxy_usd:               { label: 'Proxy USD au publish', help: 'Un publish USD d\'asset ecrit aussi une geo proxy allegee (purpose proxy).' },
  proxy_reduction:         { label: 'Reduction du proxy', help: 'Part des triangles retiree (0.9 = il en reste 10 %).' },
  publish_max_parallel:    { label: 'Publishs simultanés sur ce poste', help: 'Les suivants attendent leur tour. Défaut 10.' },
  publish_max_mbps:        { label: 'Débit max par publish (Mo/s)', help: '0 = pas de limite. À régler après mesure.' },
  portable_paths:          { label: 'Chemins portables $FLUX', help: 'Les chemins donnes a Houdini sont ecrits en $FLUX/... (scenes portables).' },
}
const SOURCE_LABEL: Record<string, string> = { page: 'regle ici', lancement: 'variable au lancement', defaut: 'defaut' }

function linesOf(obj: Record<string, string>): string {
  return Object.entries(obj).map(([k, v]) => `${k}=${v}`).join('\n')
}

function parseLines(text: string): Record<string, string> {
  const out: Record<string, string> = {}
  for (const raw of text.split('\n')) {
    const line = raw.trim()
    if (!line) continue
    const i = line.indexOf('=')
    if (i <= 0) continue
    out[line.slice(0, i).trim()] = line.slice(i + 1).trim()
  }
  return out
}

export function AdvancedSettings({ part = 'advanced' }: { part?: 'project' | 'advanced' }) {
  const adv = part === 'advanced'
  const { project: activeProject } = useProject()
  const navigate = useNavigate()
  const flowRights = useFlowRights()
  const [proj, setProj] = useState<AdvancedProject | null>(null)
  const [switches, setSwitches] = useState<Record<string, AdvancedSwitch>>({})
  const [error, setError] = useState('')
  const [saved, setSaved] = useState('')
  const [busy, setBusy] = useState(false)
  // Project form (strings while editing, parsed at save).
  const [fps, setFps] = useState('')
  const [resW, setResW] = useState('')
  const [resH, setResH] = useState('')
  const [mpu, setMpu] = useState('')
  const [upAxis, setUpAxis] = useState('Y')
  const [ocio, setOcio] = useState('')
  const [envText, setEnvText] = useState('')
  const [threshold, setThreshold] = useState('')
  const [modesText, setModesText] = useState('')
  // Numeric switches (proxy_reduction, publish_max_*): text drafts by switch name.
  const [numDraft, setNumDraft] = useState<Record<string, string>>({})
  const draftsOf = (sw: Record<string, AdvancedSwitch>) => Object.fromEntries(
    Object.entries(sw).filter(([, s]) => typeof s.value === 'number').map(([k, s]) => [k, String(s.value)]))

  const load = () => {
    setError('')
    api.getAdvancedSettings(activeProject || undefined)
      .then(r => {
        setSwitches(r.switches)
        setNumDraft(draftsOf(r.switches))
        setProj(r.project)
        if (r.project) fill(r.project)
      })
      .catch(e => setError(errMsg(e)))
  }

  const fill = (p: AdvancedProject) => {
    const v = p.values
    setFps(String(v.fps ?? ''))
    setResW(String(v.resolution?.[0] ?? '')); setResH(String(v.resolution?.[1] ?? ''))
    setMpu(String(v.usd.meters_per_unit ?? '')); setUpAxis(v.usd.up_axis || 'Y')
    setOcio(v.ocio_config || '')
    setEnvText(linesOf(v.env || {}))
    setThreshold(String(v.storage.last_link_threshold_gb ?? ''))
    setModesText(linesOf(v.storage.last_mode || {}))
  }

  useEffect(load, [activeProject])

  const saveProject = () => {
    if (!proj) return
    setBusy(true); setError(''); setSaved('')
    const values = {
      fps: Number(fps),
      resolution: [Number(resW), Number(resH)],
      usd: { meters_per_unit: Number(mpu), up_axis: upAxis },
      ocio_config: ocio,
      env: parseLines(envText),
      storage: { last_link_threshold_gb: Number(threshold), last_mode: parseLines(modesText) },
    }
    api.putAdvancedProject(proj.name, values)
      .then(r => { setProj(r); fill(r); setSaved('project.json enregistre') })
      .catch(e => setError(errMsg(e)))
      .finally(() => setBusy(false))
  }

  const saveSwitch = (name: string, value: boolean | number | null) => {
    setError(''); setSaved('')
    api.putAdvancedSwitches({ [name]: value })
      .then(r => { setSwitches(r); setNumDraft(draftsOf(r)); setSaved('Reglage applique') })
      .catch(e => setError(errMsg(e)))
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 760 }}>
      {adv && <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11, color: 'var(--ink-3)', lineHeight: 1.5 }}>
        <AlertTriangle size={14} strokeWidth={1.75} color="var(--warn)" style={{ flexShrink: 0 }} />
        Ces reglages changent la facon dont FLUX ecrit les fichiers. Une valeur fausse peut casser les publishs
        du projet : ne modifie que ce que tu comprends.
      </div>}
      {error && <div style={{ fontSize: 11, color: 'var(--err)', whiteSpace: 'pre-wrap' }}>{error}</div>}
      {saved && !error && <div style={{ fontSize: 11, color: 'var(--ok)' }}>{saved}</div>}

      <SecTitle>{proj ? `${adv ? 'Technique du projet' : 'Projet'} ${proj.name} (project.json, tous les artistes)` : 'Projet'}</SecTitle>
      {!proj && <div style={{ fontSize: 11, color: 'var(--ink-4)' }}>Aucun projet actif.</div>}
      {proj && (
        <div className="card" style={{ padding: '10px 12px', display: 'grid', gridTemplateColumns: '200px 1fr', gap: '8px 12px', alignItems: 'center' }}>
          <span className="cap">Identifiant</span>
          <span style={{ ...mono, color: 'var(--ink-4)' }}>{proj.project_id}</span>
          {!adv && <>
          <span className="cap">FPS</span>
          <input style={{ ...inputStyle, width: 90 }} value={fps} onChange={e => setFps(e.target.value)} />
          <span className="cap">Resolution</span>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <input style={{ ...inputStyle, width: 80 }} value={resW} onChange={e => setResW(e.target.value)} />
            <span style={{ color: 'var(--ink-4)' }}>x</span>
            <input style={{ ...inputStyle, width: 80 }} value={resH} onChange={e => setResH(e.target.value)} />
          </div>
          </>}
          {adv && <>
          <span className="cap">USD metres par unite</span>
          <input style={{ ...inputStyle, width: 90 }} value={mpu} onChange={e => setMpu(e.target.value)} />
          <span className="cap">USD axe vertical</span>
          <select style={{ ...inputStyle, width: 90 }} value={upAxis} onChange={e => setUpAxis(e.target.value)}>
            <option value="Y">Y</option>
            <option value="Z">Z</option>
          </select>
          <span className="cap">Config OCIO</span>
          <input style={inputStyle} value={ocio} onChange={e => setOcio(e.target.value)} placeholder="vide = celle du logiciel" />
          <span className="cap">Variables d'env (CLE=valeur)</span>
          <textarea style={{ ...inputStyle, minHeight: 54, resize: 'vertical' }} value={envText} onChange={e => setEnvText(e.target.value)} />
          <span className="cap">LAST : lien au-dela de (Go)</span>
          <input style={{ ...inputStyle, width: 90 }} value={threshold} onChange={e => setThreshold(e.target.value)} />
          <span className="cap">LAST : mode par extension</span>
          <textarea
            style={{ ...inputStyle, minHeight: 54, resize: 'vertical' }} value={modesText}
            onChange={e => setModesText(e.target.value)}
            placeholder={`.abc=link   (modes : ${proj.last_modes.join(', ')})`}
          />
          </>}
          <span />
          <div style={{ display: 'flex', gap: 8 }}>
            <Btn sm primary disabled={busy} onClick={saveProject}><Save size={11} strokeWidth={2} /> Enregistrer project.json</Btn>
            <Btn sm ghost disabled={busy} onClick={() => proj && fill(proj)}><RotateCcw size={11} strokeWidth={2} /> Annuler les changements</Btn>
          </div>
        </div>
      )}

      {adv && <>
      <SecTitle>Actions (YAML)</SecTitle>
      <div className="card" style={{ padding: '10px 12px', display: 'flex', alignItems: 'center', gap: 10 }}>
        <Workflow size={14} strokeWidth={1.75} color="var(--ink-3)" />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 11, color: 'var(--ink)' }}>Flows (graph YAML)</div>
          <div style={{ fontSize: 11, color: 'var(--ink-4)', marginTop: 1 }}>
            Editeur de flows. Le publish tourne encore sur les actions v1 jusqu'a P8 : seul l'ancien editeur les modifie.
          </div>
        </div>
        <Btn sm ghost disabled={!flowRights?.td} title={flowRights?.td ? undefined : 'Coche TD dans ton profil'} onClick={() => {
          // Own window when Electron can open one, else the page in this window.
          if (window.electronAPI?.detachPage) window.electronAPI.detachPage('/action-graph')
          else navigate('/action-graph')
        }}>
          <ExternalLink size={11} strokeWidth={2} /> Ouvrir le graph
        </Btn>
        {/* P4: the old v1 action editor, the only UI that edits the real publish until P8
            (which removes it). Kept out of the new editor's bar on purpose. */}
        <span
          onClick={() => navigate('/action-graph-legacy')}
          title="Ancien editeur des actions v1 (publish reel), retire en P8"
          style={{ fontSize: 10.5, color: 'var(--ink-4)', cursor: 'pointer', textDecoration: 'underline', whiteSpace: 'nowrap' }}
        >
          Ancien editeur
        </span>
      </div>

      <SecTitle>Publish (ce poste)</SecTitle>
      <div className="card" style={{ padding: '6px 12px', display: 'flex', flexDirection: 'column' }}>
        {Object.entries(switches).map(([name, sw]) => {
          const meta = SWITCH_LABELS[name] ?? { label: name, help: '' }
          const isBool = typeof sw.value === 'boolean'
          return (
            <div key={name} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 0', borderBottom: '1px solid var(--rule)' }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 11, color: 'var(--ink)' }}>{meta.label}</div>
                <div style={{ fontSize: 11, color: 'var(--ink-4)', marginTop: 1 }}>
                  {meta.help} <span style={{ ...mono, fontSize: 10.5 }}>{sw.env}</span> · {SOURCE_LABEL[sw.source] ?? sw.source}
                </div>
              </div>
              {isBool ? (
                <div style={{ display: 'flex', gap: 4 }}>
                  {[true, false].map(v => (
                    <Btn key={String(v)} sm ghost={sw.value !== v} primary={sw.value === v} onClick={() => saveSwitch(name, v)}>
                      {v ? 'Oui' : 'Non'}
                    </Btn>
                  ))}
                </div>
              ) : (
                <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                  <input style={{ ...inputStyle, width: 70 }} value={numDraft[name] ?? ''} onChange={e => setNumDraft(d => ({ ...d, [name]: e.target.value }))} />
                  <Btn sm ghost onClick={() => saveSwitch(name, Number(numDraft[name]))}>Appliquer</Btn>
                </div>
              )}
              <Btn sm ghost disabled={sw.saved === null || sw.saved === undefined} title="Revenir au defaut" onClick={() => saveSwitch(name, null)}>
                <RotateCcw size={10} strokeWidth={2} />
              </Btn>
            </div>
          )
        })}
      </div>
      </>}
    </div>
  )
}
