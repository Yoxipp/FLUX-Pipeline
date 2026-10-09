// Folder Manager item modals: rename, move, delete confirm and the right-click menu.

import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { ChevronRight, Trash2 } from 'lucide-react'
import { api } from '../../api/client'
import { FolderSvg } from './icons'
import type { ExplorerItem } from './shared'
import { useTr } from '../../i18n'

export function RenameModal({ item, onConfirm, onCancel }: {
  item: ExplorerItem
  onConfirm: (newName: string) => Promise<void>
  onCancel: () => void
}) {
  const [name, setName]   = useState(item.name)
  const [busy, setBusy]   = useState(false)
  const [error, setError] = useState('')
  const inputRef          = useRef<HTMLInputElement>(null)
  const { tr }            = useTr()

  useEffect(() => { inputRef.current?.focus(); inputRef.current?.select() }, [])
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onCancel() }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [onCancel])

  const canConfirm = name.trim() !== '' && name.trim() !== item.name && !busy

  const handleConfirm = async () => {
    if (!canConfirm) return
    setBusy(true); setError('')
    try { await onConfirm(name.trim()) }
    catch (e) { setError(e instanceof Error ? e.message : tr('Erreur', 'Error')); setBusy(false) }
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)', zIndex: 2000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ background: 'var(--paper)', border: '1px solid var(--rule-2)', borderRadius: 10, padding: '20px 22px', width: 320, boxShadow: 'var(--shadow)' }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 14, color: 'var(--ink)' }}>{tr(`Renommer "${item.name}"`, `Rename "${item.name}"`)}</div>
        <input
          ref={inputRef}
          value={name}
          onChange={e => setName(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') void handleConfirm() }}
          style={{ width: '100%', height: 32, border: '1px solid var(--rule-2)', borderRadius: 5, background: 'var(--bg-deep)', color: 'var(--ink-2)', fontFamily: 'var(--sans)', fontSize: 11, padding: '0 10px', outline: 'none', boxSizing: 'border-box' }}
        />
        {error && <div style={{ fontSize: 11, color: 'var(--err)', fontFamily: 'var(--mono)', marginTop: 6 }}>{error}</div>}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 16 }}>
          <div className="btn ghost" onClick={onCancel} style={{ cursor: 'pointer' }}>{tr('Annuler', 'Cancel')}</div>
          <div className="btn primary" onClick={() => void handleConfirm()} style={{ cursor: canConfirm ? 'pointer' : 'default', opacity: canConfirm ? 1 : 0.5 }}>
            {busy ? '…' : tr('Renommer', 'Rename')}
          </div>
        </div>
      </div>
    </div>
  )
}

