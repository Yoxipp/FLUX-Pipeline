// CreateMenu - the one "Create" button of a Production toolbar (retake 05): a click
// lists what can really be created in this mode (Shot / Sequence, or Asset / Group)
// and opens NewProductionDialog on that type. The creation fields stay in the dialog
// (same validations and defaults), never exposed permanently.

import * as Menu from '@radix-ui/react-dropdown-menu'
import { ChevronDown, Plus } from 'lucide-react'

export type CreateKind = 'shot' | 'seq' | 'asset' | 'group'

const LABEL: Record<CreateKind, string> = { shot: 'Shot', seq: 'Séquence', asset: 'Asset', group: 'Groupe' }

export function CreateMenu({ mode, hasSequences, onCreate }: {
  mode: 'asset' | 'shot'
  hasSequences: boolean
  onCreate: (kind: CreateKind) => void
}) {
  const kinds: CreateKind[] = mode === 'shot' ? ['shot', 'seq'] : ['asset', 'group']
  return (
    <Menu.Root modal={false}>
      <Menu.Trigger asChild>
        <button type="button" className="production-create-trigger" aria-label="Create">
          <Plus size={13} /> Create <ChevronDown size={12} />
        </button>
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Content className="production-context-menu" align="start" sideOffset={4} collisionPadding={10}>
          {kinds.map(kind => {
            const blocked = kind === 'shot' && !hasSequences
            return (
              <Menu.Item key={kind} className="production-menu-item" disabled={blocked} onSelect={() => onCreate(kind)}
                title={blocked ? "Crée d'abord une séquence" : undefined}>
                {LABEL[kind]}{blocked && <span style={{ marginLeft: 'auto', color: 'var(--ink-4)', fontSize: 11 }}>séquence requise</span>}
              </Menu.Item>
            )
          })}
        </Menu.Content>
      </Menu.Portal>
    </Menu.Root>
  )
}
