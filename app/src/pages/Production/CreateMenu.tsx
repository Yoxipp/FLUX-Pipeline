// CreateMenu - the one "Create" button of a Production toolbar (retake 05): a click
// lists what can really be created in this mode (Shot / Sequence, or Asset / Group)
// and opens NewProductionDialog on that type. The creation fields stay in the dialog
// (same validations and defaults), never exposed permanently.

import { useState } from 'react'
import * as Menu from '@radix-ui/react-dropdown-menu'
import * as Dialog from '@radix-ui/react-dialog'
import { ChevronDown, Plus, X } from 'lucide-react'
import { api } from '../../api/client'
import { useProject } from '../../ProjectContext'

export type CreateKind = 'shot' | 'seq' | 'asset' | 'group'

const LABEL: Record<CreateKind, string> = { shot: 'Shot', seq: 'Séquence', asset: 'Asset', group: 'Groupe' }

export function CreateMenu({ mode, hasSequences, onCreate }: {
  mode: 'asset' | 'shot'
  hasSequences: boolean
  onCreate: (kind: CreateKind) => void
}) {
  const kinds: CreateKind[] = mode === 'shot' ? ['shot', 'seq'] : ['asset', 'group']
  const [newProject, setNewProject] = useState(false)
  return (<>
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
          <Menu.Separator style={{ height: 1, background: 'var(--rule)', margin: '4px 0' }} />
          <Menu.Item className="production-menu-item" onSelect={() => setNewProject(true)}>Projet</Menu.Item>
        </Menu.Content>
      </Menu.Portal>
    </Menu.Root>
    {newProject && <NewProjectDialog onClose={() => setNewProject(false)} />}
  </>)
}

// A new project from Production (it creates the project folders on disk), then switches to it.
function NewProjectDialog({ onClose }: { onClose: () => void }) {
  const { setProject, refreshProjects } = useProject()
  const [name, setName] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const create = async () => {
    const clean = name.trim()
    if (!clean) return
    setBusy(true); setError('')
    try {
      const r = await api.createProject(clean)
      await refreshProjects()
      setProject(r.name)
      onClose()
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) }
  }
  return (
    <Dialog.Root open onOpenChange={open => { if (!open && !busy) onClose() }}><Dialog.Portal><Dialog.Overlay className="production-dialog-overlay" /><Dialog.Content className="production-dialog">
      <div className="production-dialog-heading"><Dialog.Title>Nouveau projet</Dialog.Title><Dialog.Close disabled={busy} aria-label="Fermer"><X size={16} /></Dialog.Close></div>
      <Dialog.Description>Crée le projet et ses dossiers, puis l'ouvre.</Dialog.Description>
      <input autoFocus value={name} disabled={busy} placeholder="Nom du projet" onChange={e => setName(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter') void create() }} style={{ width: '100%', marginTop: 10 }} />
      {error && <div style={{ fontSize: 11, color: 'var(--err)', marginTop: 6 }}>{error}</div>}
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 12 }}><button className="btn primary" disabled={busy || !name.trim()} onClick={() => void create()}>Créer le projet</button></div>
    </Dialog.Content></Dialog.Portal></Dialog.Root>
  )
}