export function MoveModal({ items, project, currentSubpath, onConfirm, onCancel }: {
  items: ExplorerItem[]
  project: string
  currentSubpath: string[]
  onConfirm: (newSubpath: string[]) => Promise<void>
  onCancel: () => void
}) {
  const [browsePath, setBrowsePath] = useState<string[]>(currentSubpath)
  const [folders, setFolders]       = useState<string[]>([])
  const [loading, setLoading]       = useState(false)
  const [busy, setBusy]             = useState(false)
  const [error, setError]           = useState('')
  const itemNames = new Set(items.map(i => i.name))
  const { tr } = useTr()

  useEffect(() => {
    setLoading(true)
    api.browseProject(project, browsePath.join('/') || undefined)
      .then(d => {
        const all = d.folders.map(f => f.name)
        const isCurrentParent = browsePath.join('/') === currentSubpath.join('/')
        setFolders(isCurrentParent ? all.filter(n => !itemNames.has(n)) : all)
      })
      .catch(() => setFolders([]))
      .finally(() => setLoading(false))
  }, [project, browsePath, currentSubpath])

  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onCancel() }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [onCancel])

  const isSameLocation  = browsePath.join('/') === currentSubpath.join('/')
  const isInsideItself  = items.some(it => it.isDir &&
    browsePath.length > currentSubpath.length &&
    browsePath.slice(0, currentSubpath.length + 1).join('/') === [...currentSubpath, it.name].join('/'))
  const canConfirm = !isSameLocation && !isInsideItself && !busy

  const handleConfirm = async () => {
    if (!canConfirm) return
    setBusy(true); setError('')
    try { await onConfirm(browsePath) }
    catch (e) { setError(e instanceof Error ? e.message : tr('Erreur', 'Error')); setBusy(false) }
  }

  const breadcrumb = [project, ...browsePath]

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)', zIndex: 2000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ background: 'var(--paper)', border: '1px solid var(--rule-2)', borderRadius: 10, padding: '20px 22px', width: 360, boxShadow: 'var(--shadow)' }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4, color: 'var(--ink)' }}>
          {items.length === 1
            ? tr(`Déplacer "${items[0].name}"`, `Move "${items[0].name}"`)
            : tr(`Déplacer ${items.length} éléments`, `Move ${items.length} items`)}
        </div>
        <div style={{ fontSize: 11, color: 'var(--ink-3)', marginBottom: 12 }}>{tr('Double-clic pour naviguer dans un dossier', 'Double-click to open a folder')}</div>

        {/* Breadcrumb */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 3, fontFamily: 'var(--mono)', fontSize: 10.5, marginBottom: 8, flexWrap: 'wrap' }}>
          {breadcrumb.map((seg, i) => (
            <span key={i} style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
              {i > 0 && <ChevronRight size={8} strokeWidth={1.5} color="var(--ink-4)" />}
              <span
                onClick={() => setBrowsePath(browsePath.slice(0, i))}
                style={{ color: i === breadcrumb.length - 1 ? 'var(--ink)' : 'var(--accent-hi)', fontWeight: i === breadcrumb.length - 1 ? 600 : 400, cursor: i === breadcrumb.length - 1 ? 'default' : 'pointer' }}
              >
                {seg}
              </span>
            </span>
          ))}
        </div>

        {/* Folder list */}
        <div style={{ height: 180, border: '1px solid var(--rule-2)', borderRadius: 6, background: 'var(--bg-deep)', overflowY: 'auto', marginBottom: 10 }}>
          {loading ? (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', fontSize: 11, color: 'var(--ink-4)', fontStyle: 'italic' }}>{tr('Chargement…', 'Loading…')}</div>
          ) : folders.length === 0 ? (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', fontSize: 11, color: 'var(--ink-4)', fontStyle: 'italic' }}>{tr('Aucun sous-dossier', 'No subfolders')}</div>
          ) : folders.map((f, i) => (
            <div
              key={i}
              onDoubleClick={() => setBrowsePath([...browsePath, f])}
              style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 10px', cursor: 'default', borderBottom: '1px solid var(--rule)', fontSize: 11, color: 'var(--ink-2)' }}
              onMouseEnter={e => (e.currentTarget.style.background = 'var(--accent-soft)')}
              onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
            >
              <FolderSvg size={18} />
              <span style={{ fontFamily: 'var(--mono)', fontSize: 11, flex: 1 }}>{f}</span>
              <ChevronRight size={9} strokeWidth={1.5} color="var(--ink-4)" />
            </div>
          ))}
        </div>

        {/* Destination */}
        <div style={{ padding: '5px 8px', borderRadius: 5, border: '1px solid var(--rule-2)', background: 'var(--bg-deep)', fontFamily: 'var(--mono)', fontSize: 10.5, marginBottom: 10 }}>
          <span style={{ color: 'var(--ink-4)' }}>{tr('Destination : ', 'Destination: ')}</span>
          <span style={{ color: 'var(--ink-2)', fontWeight: 600 }}>{breadcrumb.join(' / ')}</span>
          {isSameLocation && <span style={{ color: 'var(--err)', marginLeft: 6 }}>{tr('= emplacement actuel', '= current location')}</span>}
          {isInsideItself && <span style={{ color: 'var(--err)', marginLeft: 6 }}>{tr('dossier enfant interdit', 'cannot move into a child folder')}</span>}
        </div>

        {error && <div style={{ fontSize: 11, color: 'var(--err)', fontFamily: 'var(--mono)', marginBottom: 8 }}>{error}</div>}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <div className="btn ghost" onClick={onCancel} style={{ cursor: 'pointer' }}>{tr('Annuler', 'Cancel')}</div>
          <div className="btn primary" onClick={() => void handleConfirm()} style={{ cursor: canConfirm ? 'pointer' : 'default', opacity: canConfirm ? 1 : 0.5 }}>
            {busy ? '…' : tr('Déplacer ici', 'Move here')}
          </div>
        </div>
      </div>
    </div>
  )
}

