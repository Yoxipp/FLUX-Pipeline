// FlowManage.tsx — Dupliquer, Renommer, Changer de portee, Supprimer a flow (ADR 0069): the
// right-click menu of File > Open and the File menu entries for the open flow. Dupliquer an
// example (shipped example_*) gives a normal flow without the prefix, and the TOOL page it
// reads is created in the project when missing (POST /copy). Renommer / Changer de portee =
// POST /relocate: versions and state follow, the flow arrives inactive, the old one goes to
// the trash. Supprimer = to the trash of its scope. Shipped flows only duplicate.

import { useEffect, useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { ArrowRightLeft, Copy, FolderOpen, Pencil, Trash2, X } from 'lucide-react'
import { toast } from 'sonner'
import { flowsApi } from '../../api/flows'
import { Btn } from '../../components/shared/ui'
import { NameDialog, type ScopeChoice } from './FileDialogs'
import type { FlowRights, FlowScope } from './types'
import { useTr } from './useTr'

type HttpError = Error & { status?: number }

export type FlowOp = 'duplicate' | 'rename' | 'move' | 'delete'
export interface FlowRef { name: string; scope: FlowScope }
export interface FlowOpRequest { op: FlowOp; flow: FlowRef }

const EXAMPLE_PREFIX = 'example_'
const LEGACY_PREFIX = 'legacy_'

/** Why *op* is not possible on *flow* (null = allowed). */
export function opBlocked(op: FlowOp, flow: FlowRef, rights: FlowRights | null, tr: (fr: string, en: string) => string): string | null {
  if (op === 'duplicate') return null
  if (flow.scope === 'shipped') {
    return flow.name.startsWith(EXAMPLE_PREFIX) ? tr('Exemple livre : duplique-le pour le modifier', 'Shipped example: duplicate it to edit it')
      : tr('Flow livre : duplique-le', 'Shipped flow: duplicate it')
  }
  if (!rights?.can[flow.scope]?.write) return flow.scope === 'perso' ? tr('Case TD requise', 'TD box required') : tr('Case Team TD requise', 'Team TD box required')
  return null
}

/** The name proposed by Dupliquer: an example loses its prefix, another flow gets _copie. */
export function duplicateName(name: string): string {
  if (name.startsWith(EXAMPLE_PREFIX)) return name.slice(EXAMPLE_PREFIX.length)
  return `${name.replace(LEGACY_PREFIX, '')}_copie`.slice(0, 41)
}

/** Right-click menu of a flow in File > Open (fixed at the mouse). */
export function FlowOpMenu({ at, flow, rights, onPick, onOpen, onClose }: {
  at: { x: number; y: number } | null
  flow: FlowRef | null
  rights: FlowRights | null
  onPick: (op: FlowOp) => void
  onOpen: () => void
  onClose: () => void
}) {
  const { tr } = useTr()
  useEffect(() => {
    if (!at) return
    const close = (e: Event) => { if (!(e.target as HTMLElement | null)?.closest?.('.flow-opmenu')) onClose() }
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    const id = setTimeout(() => { document.addEventListener('mousedown', close); document.addEventListener('contextmenu', close) }, 0)
    document.addEventListener('keydown', esc)
    return () => { clearTimeout(id); document.removeEventListener('mousedown', close); document.removeEventListener('contextmenu', close); document.removeEventListener('keydown', esc) }
  }, [at, onClose])
  if (!at || !flow) return null
  const items: { op: FlowOp | 'open'; icon: JSX.Element; label: string }[] = [
    { op: 'open', icon: <FolderOpen size={13} />, label: tr('Ouvrir', 'Open') },
    { op: 'duplicate', icon: <Copy size={13} />, label: tr('Dupliquer…', 'Duplicate…') },
    { op: 'rename', icon: <Pencil size={13} />, label: tr('Renommer…', 'Rename…') },
    { op: 'move', icon: <ArrowRightLeft size={13} />, label: tr('Changer de portee…', 'Change scope…') },
    { op: 'delete', icon: <Trash2 size={13} />, label: tr('Supprimer…', 'Delete…') },
  ]
  return (
    <div className="flow-menu flow-opmenu" role="menu"
         style={{ position: 'fixed', left: Math.min(at.x, window.innerWidth - 220), top: Math.min(at.y, window.innerHeight - 200), zIndex: 70, minWidth: 200 }}>
      <div className="flow-menu-label">{flow.name}</div>
      {items.map(it => {
        const why = it.op === 'open' ? null : opBlocked(it.op, flow, rights, tr)
        return (
          <div key={it.op} role="menuitem" className="flow-menu-item" aria-disabled={!!why} data-disabled={why ? '' : undefined} title={why ?? undefined}
               style={why ? { opacity: 0.45, cursor: 'default' } : undefined}
               onClick={() => { if (why) return; onClose(); if (it.op === 'open') onOpen(); else onPick(it.op) }}>
            {it.icon} {it.label}
          </div>
        )
      })}
    </div>
  )
}

/** The dialogs of the four operations; *onDone* gets the flow to show next (null: nothing changes). */
export function FlowOpDialogs({ request, choices, project, openFlow, dirty, onClose, onDone }: {
  request: FlowOpRequest | null
  choices: ScopeChoice[]
  project?: string
  openFlow: FlowRef | null            // the flow open in the editor
  dirty: boolean
  onClose: () => void
  onDone: (next: FlowRef | null, removedOpen: boolean) => void
}) {
  const { tr } = useTr()
  const [busy, setBusy] = useState(false)
  const op = request?.op
  const flow = request?.flow
  const isOpen = !!flow && !!openFlow && flow.name === openFlow.name && flow.scope === openFlow.scope
  const fail = (e: HttpError) => toast.error(e.status === 409 ? (e.message || tr('Un flow de ce nom existe deja la', 'A flow with this name already exists there')) : e.message)
  // A copy or a move takes the saved file: unsaved changes of the open flow would be lost.
  const unsaved = isOpen && dirty && op !== 'delete'

  const duplicate = (name: string, scope: FlowScope) => {
    if (!flow) return
    setBusy(true)
    flowsApi.copy(flow.name, flow.scope, scope, { project, new_name: name })
      .then(r => {
        const made = (r.pages ?? []).filter(p => p.status === 'created').map(p => p.page)
        const lack = (r.pages ?? []).filter(p => p.status === 'no_right' || p.status === 'missing').map(p => p.page)
        toast.success(tr(`${r.name} cree`, `${r.name} created`) + (made.length ? tr(` ; page TOOL creee : ${made.join(', ')}`, `; TOOL page created: ${made.join(', ')}`) : ''))
        if (lack.length) toast.warning(tr(`Page TOOL a creer par un Team TD : ${lack.join(', ')}`, `TOOL page to create by a Team TD: ${lack.join(', ')}`))
        onDone({ name: r.name, scope: r.scope }, false)
      })
      .catch(fail).finally(() => setBusy(false))
  }
  const relocate = (name: string, scope: FlowScope) => {
    if (!flow) return
    setBusy(true)
    flowsApi.relocate(flow.name, flow.scope, scope, { project, new_name: name })
      .then(r => {
        toast.success(op === 'rename' ? tr(`Renomme en ${r.name}`, `Renamed to ${r.name}`)
          : tr(`${r.name} deplace (${r.scope}), a reactiver si besoin`, `${r.name} moved (${r.scope}), activate it again if needed`))
        onDone(isOpen ? { name: r.name, scope: r.scope } : null, false)
      })
      .catch(fail).finally(() => setBusy(false))
  }
  const remove = () => {
    if (!flow) return
    setBusy(true)
    flowsApi.remove(flow.name, flow.scope, project)
      .then(() => { toast.success(tr(`${flow.name} mis a la corbeille`, `${flow.name} moved to the trash`)); onDone(null, isOpen) })
      .catch(fail).finally(() => setBusy(false))
  }

  const moveChoices = choices.map(c => c.scope === flow?.scope ? { ...c, disabled: tr('il y est deja', 'already there') } : c)
  const isExample = !!flow && flow.scope === 'shipped' && flow.name.startsWith(EXAMPLE_PREFIX)
  return (
    <>
      <NameDialog
        open={!!flow && op === 'duplicate'} title={tr(`Dupliquer ${flow?.name ?? ''}`, `Duplicate ${flow?.name ?? ''}`)}
        note={unsaved ? tr('Copie du fichier enregistre : enregistre d\'abord (Ctrl+S) pour garder tes changements.', 'Copies the saved file: save first (Ctrl+S) to keep your changes.')
          : isExample ? tr('Un exemple devient un flow normal, modifiable et activable. Sa page TOOL est creee dans le projet si elle manque.', 'An example becomes a normal flow you can edit and activate. Its TOOL page is created in the project when missing.')
          : undefined}
        initialName={flow ? duplicateName(flow.name) : ''} choices={choices}
        initialScope={flow && flow.scope !== 'shipped' ? flow.scope : (project ? 'project' : 'team')}
        confirmLabel={tr('Dupliquer', 'Duplicate')} onClose={onClose} onConfirm={(name, scope) => { if (!busy) duplicate(name, scope) }}
      />
      <NameDialog
        open={!!flow && op === 'rename'} title={tr(`Renommer ${flow?.name ?? ''}`, `Rename ${flow?.name ?? ''}`)} askScope={false}
        note={unsaved ? tr('Enregistre d\'abord (Ctrl+S) : le renommage prend le fichier enregistre.', 'Save first (Ctrl+S): renaming takes the saved file.')
          : tr('Les versions suivent ; le flow est desactive. Une page qui lit sa sortie doit etre mise a jour.', 'Versions follow; the flow is deactivated. A page reading its output must be updated.')}
        initialName={flow?.name ?? ''} choices={choices} initialScope={flow?.scope}
        confirmLabel={tr('Renommer', 'Rename')} onClose={onClose}
        onConfirm={name => { if (unsaved) toast.error(tr('Enregistre d\'abord (Ctrl+S)', 'Save first (Ctrl+S)')); else if (!busy && flow) relocate(name, flow.scope) }}
      />
      <NameDialog
        open={!!flow && op === 'move'} title={tr(`Changer la portee de ${flow?.name ?? ''}`, `Change the scope of ${flow?.name ?? ''}`)} askName={false}
        note={unsaved ? tr('Enregistre d\'abord (Ctrl+S) : le deplacement prend le fichier enregistre.', 'Save first (Ctrl+S): moving takes the saved file.')
          : tr('Le flow part avec ses versions et son historique ; il arrive desactive. L\'ancien va a la corbeille.', 'The flow goes with its versions and history; it arrives inactive. The old one goes to the trash.')}
        initialName={flow?.name ?? ''} choices={moveChoices} initialScope={moveChoices.find(c => !c.disabled)?.scope}
        confirmLabel={tr('Deplacer', 'Move')} onClose={onClose}
        onConfirm={(_name, scope) => { if (unsaved) toast.error(tr('Enregistre d\'abord (Ctrl+S)', 'Save first (Ctrl+S)')); else if (!busy && flow) relocate(flow.name, scope) }}
      />
      <Dialog.Root open={!!flow && op === 'delete'} onOpenChange={o => { if (!o) onClose() }}>
        <Dialog.Portal>
          <Dialog.Overlay className="flow-dialog-overlay" />
          <Dialog.Content className="flow-dialog" aria-describedby={undefined} style={{ width: 420 }}>
            <div className="flow-dialog-heading">
              <Dialog.Title>{tr(`Supprimer ${flow?.name ?? ''} ?`, `Delete ${flow?.name ?? ''}?`)}</Dialog.Title>
              <Dialog.Close aria-label={tr('Fermer', 'Close')}><X size={15} /></Dialog.Close>
            </div>
            <div style={{ fontSize: 12, color: 'var(--ink-2)', lineHeight: 1.5 }}>
              {tr('Le flow, ses versions et son etat vont dans la corbeille de sa portee (_trash), recuperables a la main. Il ne tourne plus.',
                  'The flow, its versions and its state go to the trash of its scope (_trash), recoverable by hand. It no longer runs.')}
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 6, marginTop: 12 }}>
              <Btn sm ghost onClick={onClose}>{tr('Annuler', 'Cancel')}</Btn>
              <Btn sm primary disabled={busy} onClick={remove}><Trash2 size={12} /> {tr('Mettre a la corbeille', 'Move to the trash')}</Btn>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  )
}
