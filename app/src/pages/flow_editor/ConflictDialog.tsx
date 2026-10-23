// ConflictDialog.tsx — the flow was saved by someone else since it was opened (03_EDITEUR §6,
// B7, 409 of PUT / increment with {revision, by, at}). No merge in V1: "Voir sa version"
// keeps this document as a local draft (proposed again at the next opening) and loads
// theirs; "Enregistrer par-dessus" saves with force (their save stays in the history and
// the frozen versions); Annuler keeps editing, nothing saved.

import * as Dialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { Btn } from '../../components/shared/ui'
import { useTr } from './useTr'

export interface ConflictInfo { by?: string | null; at?: string | null; retry: () => void }

export function ConflictDialog({ conflict, onTheirs, onClose }: {
  conflict: ConflictInfo | null
  onTheirs: () => void
  onClose: () => void
}) {
  const { tr } = useTr()
  const who = conflict?.by || tr('Quelqu\'un', 'Someone')
  const at = conflict?.at ? conflict.at.replace('T', ' ').slice(11, 16) : ''
  return (
    <Dialog.Root open={!!conflict} onOpenChange={o => { if (!o) onClose() }}>
      <Dialog.Portal>
        <Dialog.Overlay className="flow-dialog-overlay" />
        <Dialog.Content className="flow-dialog" aria-describedby={undefined} style={{ width: 440 }}>
          <div className="flow-dialog-heading">
            <Dialog.Title>{tr('Enregistre pendant que tu editais', 'Saved while you were editing')}</Dialog.Title>
            <Dialog.Close aria-label={tr('Fermer', 'Close')}><X size={15} /></Dialog.Close>
          </div>
          <div style={{ fontSize: 12, color: 'var(--ink-2)', lineHeight: 1.5 }}>
            {tr(`${who} a enregistre ce flow${at ? ` a ${at}` : ''} pendant que tu l'editais. Pas de fusion : choisis.`,
                `${who} saved this flow${at ? ` at ${at}` : ''} while you were editing it. No merge: choose.`)}
          </div>
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 6, marginTop: 10, flexWrap: 'wrap' }}>
            <Btn sm ghost onClick={onClose}>{tr('Annuler', 'Cancel')}</Btn>
            <Btn sm ghost onClick={onTheirs} title={tr('Ton document reste en brouillon local, propose a la reouverture', 'Your document stays as a local draft, offered when reopened')}>
              {tr('Voir sa version', 'See their version')}
            </Btn>
            <Btn sm primary onClick={() => { conflict?.retry(); onClose() }} title={tr('Sa version reste dans l\'historique', 'Their version stays in the history')}>
              {tr('Enregistrer par-dessus', 'Save over it')}
            </Btn>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
