import { useState } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import * as Dropdown from '@radix-ui/react-dropdown-menu'
import * as Dialog from '@radix-ui/react-dialog'
import { Eye, LockKeyhole, X } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '../../api/client'
import { productionSync } from '../../hooks/useProduction'
import type { ProductionState } from '../../types'
import type { Selection } from './Production'
import { useArchiveDelete } from './MenuEdit'
import { trackingLocked, type TrackingEntity } from './tracking'
import { viewportRect } from '../../components/shared/tooltipPosition'
import { shotFollowKey, useFavorites } from '../../hooks/useFavorites'

export function EntityContextMenu({ project, state, entity, setState, setSelection, onEdit }: {
  project: string; state: ProductionState; entity: TrackingEntity
  setState: (patch: (prev: ProductionState) => ProductionState) => void
  setSelection: (selection: Selection) => void; onEdit: () => void
}) {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [anchor, setAnchor] = useState({ x: 0, y: 0 })
  const [unlock, setUnlock] = useState(false)
  const [phrase, setPhrase] = useState('')
  const [busy, setBusy] = useState(false)
  const archive = useArchiveDelete(project)
  const isShot = 'seq_id' in entity
  const seq = isShot ? state.sequences.find(s => s.id === entity.seq_id) : undefined
  const locked = trackingLocked(state, entity)
  const inherited = isShot && Boolean(seq?.locked)
  const selection: Selection = { kind: isShot ? 'shot' : 'asset', id: entity.id }
  // Follow the whole shot: its events land in Activity > Self and notify (retake 04).
  const { has, toggleKey } = useFavorites()
  const followKey = isShot ? shotFollowKey(project, seq?.name ?? '', entity.name) : ''
  const followed = isShot && has(followKey)
  const lock = async (value: boolean) => {
    if (!isShot) return
    setBusy(true)
    try {
      await productionSync.flush()
      const result = await api.lockSeqShot(project, 'shot', seq?.name ?? '', entity.name, value, phrase)
      setState(prev => ({ ...prev, shots: prev.shots.map(s => s.id === entity.id ? { ...s, locked: result.locked ?? undefined } : s) }))
      setUnlock(false); setPhrase('')
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
  return <>
    <span className="tracking-entity-name" role="button" tabIndex={0} aria-label={`Actions de ${entity.name}`} title={isShot ? `Clic droit : Edit, ${followed ? 'Ne plus suivre' : 'Suivre'}, Calendar, Lock, Delete` : 'Clic droit : Edit, Delete'}
      onContextMenu={e => { e.preventDefault(); setAnchor({ x: e.clientX, y: e.clientY }); setOpen(true) }}
      onKeyDown={e => { if (e.key === 'ContextMenu' || (e.shiftKey && e.key === 'F10')) { e.preventDefault(); const rect = viewportRect(e.currentTarget); setAnchor({ x: rect.left, y: rect.bottom }); setOpen(true) } }}>
      <strong>{entity.name}{locked && <LockKeyhole size={11} />}{followed && <Eye size={11} aria-label="Shot suivi" />}</strong>
    </span>
    <Dropdown.Root open={open} onOpenChange={setOpen} modal={false}>{createPortal(<Dropdown.Trigger tabIndex={-1} aria-hidden style={{ position: 'fixed', left: anchor.x, top: anchor.y, width: 1, height: 1, opacity: 0, pointerEvents: 'none' }} />, document.body)}
      <Dropdown.Portal><Dropdown.Content className="production-context-menu" align="start" collisionPadding={10}>
        <Dropdown.Label className="production-menu-artist">{entity.name}</Dropdown.Label>
        <Dropdown.Item className="production-menu-item" onSelect={() => { setSelection(selection); onEdit() }}>Edit</Dropdown.Item>
        {isShot && <Dropdown.Item className="production-menu-item" onSelect={() => { void toggleKey(followKey); toast.success(followed ? `${entity.name} : plus suivi` : `${entity.name} suivi : ses events arrivent dans Activity > Self`) }}>{followed ? 'Ne plus suivre' : 'Suivre le shot'}</Dropdown.Item>}
        {isShot && <Dropdown.Item className="production-menu-item" onSelect={() => navigate(`/calendar?${new URLSearchParams({ seq: seq?.name ?? '', shot: entity.name, project })}`)}>Calendar</Dropdown.Item>}
        {isShot && <Dropdown.Item disabled={busy || inherited} className="production-menu-item" onSelect={() => { if (locked) setUnlock(true); else void lock(true) }}>{locked ? 'Unlock' : 'Lock'}{inherited ? ` · ${seq?.name}` : ''}</Dropdown.Item>}
        <Dropdown.Item disabled={locked} className="production-menu-item production-menu-delete" onSelect={() => void remove()}>Delete</Dropdown.Item>
      </Dropdown.Content></Dropdown.Portal>
    </Dropdown.Root>
    {archive.modal}
    <Dialog.Root open={unlock} onOpenChange={value => { if (!busy) setUnlock(value) }}><Dialog.Portal><Dialog.Overlay className="production-dialog-overlay" /><Dialog.Content className="production-dialog">
      <div className="production-dialog-heading"><Dialog.Title>Unlock · {entity.name}</Dialog.Title><Dialog.Close disabled={busy} aria-label="Fermer"><X size={16} /></Dialog.Close></div>
      <Dialog.Description>Tapez Understand pour déverrouiller ce shot.</Dialog.Description><input aria-label="Confirmation de déverrouillage" value={phrase} onChange={e => setPhrase(e.target.value)} />
      <div className="production-dialog-actions"><button disabled={busy || phrase.trim() !== 'Understand'} onClick={() => void lock(false)}>{busy ? '…' : 'Unlock'}</button></div>
    </Dialog.Content></Dialog.Portal></Dialog.Root>
  </>
}