export function ContextMenu({ x, y, isFavorited, isArchived, locked, canEdit, canDelete, count, onFavorite, onArchive, onToggleLock, onRename, onMove, onDelete, onCopyPath, onCopyHoudiniPath, openInTargets, onClose }: {
  x: number; y: number
  isFavorited: boolean
  isArchived: boolean
  locked: boolean
  canEdit: boolean
  canDelete: boolean
  count: number
  onFavorite:       () => void
  onArchive:        () => void
  onToggleLock?:    () => void
  onRename:         () => void
  onMove:           () => void
  onDelete:         () => void
  onCopyPath?:      () => void
  onCopyHoudiniPath?: () => void
  // Every currently-connected, import-capable DCC for this item (built from live status).
  openInTargets?:   { dcc: string; onClick: () => void }[]
  onClose:          () => void
}) {
  const menuRef = useRef<HTMLDivElement>(null)
  const { tr } = useTr()
  const [openInHovered, setOpenInHovered] = useState(false)
  // "Open in" submenu: opens on the left / moves up when the window has no room
  // (2026-09-26: half of it was off screen, right of the Folder Manager).
  const subRef = useRef<HTMLDivElement>(null)
  const [subFlip, setSubFlip] = useState<{ left: boolean; dy: number }>({ left: false, dy: 0 })
  useLayoutEffect(() => {
    if (!openInHovered || !subRef.current) { setSubFlip({ left: false, dy: 0 }); return }
    const r = subRef.current.getBoundingClientRect()
    const parent = subRef.current.parentElement?.getBoundingClientRect()
    const left = r.right > window.innerWidth - 4 && !!parent && parent.left - r.width >= 4
    const dy = r.bottom > window.innerHeight - 4 ? Math.min(0, window.innerHeight - 4 - r.bottom) : 0
    if (left || dy) setSubFlip({ left, dy })
  }, [openInHovered])

  // Ajuste la position pour rester dans la fenêtre
  const [pos, setPos] = useState({ x, y })
  useEffect(() => {
    if (!menuRef.current) return
    const rect = menuRef.current.getBoundingClientRect()
    const nx = rect.right  > window.innerWidth  ? x - rect.width  : x
    const ny = rect.bottom > window.innerHeight ? y - rect.height : y
    if (nx !== x || ny !== y) setPos({ x: nx, y: ny })
  }, [x, y])

  const row = (label: string, danger = false, onClick?: () => void) => (
    <div
      onClick={onClick}
      style={{
        padding: '6px 12px', fontSize: 11, cursor: onClick ? 'pointer' : 'default',
        color: danger ? 'var(--err)' : 'var(--ink-2)',
        display: 'flex', alignItems: 'center', gap: 7,
        transition: 'background 0.06s',
      }}
      onMouseEnter={e => { if (onClick) e.currentTarget.style.background = danger ? 'rgba(var(--err-rgb),0.1)' : 'var(--accent-soft)' }}
      onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
    >
      {label}
    </div>
  )

  return (
    <div
      ref={menuRef}
      onMouseDown={e => e.stopPropagation()}
      style={{
        position: 'fixed', top: pos.y, left: pos.x, zIndex: 1000,
        background: 'var(--paper)', border: '1px solid var(--rule-2)',
        borderRadius: 7, boxShadow: 'var(--shadow)', minWidth: 180,
        paddingBlock: 4,
      }}
    >
      {row(
        isFavorited ? tr('★ Retirer des Favoris', '★ Remove from Favorites') : tr('☆ Ajouter aux Favoris', '☆ Add to Favorites'),
        false,
        () => { onFavorite(); onClose() },
      )}
      {row(
        isArchived ? tr('Désarchiver', 'Unarchive') : tr('Archiver', 'Archive'),
        false,
        () => { onArchive(); onClose() },
      )}
      {onToggleLock && count === 1 && (
        <>
          <div style={{ height: 1, background: 'var(--rule)', margin: '4px 0' }} />
          {row(locked ? tr('🔓 Déverrouiller', '🔓 Unlock') : tr('🔒 Verrouiller', '🔒 Lock'), false, () => { onToggleLock(); onClose() })}
        </>
      )}
      {onCopyPath && count === 1 && (
        <>
          <div style={{ height: 1, background: 'var(--rule)', margin: '4px 0' }} />
          {row(tr('Copier le chemin', 'Copy path'), false, () => { onCopyPath(); onClose() })}
          {onCopyHoudiniPath && row(tr('Copier le chemin Houdini ($FLUX)', 'Copy Houdini path ($FLUX)'), false, () => { onCopyHoudiniPath(); onClose() })}
        </>
      )}
      {canEdit && (
        <>
          <div style={{ height: 1, background: 'var(--rule)', margin: '4px 0' }} />
          {count === 1 && row(tr('Renommer', 'Rename'), false, () => { onRename(); onClose() })}
          {!locked && row(count > 1 ? tr(`Déplacer (${count})`, `Move (${count})`) : tr('Déplacer', 'Move'), false, () => { onMove(); onClose() })}
        </>
      )}
      {openInTargets && openInTargets.length > 0 && (
        <>
          <div style={{ height: 1, background: 'var(--rule)', margin: '4px 0' }} />
          <div
            style={{ position: 'relative' }}
            onMouseEnter={() => setOpenInHovered(true)}
            onMouseLeave={() => setOpenInHovered(false)}
          >
            <div style={{
              padding: '6px 12px', fontSize: 11, cursor: 'pointer',
              color: 'var(--ink-2)', display: 'flex', alignItems: 'center',
              justifyContent: 'space-between', gap: 7,
              background: openInHovered ? 'var(--accent-soft)' : 'transparent',
              transition: 'background 0.06s',
            }}>
              <span>Open in</span>
              <ChevronRight size={11} strokeWidth={2} />
            </div>
            {openInHovered && (
              <div ref={subRef} style={{
                position: 'absolute', top: subFlip.dy,
                ...(subFlip.left ? { right: '100%' } : { left: '100%' }),
                background: 'var(--paper)', border: '1px solid var(--rule-2)',
                borderRadius: 7, boxShadow: 'var(--shadow)', minWidth: 140, maxWidth: 380,
                overflow: 'hidden', paddingBlock: 4, zIndex: 1001,
              }}>
                {openInTargets.map(target => (
                  <div
                    key={target.dcc}
                    onClick={() => { target.onClick(); onClose() }}
                    title={target.dcc}
                    style={{
                      padding: '6px 12px', fontSize: 11, cursor: 'pointer',
                      color: 'var(--ink-2)', display: 'block',
                      whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                      transition: 'background 0.06s',
                    }}
                    onMouseEnter={e => { e.currentTarget.style.background = 'var(--accent-soft)' }}
                    onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
                  >
                    {target.dcc}
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
      {canDelete && !locked && (
        <>
          <div style={{ height: 1, background: 'var(--rule)', margin: '4px 0' }} />
          {row(count > 1 ? tr(`Supprimer (${count})`, `Delete (${count})`) : tr('Supprimer', 'Delete'), true, () => { onDelete(); onClose() })}
        </>
      )}
    </div>
  )
}

// ── Delete Confirm Modal ───────────────────────────────────────────────────────

export function DeleteModal({ items, onConfirm, onCancel }: {
  items: ExplorerItem[]
  onConfirm: () => void
  onCancel:  () => void
}) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onCancel() }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [onCancel])

  const { tr } = useTr()
  const single = items.length === 1
  const allDirs = items.every(i => i.isDir)

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)', zIndex: 2000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ background: 'var(--paper)', border: '1px solid var(--rule-2)', borderRadius: 10, padding: '22px 24px', minWidth: 300, maxWidth: 380, boxShadow: 'var(--shadow)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
          <Trash2 size={16} strokeWidth={1.75} color="var(--err)" />
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)' }}>
            {single
              ? tr(`Supprimer "${items[0].name}" ?`, `Delete "${items[0].name}"?`)
              : tr(`Supprimer ${items.length} éléments ?`, `Delete ${items.length} items?`)}
          </div>
        </div>
        <div style={{ fontSize: 11, color: 'var(--ink-3)', marginBottom: 20, lineHeight: 1.5 }}>
          {single
            ? items[0].isDir
              ? tr('Ce dossier et tout son contenu seront supprimés définitivement.', 'This folder and all its contents will be permanently deleted.')
              : tr('Ce fichier sera supprimé définitivement.', 'This file will be permanently deleted.')
            : allDirs
              ? tr('Ces dossiers et tout leur contenu seront supprimés définitivement.', 'These folders and all their contents will be permanently deleted.')
              : tr('Ces éléments seront supprimés définitivement.', 'These items will be permanently deleted.')}
          {' '}{tr('Cette action est irréversible.', 'This cannot be undone.')}
        </div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <div className="btn ghost" onClick={onCancel} style={{ cursor: 'pointer' }}>{tr('Annuler', 'Cancel')}</div>
          <div
            className="btn primary"
            onClick={onConfirm}
            style={{ cursor: 'pointer', background: 'var(--err)', borderColor: 'var(--err)' }}
          >
            {tr('Supprimer', 'Delete')}
          </div>
        </div>
      </div>
    </div>
  )
}
