// BridgesDialog.tsx — Flows > Bridges (P6c, 01 §12): the extension bridges of
// CONFIG/extensions/bridges/ (a soft added without rebuilding FLUX). One row per bridge:
// manifest, errors (a broken bridge is shown alone, the others load), exe found, install
// state on this machine. Installer / Desinstaller act on this machine; a conflict (a file
// FLUX did not write) changes nothing until "Remplacer" (backup made). "Creer les nodes"
// (Team TD) writes <prefix>_instance and <prefix>_publish into the team scope.

import { useCallback, useEffect, useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { CircleCheck, CircleX, Plug, RefreshCw, TriangleAlert, X } from 'lucide-react'
import { toast } from 'sonner'
import { flowsApi } from '../../api/flows'
import { Btn } from '../../components/shared/ui'
import type { BridgeInfo, BridgeInstallState } from './types'
import { useTr } from './useTr'

export function BridgesDialog({ open, canCreate, onClose, onNodes }: {
  open: boolean
  canCreate: boolean          // Team TD: create the nodes of a bridge
  onClose: () => void
  onNodes: () => void         // nodes written: reload the catalogue and the list
}) {
  const { tr } = useTr()
  const [data, setData] = useState<{ dir: string | null; bridges: BridgeInfo[] } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [conflict, setConflict] = useState<Record<string, string[]>>({})
  const [sceneExt, setSceneExt] = useState<Record<string, string>>({})

  const load = useCallback(() => {
    flowsApi.bridges().then(d => { setData(d); setError(null) }).catch((e: Error) => setError(e.message))
  }, [])

  useEffect(() => { if (open) { setConflict({}); load() } }, [open, load])

  const stateLabel = (s: BridgeInstallState): string => ({
    installed: tr('installe', 'installed'), absent: tr('non installe', 'not installed'),
    partial: tr('incomplet', 'partial'), outdated: tr('a mettre a jour', 'to update'),
    conflict: tr('conflit', 'conflict'), error: tr('erreur', 'error'),
  })[s]

  const install = (b: BridgeInfo, overwrite: boolean) => {
    setBusy(b.soft)
    flowsApi.installBridge(b.soft, overwrite)
      .then(r => {
        if (r.success) { toast.success(r.message); setConflict(c => ({ ...c, [b.soft]: [] })) }
        else if (r.conflicts?.length) setConflict(c => ({ ...c, [b.soft]: r.conflicts ?? [] }))
        else toast.error(r.message)
        load()
      })
      .catch((e: Error) => toast.error(e.message))
      .finally(() => setBusy(null))
  }

  const uninstall = (b: BridgeInfo) => {
    setBusy(b.soft)
    flowsApi.uninstallBridge(b.soft)
      .then(r => { (r.kept?.length ? toast.warning : toast.success)(r.message); load() })
      .catch((e: Error) => toast.error(e.message))
      .finally(() => setBusy(null))
  }

  const createNodes = (b: BridgeInfo) => {
    const ext = (sceneExt[b.soft] ?? '').trim() || '.scene'
    setBusy(b.soft)
    flowsApi.bridgeFlows(b.soft, ext.startsWith('.') ? ext : `.${ext}`)
      .then(r => {
        const written = r.flows.filter(f => f.status === 'written').map(f => f.name)
        const kept = r.flows.filter(f => f.status === 'kept').map(f => f.name)
        if (written.length) toast.success(tr(`Nodes crees : ${written.join(', ')}`, `Nodes created: ${written.join(', ')}`))
        if (kept.length) toast.info(tr(`Deja presents, gardes : ${kept.join(', ')}`, `Already there, kept: ${kept.join(', ')}`))
        onNodes()
      })
      .catch((e: Error) => toast.error(e.message))
      .finally(() => setBusy(null))
  }

  const row = { padding: '10px 0', borderBottom: '1px solid var(--rule)', fontSize: 12 } as const
  const small = { fontSize: 11, color: 'var(--ink-3)' } as const

  return (
    <Dialog.Root open={open} onOpenChange={o => { if (!o) onClose() }}>
      <Dialog.Portal>
        <Dialog.Overlay className="flow-dialog-overlay" />
        <Dialog.Content className="flow-dialog" aria-describedby={undefined} style={{ width: 620 }}>
          <div className="flow-dialog-heading">
            <Dialog.Title>{tr('Bridges d\'extension', 'Extension bridges')}</Dialog.Title>
            <button type="button" className="flow-tool" onClick={load} title={tr('Relire le dossier', 'Read the folder again')}><RefreshCw size={13} /></button>
            <Dialog.Close aria-label={tr('Fermer', 'Close')}><X size={15} /></Dialog.Close>
          </div>
          <div style={small}>
            {tr('Un logiciel ajoute sans recompiler FLUX : bridge.yml + script cote logiciel dans ', 'A software added without rebuilding FLUX: bridge.yml + software-side script in ')}
            <span className="tag">{data?.dir ?? 'CONFIG/extensions/bridges'}</span>
            {tr(' (exemple : docs/development/FLOWS_BRIDGE_3DSMAX.md).', ' (example: docs/development/FLOWS_BRIDGE_3DSMAX.md).')}
          </div>
          {error && <div style={{ fontSize: 12, color: 'var(--err)', marginTop: 6 }}>{error}</div>}
          {data && data.bridges.length === 0 && (
            <div style={{ ...small, padding: '14px 0' }}>{tr('Aucun bridge d\'extension.', 'No extension bridge.')}</div>
          )}
          <div style={{ maxHeight: 460, overflowY: 'auto', marginTop: 6 }}>
            {data?.bridges.map(b => {
              const m = b.manifest
              const st = b.install?.state
              const files = conflict[b.soft] ?? []
              return (
                <div key={b.soft} style={row}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    {b.ok ? <Plug size={14} /> : <CircleX size={14} color="var(--err)" />}
                    <span style={{ color: 'var(--ink)', fontWeight: 600 }}>{m?.label ?? b.soft}</span>
                    {m && <span className="tag">{m.prefix}</span>}
                    {m && <span className="tag">{m.transport}</span>}
                    {m && m.transport !== 'file_mailbox' && <span className="tag">{m.port_range[0]}..{m.port_range[0] + m.port_range[1] - 1}</span>}
                    <div style={{ flex: 1 }} />
                    {st && (
                      <span className="tag" title={b.install?.target ?? ''}>
                        {st === 'installed' ? <CircleCheck size={11} color="var(--ok)" /> : st === 'conflict' || st === 'error' ? <TriangleAlert size={11} color="var(--warn)" /> : null}
                        {' '}{stateLabel(st)}
                      </span>
                    )}
                  </div>
                  {b.errors.map((e, n) => <div key={n} style={{ color: 'var(--err)', fontSize: 11, marginTop: 3 }}>{e}</div>)}
                  {b.ok && (
                    <>
                      <div style={{ ...small, marginTop: 3 }}>
                        {b.exe ? tr(`Logiciel : ${b.exe}`, `Software: ${b.exe}`) : tr('Logiciel non trouve (exe_hints)', 'Software not found (exe_hints)')}
                        {b.install?.target && <> ; {tr('dossier', 'folder')} {b.install.target}</>}
                      </div>
                      {b.install?.error && <div style={{ color: 'var(--err)', fontSize: 11, marginTop: 3 }}>{b.install.error}</div>}
                      {files.length > 0 && (
                        <div style={{ color: 'var(--warn)', fontSize: 11, marginTop: 3 }}>
                          {tr(`Fichiers differents deja presents : ${files.join(', ')}. Remplacer les sauvegarde avant.`,
                              `Different files already there: ${files.join(', ')}. Replace backs them up first.`)}
                        </div>
                      )}
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 6 }}>
                        {files.length > 0
                          ? <Btn sm disabled={busy === b.soft} onClick={() => install(b, true)}>{tr('Remplacer (sauvegarde)', 'Replace (backup)')}</Btn>
                          : <Btn sm disabled={busy === b.soft || st === 'installed' || st === 'error'} onClick={() => install(b, false)}>
                              {st === 'outdated' ? tr('Mettre a jour', 'Update') : tr('Installer', 'Install')}
                            </Btn>}
                        <Btn sm ghost disabled={busy === b.soft || st === 'absent' || st === 'error'} onClick={() => uninstall(b)}>{tr('Desinstaller', 'Uninstall')}</Btn>
                        <div style={{ flex: 1 }} />
                        <input
                          value={sceneExt[b.soft] ?? ''} placeholder=".max" disabled={!canCreate}
                          onChange={e => setSceneExt(x => ({ ...x, [b.soft]: e.target.value }))}
                          title={tr('Extension des scenes du logiciel (modele de publish)', 'Scene extension of the software (publish template)')}
                          style={{ width: 64, fontSize: 11, padding: '3px 6px', background: 'var(--paper-2)', border: '1px solid var(--rule-2)', borderRadius: 4, color: 'var(--ink)' }}
                        />
                        <Btn sm ghost disabled={!canCreate || busy === b.soft} onClick={() => createNodes(b)}
                             title={canCreate ? tr(`Ecrit ${m?.prefix}_instance et ${m?.prefix}_publish dans les flows d'equipe`, `Writes ${m?.prefix}_instance and ${m?.prefix}_publish into the team flows`) : tr('Case Team TD requise', 'Team TD box required')}>
                          {tr('Creer les nodes', 'Create the nodes')}
                        </Btn>
                      </div>
                    </>
                  )}
                </div>
              )
            })}
          </div>
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 10 }}>
            <Btn sm ghost onClick={onClose}>{tr('Fermer', 'Close')}</Btn>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
