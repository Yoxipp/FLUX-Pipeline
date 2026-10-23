// VersionsDialog.tsx — versions of the open flow (03_EDITEUR §6): `v003 | date | artiste |
// +2 nodes -1 lien` (diff with the previous version, computed here), tags "courante" and
// "active". Voir = opens the frozen version read-only; Revenir a cette version = creates
// v(max+1) identical (B7: nothing is lost, so no slider). Historique tab: history.jsonl.

import { useEffect, useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { flowsApi } from '../../api/flows'
import { Btn } from '../../components/shared/ui'
import type { FlowDoc, FlowScope, VersionList } from './types'
import { useTr } from './useTr'

const DIFF_MAX = 20   // versions whose diff is computed (one GET each)

const vname = (n: number) => `v${String(n).padStart(3, '0')}`
const when = (iso: string) => iso ? iso.replace('T', ' ').slice(0, 16) : ''

export function diffDocs(a: FlowDoc | null, b: FlowDoc): { nodes: [number, number]; links: [number, number] } {
  const an = new Set(Object.keys(a?.nodes ?? {})), bn = new Set(Object.keys(b.nodes ?? {}))
  const key = (l: { from: string; to: string }) => `${l.from}>${l.to}`
  const al = new Set((a?.links ?? []).map(key)), bl = new Set((b.links ?? []).map(key))
  const count = (x: Set<string>, y: Set<string>) => [...x].filter(k => !y.has(k)).length
  return { nodes: [count(bn, an), count(an, bn)], links: [count(bl, al), count(al, bl)] }
}

export function VersionsDialog({ open, name, scope, project, canRevert, onView, onRevert, onClose }: {
  open: boolean
  name: string
  scope: FlowScope
  project?: string
  canRevert?: string            // why Revenir is greyed (undefined = allowed)
  onView: (version: number) => void
  onRevert: (version: number) => void
  onClose: () => void
}) {
  const { tr, lang } = useTr()
  const [list, setList] = useState<VersionList | null>(null)
  const [diffs, setDiffs] = useState<Record<number, string>>({})
  const [tab, setTab] = useState<'versions' | 'history'>('versions')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    let alive = true
    setList(null); setDiffs({}); setError(null)
    flowsApi.versions(name, scope, project)
      .then(async l => {
        if (!alive) return
        setList(l)
        const nums = l.versions.map(v => v.version).slice(0, DIFF_MAX + 1)
        const docs = await Promise.all(nums.map(v => flowsApi.get(name, { scope, project, version: v }).then(r => r.flow).catch(() => null)))
        if (!alive) return
        const out: Record<number, string> = {}
        nums.forEach((v, i) => {
          const cur = docs[i]
          if (!cur || i === DIFF_MAX) return
          const d = diffDocs(i + 1 < docs.length ? docs[i + 1] : null, cur)
          const parts = [
            d.nodes[0] && `+${d.nodes[0]} ${tr('nodes', 'nodes')}`, d.nodes[1] && `-${d.nodes[1]} ${tr('nodes', 'nodes')}`,
            d.links[0] && `+${d.links[0]} ${tr('liens', 'links')}`, d.links[1] && `-${d.links[1]} ${tr('liens', 'links')}`,
          ].filter(Boolean)
          out[v] = parts.length ? parts.join(' ') : tr('parametres', 'parameters')
        })
        setDiffs(out)
      })
      .catch(e => { if (alive) setError(String(e?.message ?? e)) })
    return () => { alive = false }
  }, [open, name, scope, project])  // eslint-disable-line react-hooks/exhaustive-deps

  const kinds: Record<string, [string, string]> = {
    save: ['enregistre', 'saved'], increment: ['version figee', 'version frozen'], revert: ['retour a une version', 'reverted'],
    activate: ['active', 'activated'], deactivate: ['desactive', 'deactivated'], migrate: ['migre de v1', 'migrated from v1'],
    delete: ['supprime', 'deleted'], copy: ['copie', 'copied'],
  }
  const tabStyle = (on: boolean): React.CSSProperties => ({
    fontSize: 11.5, padding: '3px 8px', cursor: 'pointer', color: on ? 'var(--ink)' : 'var(--ink-3)',
    borderBottom: `2px solid ${on ? 'var(--accent)' : 'transparent'}`,
  })

  return (
    <Dialog.Root open={open} onOpenChange={o => { if (!o) onClose() }}>
      <Dialog.Portal>
        <Dialog.Overlay className="flow-dialog-overlay" />
        <Dialog.Content className="flow-dialog" aria-describedby={undefined} style={{ width: 620, top: '12%' }}>
          <div className="flow-dialog-heading">
            <Dialog.Title>{tr(`Versions de ${name}`, `Versions of ${name}`)}</Dialog.Title>
            <Dialog.Close aria-label={tr('Fermer', 'Close')}><X size={15} /></Dialog.Close>
          </div>
          <div style={{ display: 'flex', gap: 4, borderBottom: '1px solid var(--rule)', marginBottom: 6 }}>
            <span style={tabStyle(tab === 'versions')} onClick={() => setTab('versions')}>{tr('Versions', 'Versions')}</span>
            <span style={tabStyle(tab === 'history')} onClick={() => setTab('history')}>{tr('Historique', 'History')}</span>
          </div>
          {error && <div style={{ fontSize: 11.5, color: 'var(--err)' }}>{error}</div>}
          {!list && !error && <div className="flow-dialog-hint">{tr('Chargement…', 'Loading…')}</div>}
          <div style={{ maxHeight: 360, overflowY: 'auto', fontSize: 11.5 }}>
            {list && tab === 'versions' && list.versions.length === 0 && (
              <div className="flow-dialog-hint">{tr('Aucune version figee (Enregistrer et incrementer en cree une).', 'No frozen version (Save and increment creates one).')}</div>
            )}
            {list && tab === 'versions' && list.versions.map(v => (
              <div key={v.version} style={{ display: 'grid', gridTemplateColumns: '52px 112px 90px 1fr auto', gap: 8, alignItems: 'center', padding: '4px 0', borderBottom: '1px solid var(--rule)' }}>
                <span style={{ fontWeight: 600, color: 'var(--ink)' }}>{vname(v.version)}</span>
                <span style={{ color: 'var(--ink-3)' }}>{when(v.at)}</span>
                <span style={{ color: 'var(--ink-2)', overflow: 'hidden', textOverflow: 'ellipsis' }}>{v.user ?? ''}</span>
                <span style={{ display: 'flex', gap: 4, alignItems: 'center', minWidth: 0 }}>
                  <span style={{ color: 'var(--ink-3)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{diffs[v.version] ?? ''}</span>
                  {v.version === list.state.current && <span className="tag">{tr('courante', 'current')}</span>}
                  {list.state.active && v.version === list.state.active_version && <span className="tag">{tr('active', 'active')}</span>}
                </span>
                <span style={{ display: 'flex', gap: 4 }}>
                  <Btn sm ghost onClick={() => onView(v.version)}>{tr('Voir', 'View')}</Btn>
                  <Btn sm ghost disabled={!!canRevert} title={canRevert ?? tr(`Cree ${vname((list.versions[0]?.version ?? 0) + 1)} identique a ${vname(v.version)}`, `Creates ${vname((list.versions[0]?.version ?? 0) + 1)} identical to ${vname(v.version)}`)}
                       onClick={() => onRevert(v.version)}>{tr('Revenir', 'Revert')}</Btn>
                </span>
              </div>
            ))}
            {list && tab === 'history' && list.history.length === 0 && (
              <div className="flow-dialog-hint">{tr('Pas d\'historique (les flows perso n\'en gardent pas).', 'No history (personal flows keep none).')}</div>
            )}
            {list && tab === 'history' && list.history.map((h, k) => (
              <div key={k} style={{ display: 'grid', gridTemplateColumns: '112px 90px 1fr', gap: 8, padding: '3px 0', borderBottom: '1px solid var(--rule)' }}>
                <span style={{ color: 'var(--ink-3)' }}>{when(h.at)}</span>
                <span style={{ color: 'var(--ink-2)' }}>{h.user ?? '?'}</span>
                <span style={{ color: 'var(--ink)' }}>
                  {(kinds[h.kind] ? kinds[h.kind][lang === 'en' ? 1 : 0] : h.kind)}
                  {h.version ? ` ${vname(h.version)}` : ''}
                  {h.to_version ? ` (${vname(h.to_version)})` : ''}
                  {h.note ? ` : ${h.note}` : ''}
                </span>
              </div>
            ))}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
