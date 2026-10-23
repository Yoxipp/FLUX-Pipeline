// DestructiveDialog.tsx — "Nodes destructifs" (03_EDITEUR §6, decision 13): before a save
// (Ctrl+S, quit, close of the window) that adds `!` nodes, one line per node (icon, label,
// key params, "Aller au node") and a SlideToConfirm (danger, full width) "Glisse pour
// valider et enregistrer". Cancel = stay, nothing saved. The ids go to the backend as
// `confirmed_destructive` (PUT refuses an unconfirmed `!`, E_DESTRUCTIVE_UNCONFIRMED).

import * as Dialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { SlideToConfirm } from '../../components/shared/SlideToConfirm'
import { Btn } from '../../components/shared/ui'
import { FAMILY_INFO } from './families'
import { iconFor } from './icons'
import type { FlowViewNode } from './types'
import { formatValue, useTr } from './useTr'

export function DestructiveDialog({ nodes, params, onGoTo, onConfirm, onCancel }: {
  nodes: FlowViewNode[] | null            // null = closed
  params: Record<string, Record<string, unknown>>
  onGoTo: (id: string) => void
  onConfirm: () => void
  onCancel: () => void
}) {
  const { tr } = useTr()
  return (
    <Dialog.Root open={!!nodes} onOpenChange={o => { if (!o) onCancel() }}>
      <Dialog.Portal>
        <Dialog.Overlay className="flow-dialog-overlay" />
        <Dialog.Content className="flow-dialog" aria-describedby={undefined} style={{ width: 480 }}>
          <div className="flow-dialog-heading">
            <Dialog.Title style={{ color: 'var(--err)' }}>{tr('Nodes destructifs', 'Destructive nodes')}</Dialog.Title>
            <Dialog.Close aria-label={tr('Fermer', 'Close')}><X size={15} /></Dialog.Close>
          </div>
          <div style={{ fontSize: 12, color: 'var(--ink-2)', marginBottom: 6 }}>
            {tr('Ces nodes effacent, ecrasent ou deplacent des fichiers. Verifie-les avant d\'enregistrer.',
                'These nodes erase, overwrite or move files. Check them before saving.')}
          </div>
          <div style={{ maxHeight: 280, overflowY: 'auto' }}>
            {(nodes ?? []).map(n => {
              const Icon = iconFor(n.icon, n.family)
              const p = params[n.id] ?? {}
              const keys = Object.entries(p).filter(([, v]) => v !== undefined && v !== '').slice(0, 4)
              return (
                <div key={n.id} style={{ display: 'flex', alignItems: 'flex-start', gap: 8, padding: '6px 0', borderBottom: '1px solid var(--rule)' }}>
                  <Icon size={14} strokeWidth={2} color={FAMILY_INFO[n.family].color} style={{ marginTop: 1, flexShrink: 0 }} />
                  <div style={{ flex: 1, minWidth: 0, fontSize: 11.5 }}>
                    <div style={{ color: 'var(--ink)', fontWeight: 600 }}>
                      <span style={{ color: 'var(--err)' }}>! </span>{n.label} <span className="tag">{n.id}</span>
                    </div>
                    {keys.map(([k, v]) => (
                      <div key={k} style={{ color: 'var(--ink-3)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {k} = {formatValue(v, 80)}
                      </div>
                    ))}
                  </div>
                  <Btn sm ghost onClick={() => onGoTo(n.id)}>{tr('Aller au node', 'Go to node')}</Btn>
                </div>
              )
            })}
          </div>
          <div style={{ marginTop: 12 }}>
            <SlideToConfirm label={tr('Glisse pour valider et enregistrer', 'Slide to confirm and save')} tone="danger" width="fill" onConfirm={onConfirm} />
          </div>
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 6 }}>
            <Btn sm ghost onClick={onCancel}>{tr('Annuler', 'Cancel')}</Btn>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
