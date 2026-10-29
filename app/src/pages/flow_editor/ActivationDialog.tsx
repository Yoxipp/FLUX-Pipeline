// ActivationDialog.tsx — "Activer" (03_EDITEUR §5, 01 §8): three lines, one dot each, on the
// frozen version `current`: (1) 0 error ; (2) warnings, one "lu" box each (sent with the
// request, kept for this version) ; (3) dry run: button then report, "reussi sur vN", stale as
// soon as a newer version exists. Activer is enabled when the three are green; with a `!`
// node it is a SlideToConfirm (an active flow runs unattended). Rights: perso = TD, team /
// project = Team TD, else greyed with the reason. Deactivate when the flow is active.
// GET /flows/{name}/activation is the truth; the dry run is POST /run {dry_run, version}.
// A page flow picks the button whose branch the dry run plays (page defaults as values, T1).

import { useCallback, useEffect, useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { CircleCheck, CircleX, FlaskConical, TriangleAlert, X } from 'lucide-react'
import { toast } from 'sonner'
import { flowsApi } from '../../api/flows'
import { SlideToConfirm } from '../../components/shared/SlideToConfirm'
import { Btn } from '../../components/shared/ui'
import type { PageStart } from './PageRunDialog'
import type { ActivationGate, FlowScope, FlowState, RunRecord } from './types'
import { useTr } from './useTr'

const v3 = (n: number | null | undefined) => `v${String(n ?? 0).padStart(3, '0')}`

function Dot({ ok, warn }: { ok: boolean; warn?: boolean }) {
  if (ok) return <CircleCheck size={14} color="var(--ok)" style={{ flexShrink: 0 }} />
  return warn ? <TriangleAlert size={14} color="var(--warn)" style={{ flexShrink: 0 }} /> : <CircleX size={14} color="var(--err)" style={{ flexShrink: 0 }} />
}

export function ActivationDialog({ open, name, scope, project, blocked, dirty, starts = [], onClose, onChanged }: {
  open: boolean
  name: string
  scope: FlowScope
  project?: string
  blocked?: string                 // why the user cannot (de)activate (rights, shipped, legacy)
  dirty: boolean
  starts?: PageStart[]             // InputsPageReader nodes with buttons of the open document
  onClose: () => void
  onChanged: (state: FlowState) => void
}) {
  const { tr, lang } = useTr()
  const [gate, setGate] = useState<ActivationGate | null>(null)
  const [read, setRead] = useState<Record<string, boolean>>({})
  const [dry, setDry] = useState<RunRecord | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [pick, setPick] = useState('')     // `${node}|${button}` played by the dry run of a page flow

  const load = useCallback(() => {
    flowsApi.activation(name, scope, project)
      .then(g => { setGate(g); setError(null) })
      .catch((e: Error) => setError(e.message))
  }, [name, scope, project])

  useEffect(() => { if (open) { setGate(null); setDry(null); setRead({}); load() } }, [open, load])
  useEffect(() => {
    if (open) setPick(starts[0] ? `${starts[0].node}|${starts[0].buttons[0].id}` : '')
  }, [open, starts])

  const key = (w: { code: string; node: string | null; port: string | null }) => `${w.code}|${w.node ?? ''}|${w.port ?? ''}`
  const allRead = !!gate && gate.warnings.every(w => w.acked || read[key(w)])
  const ready = !!gate && !gate.legacy && gate.version > 0 && gate.errors.length === 0 && gate.dry_run.ok && allRead

  const dryRun = useCallback(async () => {
    if (!gate) return
    setBusy(true)
    try {
      const [event, button] = pick ? pick.split('|') : []
      const { run_id } = await flowsApi.run(name, { scope, project, dry_run: true, version: gate.version,
                                                     ...(button ? { event, button } : {}) })
      let rec: RunRecord | null = null
      for (let i = 0; i < 600; i++) {
        rec = await flowsApi.getRun(run_id, project)
        if (rec.status !== 'queued' && rec.status !== 'running') break
        await new Promise(r => setTimeout(r, 250))
      }
      setDry(rec)
      // dry_run_ok is written when the run closes: read the gate again (twice at most).
      for (let i = 0; i < 2; i++) {
        const g = await flowsApi.activation(name, scope, project)
        setGate(g)
        if (g.dry_run.ok || rec?.status !== 'ok') break
        await new Promise(r => setTimeout(r, 300))
      }
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusy(false)
    }
  }, [gate, name, scope, project, pick])

  const activate = useCallback(() => {
    if (!gate) return
    setBusy(true)
    const acked = gate.warnings.map(w => ({ code: w.code, node: w.node, port: w.port }))
    flowsApi.activate(name, scope, acked, project)
      .then(state => { toast.success(tr(`${name} actif (${v3(state.active_version)})`, `${name} active (${v3(state.active_version)})`)); onChanged(state); onClose() })
      .catch((e: Error) => { toast.error(e.message); load() })
      .finally(() => setBusy(false))
  }, [gate, name, scope, project, tr, onChanged, onClose, load])

  const deactivate = useCallback(() => {
    setBusy(true)
    flowsApi.deactivate(name, scope, project)
      .then(state => { toast.info(tr(`${name} desactive`, `${name} deactivated`)); onChanged(state); load() })
      .catch((e: Error) => toast.error(e.message))
      .finally(() => setBusy(false))
  }, [name, scope, project, tr, onChanged, load])

  const msg = (i: { message_fr: string; message_en: string }) => lang === 'en' ? i.message_en : i.message_fr
  const line = { display: 'flex', alignItems: 'flex-start', gap: 8, padding: '8px 0', borderBottom: '1px solid var(--rule)', fontSize: 12 } as const

  return (
    <Dialog.Root open={open} onOpenChange={o => { if (!o) onClose() }}>
      <Dialog.Portal>
        <Dialog.Overlay className="flow-dialog-overlay" />
        <Dialog.Content className="flow-dialog" aria-describedby={undefined} style={{ width: 520 }}>
          <div className="flow-dialog-heading">
            <Dialog.Title>{tr(`Activer ${name}`, `Activate ${name}`)}</Dialog.Title>
            <Dialog.Close aria-label={tr('Fermer', 'Close')}><X size={15} /></Dialog.Close>
          </div>
          {error && <div style={{ fontSize: 12, color: 'var(--err)' }}>{error}</div>}
          {gate && (
            <>
              <div style={{ fontSize: 11.5, color: 'var(--ink-3)', marginBottom: 4 }}>
                {gate.version
                  ? tr(`Version enregistree ${v3(gate.version)}`, `Saved version ${v3(gate.version)}`)
                    + (gate.active ? tr(` ; actif : ${v3(gate.active_version)}`, `; active: ${v3(gate.active_version)}`) : tr(' ; inactif', '; inactive'))
                  : gate.reason}
                {dirty && <span className="tag" style={{ marginLeft: 6 }}>{tr('modifie : Enregistrer et incrementer d\'abord', 'modified: Save and increment first')}</span>}
              </div>
              {gate.legacy && <div style={{ fontSize: 12, color: 'var(--ink-2)' }}>{tr('Un flow legacy_* ne s\'active pas (publish v1 jusqu\'a P8).', 'A legacy_* flow does not activate (v1 publish until P8).')}</div>}

              <div style={line}>
                <Dot ok={gate.errors.length === 0} />
                <div style={{ flex: 1 }}>
                  <div style={{ color: 'var(--ink)' }}>{gate.errors.length === 0 ? tr('Aucune erreur', 'No error') : tr(`${gate.errors.length} erreur(s) : corrige puis incremente`, `${gate.errors.length} error(s): fix then increment`)}</div>
                  {gate.errors.slice(0, 5).map((i, n) => <div key={n} style={{ color: 'var(--ink-3)', fontSize: 11 }}>{i.node && <span className="tag">{i.node}</span>} {msg(i)}</div>)}
                </div>
              </div>

              <div style={line}>
                <Dot ok={allRead} warn />
                <div style={{ flex: 1 }}>
                  <div style={{ color: 'var(--ink)' }}>
                    {gate.warnings.length === 0 ? tr('Aucun avertissement', 'No warning') : tr(`${gate.warnings.length} avertissement(s) a lire`, `${gate.warnings.length} warning(s) to read`)}
                  </div>
                  {gate.warnings.map(w => (
                    <label key={key(w)} style={{ display: 'flex', alignItems: 'center', gap: 6, color: 'var(--ink-2)', fontSize: 11, marginTop: 3, cursor: 'pointer' }}>
                      <input type="checkbox" checked={w.acked || !!read[key(w)]} disabled={w.acked}
                             onChange={e => setRead(r => ({ ...r, [key(w)]: e.target.checked }))} />
                      {w.node && <span className="tag">{w.node}</span>} {msg(w)} <span className="tag">{w.code}</span>
                    </label>
                  ))}
                </div>
              </div>

              <div style={line}>
                <Dot ok={gate.dry_run.ok} />
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--ink)' }}>
                    <span style={{ flex: 1 }}>
                      {gate.dry_run.ok ? tr(`Essai a blanc reussi sur ${v3(gate.version)}`, `Dry run passed on ${v3(gate.version)}`)
                        : gate.dry_run.version ? tr(`Essai perime (${v3(gate.dry_run.version)}) : relance sur ${v3(gate.version)}`, `Stale dry run (${v3(gate.dry_run.version)}): run it on ${v3(gate.version)}`)
                        : tr('Essai a blanc a faire', 'Dry run to do')}
                    </span>
                    {starts.length > 0 && (
                      <select className="flow-dialog-input" style={{ width: 'auto', maxWidth: 170, marginTop: 0 }} value={pick}
                              title={tr('Bouton de la page joue par l\'essai (valeurs par defaut de la page)', 'Page button played by the dry run (page default values)')}
                              onChange={e => setPick(e.target.value)}>
                        {starts.map(s => s.buttons.map(b => (
                          <option key={`${s.node}|${b.id}`} value={`${s.node}|${b.id}`}>{starts.length > 1 ? `${s.page} > ` : ''}{b.label}</option>
                        )))}
                      </select>
                    )}
                    <Btn sm ghost disabled={busy || !gate.version || gate.legacy} onClick={dryRun}>
                      <FlaskConical size={12} /> {busy ? tr('Essai...', 'Running...') : tr('Lancer l\'essai', 'Run the dry run')}
                    </Btn>
                  </div>
                  {dry && dry.status !== 'ok' && <div style={{ color: 'var(--err)', fontSize: 11, marginTop: 3 }}>{dry.error ?? dry.status}</div>}
                  {dry && (
                    <div style={{ maxHeight: 140, overflowY: 'auto', marginTop: 4 }}>
                      {dry.report.map((r, n) => (
                        <div key={n} style={{ color: 'var(--ink-3)', fontSize: 11 }}>{r.node && <span className="tag">{r.node}</span>} {r.text_fr}</div>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              <div style={{ marginTop: 12 }}>
                {blocked
                  ? <div style={{ fontSize: 11.5, color: 'var(--ink-3)' }}>{blocked}</div>
                  : gate.destructive.length > 0 && ready
                    ? <SlideToConfirm label={tr(`Glisse pour activer (${gate.destructive.length} node(s) destructif(s))`, `Slide to activate (${gate.destructive.length} destructive node(s))`)}
                                      tone="danger" width="fill" onConfirm={activate} />
                    : null}
              </div>
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 6, marginTop: 8 }}>
                {gate.active && !blocked && <Btn sm ghost disabled={busy} onClick={deactivate}>{tr('Desactiver', 'Deactivate')}</Btn>}
                <Btn sm ghost onClick={onClose}>{tr('Fermer', 'Close')}</Btn>
                {!blocked && gate.destructive.length === 0 && (
                  <Btn sm primary disabled={!ready || busy} onClick={activate}>{tr(`Activer ${v3(gate.version)}`, `Activate ${v3(gate.version)}`)}</Btn>
                )}
              </div>
            </>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
