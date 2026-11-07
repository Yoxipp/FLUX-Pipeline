import { useState } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import * as Dropdown from '@radix-ui/react-dropdown-menu'
import * as Dialog from '@radix-ui/react-dialog'
import { Eye, LockKeyhole, X } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '../../api/client'
import { productionSync } from '../../hooks/useProduction'
import type { ProductionPublish, ProductionState, ProductionTask } from '../../types'
import { publishVersion, sortPublishes } from './taskPublishes'
import type { Selection } from './Production'
import { useArchiveDelete, UNLOCK_PHRASE } from './MenuEdit'
import { SlideToConfirm } from '../../components/shared/SlideToConfirm'
import { useI18n } from '../../i18n'
import { trackingLocked, type TrackingEntity } from './tracking'
import { viewportRect } from '../../components/shared/tooltipPosition'
import { shotFollowKey, useFavorites } from '../../hooks/useFavorites'

export function EntityContextMenu({ project, state, entity, setState, setSelection, onEdit, publishesByTask, onOpenVersion }: {
  project: string; state: ProductionState; entity: TrackingEntity
  setState: (patch: (prev: ProductionState) => ProductionState) => void
  setSelection: (selection: Selection) => void; onEdit: () => void
  publishesByTask: Record<string, ProductionPublish[]>
  onOpenVersion: (task: ProductionTask, version: string) => void   // opens the task panel on that version
}) {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [anchor, setAnchor] = useState({ x: 0, y: 0 })
  const [unlock, setUnlock] = useState(false)
  const { t } = useI18n()
  const [busy, setBusy] = useState(false)
  const [newDir, setNewDir] = useState<string | null>(null)
  const archive = useArchiveDelete(project)
  const isShot = 'seq_id' in entity
  const seq = isShot ? state.sequences.find(s => s.id === entity.seq_id) : undefined
  const locked = trackingLocked(state, entity)
  const inherited = isShot && Boolean(seq?.locked)
  const selection: Selection = { kind: isShot ? 'shot' : 'asset', id: entity.id }
  // Follow the whole shot: its events land in the bell > Self and notify (retake 04).
  const { has, toggleKey } = useFavorites()
  const followKey = isShot ? shotFollowKey(project, seq?.name ?? '', entity.name) : ''
  const followed = isShot && has(followKey)
  const lock = async (value: boolean) => {
    if (!isShot) return
    setBusy(true)
    try {
      await productionSync.flush()
      // Unlocking: the slider replaces typing, the backend guard still expects the phrase.
      const result = await api.lockSeqShot(project, 'shot', seq?.name ?? '', entity.name, value, value ? '' : UNLOCK_PHRASE)
      setState(prev => ({ ...prev, shots: prev.shots.map(s => s.id === entity.id ? { ...s, locked: result.locked ?? undefined } : s) }))
      setUnlock(false)
    } catch (e) { toast.error(e instanceof Error ? e.message : 'Action impossible') }
    finally { setBusy(false) }
  }
  const remove = async () => {
    try {
      await productionSync.flush()
      archive.request(isShot ? { kind: 'shot', seq: seq?.name ?? '', shot: entity.name } : { kind: 'asset', class_token: entity.class, name: entity.name }, entity.name, () => {
        setState(prev => ({ ...prev, shots: prev.shots.filter(s => s.id !== entity.id), assets: prev.assets.filter(s => s.id !== entity.id) }))
        setSelection({ kind: 'none' })
      })
    } catch (e) { toast.error(e instanceof Error ? e.message : 'Action impossible') }
  }
  // Free sub-folder inside the entity's disk folder (resolved by the backend, tokens first).
  const createDir = async () => {
    const name = (newDir ?? '').trim()
    if (!name) return
    setBusy(true)
    try {
      const params = isShot ? { kind: 'shot' as const, seq: seq?.name ?? '', shot: entity.name } : { kind: 'asset' as const, class_token: entity.class, name: entity.name }
      const info = await api.getEntityFolder(project, params, { count: false })
      if (!info.rel_path || !info.exists) { toast.error(`Pas de dossier sur le disque pour ${entity.name}`); return }
      await api.createDirectory(project, info.rel_path.split('/'), name)
      toast.success(`Dossier ${name} créé dans ${info.rel_path}`)
      setNewDir(null)
    } catch (e) { toast.error(e instanceof Error ? e.message : 'Action impossible') }
    finally { setBusy(false) }
  }
  // Tasks that have at least one versioned publish, for "Ouvrir une version".
  const versioned = entity.tasks.flatMap(task => {
    const versions = sortPublishes(publishesByTask[`${entity.id}|${task.id}`] ?? []).map(p => publishVersion(p.file)).filter(Boolean)
    return versions.length ? [{ task, versions: [...new Set(versions)] }] : []
  })
  return <>
    <span className="tracking-entity-name" role="button" tabIndex={0} aria-label={`Actions de ${entity.name}`} title={isShot ? `Clic droit : Edit, ${followed ? 'Ne plus suivre' : 'Suivre'}, Calendar, Lock, Nouveau dossier, Delete` : 'Clic droit : Edit, Nouveau dossier, Delete'}
      onContextMenu={e => { e.preventDefault(); setAnchor({ x: e.clientX, y: e.clientY }); setOpen(true) }}
      onKeyDown={e => { if (e.key === 'ContextMenu' || (e.shiftKey && e.key === 'F10')) { e.preventDefault(); const rect = viewportRect(e.currentTarget); setAnchor({ x: rect.left, y: rect.bottom }); setOpen(true) } }}>
      <strong>{entity.name}{locked && <LockKeyhole size={11} />}{followed && <Eye size={11} aria-label="Shot suivi" />}</strong>
    </span>
    <Dropdown.Root open={open} onOpenChange={setOpen} modal={false}>{createPortal(<Dropdown.Trigger tabIndex={-1} aria-hidden style={{ position: 'fixed', left: anchor.x, top: anchor.y, width: 1, height: 1, opacity: 0, pointerEvents: 'none' }} />, document.body)}
      <Dropdown.Portal><Dropdown.Content className="production-context-menu" align="start" collisionPadding={10}>
        <Dropdown.Label className="production-menu-artist">{entity.name}</Dropdown.Label>
        <Dropdown.Item className="production-menu-item" onSelect={() => { setSelection(selection); onEdit() }}>Edit</Dropdown.Item>
        <Dropdown.Sub>
          <Dropdown.SubTrigger disabled={!versioned.length} className="production-menu-item">Ouvrir une version</Dropdown.SubTrigger>
          <Dropdown.Portal><Dropdown.SubContent className="production-context-menu" sideOffset={4} collisionPadding={10}>
            {versioned.map(({ task, versions }) => (
              <Dropdown.Sub key={task.id}>
                <Dropdown.SubTrigger className="production-menu-item">{task.name}</Dropdown.SubTrigger>
                <Dropdown.Portal><Dropdown.SubContent className="production-context-menu" sideOffset={4} collisionPadding={10} style={{ maxHeight: 280, overflowY: 'auto' }}>
                  {versions.map(version => (
                    <Dropdown.Item key={version} className="production-menu-item" onSelect={() => onOpenVersion(task, version)}>{version}</Dropdown.Item>
                  ))}
                </Dropdown.SubContent></Dropdown.Portal>
              </Dropdown.Sub>
            ))}
          </Dropdown.SubContent></Dropdown.Portal>
        </Dropdown.Sub>
        {isShot && <Dropdown.Item className="production-menu-item" onSelect={() => { void toggleKey(followKey); toast.success(followed ? `${entity.name} : plus suivi` : `${entity.name} suivi : ses events arrivent dans la cloche > Self`) }}>{followed ? 'Ne plus suivre' : 'Suivre le shot'}</Dropdown.Item>}
        {isShot && <Dropdown.Item className="production-menu-item" onSelect={() => navigate(`/calendar?${new URLSearchParams({ seq: seq?.name ?? '', shot: entity.name, project })}`)}>Calendar</Dropdown.Item>}
        {isShot && <Dropdown.Item disabled={busy || inherited} className="production-menu-item" onSelect={() => { if (locked) setUnlock(true); else void lock(true) }}>{locked ? 'Unlock' : 'Lock'}{inherited ? ` · ${seq?.name}` : ''}</Dropdown.Item>}
        <Dropdown.Item disabled={locked} className="production-menu-item" onSelect={() => setNewDir('')}>Nouveau dossier</Dropdown.Item>
        <Dropdown.Item disabled={locked} className="production-menu-item production-menu-delete" onSelect={() => void remove()}>Delete</Dropdown.Item>
      </Dropdown.Content></Dropdown.Portal>
    </Dropdown.Root>
    {archive.modal}
    <Dialog.Root open={unlock} onOpenChange={value => { if (!busy) setUnlock(value) }}><Dialog.Portal><Dialog.Overlay className="production-dialog-overlay" /><Dialog.Content className="production-dialog">
      <div className="production-dialog-heading"><Dialog.Title>Unlock · {entity.name}</Dialog.Title><Dialog.Close disabled={busy} aria-label="Fermer"><X size={16} /></Dialog.Close></div>
      <Dialog.Description>Glisse le curseur jusqu'au bout pour déverrouiller ce shot.</Dialog.Description>
      <div style={{ display: 'flex', justifyContent: 'center', marginTop: 12 }}><SlideToConfirm label={t('confirm.slideToUnlock')} disabled={busy} onConfirm={() => lock(false)} /></div>
    </Dialog.Content></Dialog.Portal></Dialog.Root>
    <Dialog.Root open={newDir !== null} onOpenChange={value => { if (!busy && !value) setNewDir(null) }}><Dialog.Portal><Dialog.Overlay className="production-dialog-overlay" /><Dialog.Content className="production-dialog">
      <div className="production-dialog-heading"><Dialog.Title>Nouveau dossier · {entity.name}</Dialog.Title><Dialog.Close disabled={busy} aria-label="Fermer"><X size={16} /></Dialog.Close></div>
      <Dialog.Description>Créé dans le dossier de {entity.name} sur le disque.</Dialog.Description>
      <input autoFocus value={newDir ?? ''} disabled={busy} placeholder="Nom du dossier" onChange={e => setNewDir(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter') void createDir() }} style={{ width: '100%', marginTop: 10 }} />
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 12 }}><button className="btn primary" disabled={busy || !(newDir ?? '').trim()} onClick={() => void createDir()}>Créer</button></div>
    </Dialog.Content></Dialog.Portal></Dialog.Root>
  </>
}
