// EnvPanel.tsx: "Settings avances environnement" (2026-10-23), bottom of the Avance tab.
// The school's farm config (engine limits.config: teams and their Shares), used very rarely.
// Locked: type "Understand" then the password; the backend checks both on every call
// (features/render/farm_limits.py). The password is in open source code: a guard against mistakes.
// Writes go to the network folder only if it holds the very file the engine serves; backup first.

import { useState } from 'react'
import { toast } from 'sonner'
import { Lock, Plus, RefreshCcw, ShieldAlert, Trash2 } from 'lucide-react'
import { api } from '../../api/client'
import type { RenderEnvState, RenderEnvUnlock, RenderSettingsResponse, RenderShareRule } from '../../api/client'
import { Banner, Row, Section, btn, disabledIf, errMsg, hint, input, useTr, warnText } from './renderUi'

const RENDER_TAG = 'husk'      // FLUX's commands (backend farm_limits.RENDER_TAG)
const DEFAULT_SHARE = 'default'
type TeamRow = { name: string; nominal: number; cap: number }   // percents in the UI

function rowsOf(state: RenderEnvState | null): TeamRow[] {
  const shares = state?.engine_shares
  const tag = shares ? (shares[RENDER_TAG] ? RENDER_TAG : Object.keys(shares)[0]) : undefined
  const byTeam: Record<string, RenderShareRule> = (tag && shares?.[tag]) || {}
  const pct = (x: number | null) => Math.round((x ?? 0) * 1000) / 10
  return Object.entries(byTeam).map(([name, r]) => ({ name, nominal: pct(r.nominal), cap: pct(r.cap) }))
}

