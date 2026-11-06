// DccBanner.tsx — banner of a DCC node opened from its double click (03_EDITEUR §8, P6a).
// Shipped (locked): "Node livre avec FLUX : lecture seule" + Deverrouiller (Team TD): a team copy
// of the same name that replaces the node for the whole team (decision 19); FLUX updates no
// longer change it while the copy exists. Team copy: tag "copie equipe" + Revenir au defaut
// (SlideToConfirm), which deletes the copy and brings the shipped node back.

import { useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { Lock, Undo2, Unlock, X } from 'lucide-react'
import { SlideToConfirm } from '../../components/shared/SlideToConfirm'
import { Btn } from '../../components/shared/ui'
import { useTr } from './useTr'

export function DccBanner({ name, locked, teamCopy, canUnlock, onUnlock, onRevert }: {
  name: string
  locked: boolean
  teamCopy: boolean
  canUnlock: boolean            // Team TD box
  onUnlock: () => void
  onRevert: () => void
}) {
  const { tr } = useTr()
  const [ask, setAsk] = useState<'unlock' | 'revert' | null>(null)
  if (!locked && !teamCopy) return null
  return (
    <>
      <div className="flow-banner">
        {locked
          ? <><Lock size={13} /> {tr('Node livre avec FLUX : lecture seule', 'Node shipped with FLUX: read-only')}</>
          : <><span className="tag" style={{ color: 'var(--accent-hi)' }}>{tr('copie equipe', 'team copy')}</span>
              {tr('Cette copie remplace le node livre pour toute l\'equipe.', 'This copy replaces the shipped node for the whole team.')}</>}
        <button type="button" className="flow-tool" disabled={!canUnlock}
                title={canUnlock ? undefined : tr('Case Team TD requise', 'Team TD box required')}
                onClick={() => setAsk(locked ? 'unlock' : 'revert')}>
          {locked ? <><Unlock size={13} /> {tr('Deverrouiller', 'Unlock')}</> : <><Undo2 size={13} /> {tr('Revenir au defaut', 'Back to default')}</>}
        </button>
      </div>
      <Dialog.Root open={ask !== null} onOpenChange={o => { if (!o) setAsk(null) }}>
        <Dialog.Portal>
          <Dialog.Overlay className="flow-dialog-overlay" />
          <Dialog.Content className="flow-dialog" aria-describedby={undefined} style={{ width: 460 }}>
            <div className="flow-dialog-heading">
              <Dialog.Title>{ask === 'unlock' ? tr(`Deverrouiller ${name}`, `Unlock ${name}`) : tr(`Revenir au node livre ${name}`, `Back to the shipped ${name}`)}</Dialog.Title>
              <Dialog.Close aria-label={tr('Fermer', 'Close')}><X size={15} /></Dialog.Close>
            </div>
            <div style={{ fontSize: 12, color: 'var(--ink-2)', lineHeight: 1.45 }}>
              {ask === 'unlock'
                ? tr('Une copie d\'equipe est creee : elle remplace ce node pour toute l\'equipe. Les mises a jour de FLUX ne modifieront plus ce node tant que la copie existe.',
                     'A team copy is created: it replaces this node for the whole team. FLUX updates will no longer change this node while the copy exists.')
                : tr('La copie d\'equipe est supprimee (mise a la corbeille) : toute l\'equipe retrouve le node livre avec FLUX.',
                     'The team copy is deleted (moved to the trash): the whole team gets the node shipped with FLUX back.')}
            </div>
            <div style={{ marginTop: 12 }}>
              {ask === 'unlock'
                ? <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 6 }}>
                    <Btn sm ghost onClick={() => setAsk(null)}>{tr('Annuler', 'Cancel')}</Btn>
                    <Btn sm primary onClick={() => { setAsk(null); onUnlock() }}>{tr('Deverrouiller', 'Unlock')}</Btn>
                  </div>
                : <>
                    <SlideToConfirm label={tr('Glisse pour revenir au defaut', 'Slide to go back to default')} tone="danger" width="fill"
                                    onConfirm={() => { setAsk(null); onRevert() }} />
                    <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 6 }}>
                      <Btn sm ghost onClick={() => setAsk(null)}>{tr('Annuler', 'Cancel')}</Btn>
                    </div>
                  </>}
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  )
}