export function EnvPanel({ project, configDir, onDirSaved }: {
  project: string; configDir: string; onDirSaved: (r: RenderSettingsResponse) => void
}) {
  const { tr } = useTr()
  const [open, setOpen] = useState(false)
  const [phrase, setPhrase] = useState('')
  const [password, setPassword] = useState('')
  const [unlock, setUnlock] = useState<RenderEnvUnlock | null>(null)   // memory only, never stored
  const [state, setState] = useState<RenderEnvState | null>(null)
  const [rows, setRows] = useState<TeamRow[]>([])
  const [dir, setDir] = useState(configDir)
  const [busy, setBusy] = useState(false)
  const [written, setWritten] = useState(false)

  const load = async (u: RenderEnvUnlock) => {
    const s = await api.renderEnvState(project, u)
    setState(s); setRows(rowsOf(s)); setDir(s.config_dir)
  }
  const doUnlock = async () => {
    const u = { phrase, password }
    setBusy(true)
    try { await load(u); setUnlock(u); setPassword('') }
    catch (e) { toast.error(errMsg(e)) }
    finally { setBusy(false) }
  }
  const lock = () => { setUnlock(null); setState(null); setPhrase(''); setPassword(''); setWritten(false); setOpen(false) }

  const saveDir = async () => {
    if (!unlock) return
    setBusy(true)
    try { onDirSaved(await api.renderSaveSettings(project, { engine_config_dir: dir.trim() })); await load(unlock) }
    catch (e) { toast.error(errMsg(e)) }
    finally { setBusy(false) }
  }
  const setRow = (i: number, patch: Partial<TeamRow>) => setRows(rs => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  const nominalSum = Math.round(rows.reduce((a, r) => a + r.nominal, 0) * 10) / 10
  const tags = state?.engine_shares ? Object.keys(state.engine_shares).sort() : []

  const write = async () => {
    if (!unlock) return
    if (!window.confirm(tr(
      "Ecrire ces equipes dans le limits.config de la farm ? Cela change la repartition de la farm pour toute l'ecole (une sauvegarde est faite avant).",
      "Write these teams into the farm limits.config? It changes the farm split for the whole school (a backup is made first)."))) return
    const teams: Record<string, RenderShareRule> = {}
    for (const r of rows) teams[r.name.trim()] = { nominal: r.nominal / 100, cap: r.cap / 100 }
    setBusy(true)
    try {
      const r = await api.renderEnvShares(project, unlock, teams)
      toast.success(tr('limits.config ecrit', 'limits.config written'), { description: tr(`Sauvegarde : ${r.backup}`, `Backup: ${r.backup}`) })
      setWritten(true)
    } catch (e) { toast.error(errMsg(e)) }
    finally { setBusy(false) }
  }
  const reload = async () => {
    if (!unlock) return
    setBusy(true)
    try {
      await api.renderEnvReload(project, unlock)
      toast.success(tr('Le moteur a relu limits.config', 'The engine reread limits.config'))
      setWritten(false); await load(unlock)
    } catch (e) { toast.error(errMsg(e)) }
    finally { setBusy(false) }
  }

  if (!open) {
    return (
      <div>
        <button type="button" style={btn()} onClick={() => setOpen(true)}>
          <ShieldAlert size={12} />{tr('Settings avances environnement', 'Advanced environment settings')}
        </button>
      </div>
    )
  }

  if (!unlock) {
    return (
      <Section title={tr('Environnement de la farm (ecole)', 'Farm environment (school)')}>
        <Banner color="var(--warn)">
          {tr("Ces reglages modifient la vraie config de la farm de l'ecole (equipes, parts). A ne toucher que tres rarement.",
            "These settings change the school's real farm config (teams, shares). Touch very rarely.")}
        </Banner>
        <Row label={tr('Ecrire Understand', 'Type Understand')}>
          <input style={input} value={phrase} onChange={e => setPhrase(e.target.value)} placeholder="Understand" autoComplete="off" />
        </Row>
        <Row label={tr('Mot de passe', 'Password')}>
          <input style={input} type="password" value={password} onChange={e => setPassword(e.target.value)} autoComplete="off"
            onKeyDown={e => { if (e.key === 'Enter') void doUnlock() }} />
        </Row>
        <div style={{ display: 'flex', gap: 8 }}>
          <button type="button" style={{ ...btn(true), ...disabledIf(busy || phrase !== 'Understand' || !password) }} onClick={() => void doUnlock()}>
            {tr('Deverrouiller', 'Unlock')}
          </button>
          <button type="button" style={btn()} onClick={lock}>{tr('Fermer', 'Close')}</button>
        </div>
      </Section>
    )
  }

  return (
    <Section title={tr('Environnement de la farm (ecole)', 'Farm environment (school)')}>
      <Banner color="var(--err)">
        {tr("Deverrouille : les ecritures changent la farm pour toute l'ecole.", 'Unlocked: writes change the farm for the whole school.')}
      </Banner>
      <Row label={tr('Dossier de config du moteur (reseau)', 'Engine config folder (network)')}
        help={tr('Le dossier qui contient limits.config. FLUX refuse d\'ecrire si ce n\'est pas le fichier que sert le moteur.',
          'The folder holding limits.config. FLUX refuses to write unless it is the file the engine serves.')}>
        <div style={{ display: 'flex', gap: 6 }}>
          <input style={input} value={dir} onChange={e => setDir(e.target.value)} placeholder="\\\\serveur\\tractor\\config" />
          <button type="button" style={{ ...btn(), ...disabledIf(busy || dir.trim() === (state?.config_dir ?? '')) }} onClick={() => void saveDir()}>
            {tr('Enregistrer', 'Save')}
          </button>
        </div>
        {state?.folder_ok
          ? <div style={{ ...hint, color: 'var(--ok)', marginTop: 4 }}>{tr('Meme fichier que le moteur', 'Same file as the engine')}</div>
          : <div style={{ ...warnText, marginTop: 4 }}>{state?.folder_error ?? tr('Dossier non verifie', 'Folder not checked')}</div>}
      </Row>

      <Row label={tr('Equipes et parts de la farm', 'Teams and farm shares')}
        help={tr(`Nominal = part quand tout le monde rend, plafond = maximum si les autres ne rendent pas. Applique a : ${tags.join(', ') || '?'}. "${DEFAULT_SHARE}" = toutes les equipes inconnues.`,
          `Nominal = share when everyone renders, cap = maximum when others do not. Applied to: ${tags.join(', ') || '?'}. "${DEFAULT_SHARE}" = every unknown team.`)}>
        {!state?.engine_shares && <div style={warnText}>{tr('Moteur injoignable : parts inconnues', 'Engine unreachable: shares unknown')}</div>}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 90px 90px 28px', gap: 6, alignItems: 'center', fontSize: 11.5 }}>
          <span style={hint}>{tr('Equipe (projet Tractor)', 'Team (Tractor project)')}</span>
          <span style={hint}>Nominal %</span><span style={hint}>{tr('Plafond %', 'Cap %')}</span><span />
          {rows.map((r, i) => (
            <div key={i} style={{ display: 'contents' }}>
              <input style={input} value={r.name} disabled={r.name === DEFAULT_SHARE} onChange={e => setRow(i, { name: e.target.value })} />
              <input style={input} type="number" min={0} max={100} value={r.nominal} onChange={e => setRow(i, { nominal: Number(e.target.value) })} />
              <input style={input} type="number" min={1} max={100} value={r.cap} onChange={e => setRow(i, { cap: Number(e.target.value) })} />
              {r.name === DEFAULT_SHARE ? <span /> : (
                <button type="button" style={btn(false, true)} title={tr('Retirer', 'Remove')} onClick={() => setRows(rs => rs.filter((_, j) => j !== i))}>
                  <Trash2 size={11} />
                </button>
              )}
            </div>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 6 }}>
          <button type="button" style={btn()} onClick={() => setRows(rs => [...rs.filter(r => r.name !== DEFAULT_SHARE), { name: '', nominal: 0, cap: 99 }, ...rs.filter(r => r.name === DEFAULT_SHARE)])}>
            <Plus size={11} />{tr('Equipe', 'Team')}
          </button>
          <span style={nominalSum > 100 ? warnText : hint}>{tr(`Somme nominale : ${nominalSum} %`, `Nominal total: ${nominalSum} %`)}</span>
        </div>
      </Row>

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <button type="button" style={{ ...btn(true, true), ...disabledIf(busy || !state?.folder_ok || !rows.length) }} onClick={() => void write()}>
          {tr('Ecrire limits.config', 'Write limits.config')}
        </button>
        <button type="button" style={{ ...btn(), ...disabledIf(busy) }} onClick={() => void reload()}
          title={tr('Le moteur relit limits.config (sinon les changements ne s\'appliquent pas)', 'The engine rereads limits.config (else changes do not apply)')}>
          <RefreshCcw size={11} />{tr('Recharger le moteur', 'Reload the engine')}
        </button>
        <button type="button" style={btn()} onClick={lock}><Lock size={11} />{tr('Verrouiller', 'Lock')}</button>
      </div>
      {written && <div style={warnText}>{tr('Ecrit : recharger le moteur pour appliquer.', 'Written: reload the engine to apply.')}</div>}
    </Section>
  )
}
