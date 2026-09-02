// Login.tsx — popover de sélection / création d'utilisateur (déclenché depuis la TitleBar).

import { useEffect, useRef, useState } from 'react'
import { X, Pencil, Trash2, Check } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '../api/client'
import { Avatar } from '../components/shared/ui'

interface Props {
  onDone: () => void
}

export function Login({ onDone }: Props) {
  const [users, setUsers]     = useState<string[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [newName, setNewName]   = useState('')
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState('')
  const [hovered, setHovered]   = useState<string | null>(null)
  const [renaming, setRenaming] = useState<string | null>(null)
  const [renameVal, setRenameVal] = useState('')
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const refreshUsers = () => api.listUsers().then(d => setUsers(d.users)).catch(() => {})

  useEffect(() => {
    void refreshUsers()
  }, [])

  const doRename = async (old: string) => {
    const next = renameVal.trim().toUpperCase()
    if (!next || next === old) { setRenaming(null); return }
    try {
      const res = await api.renameUser(old, next)
      toast.success(res.message)
      setRenaming(null)
      if (selected === old) setSelected(next)
      await refreshUsers()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Échec du renommage')
    }
  }

  const doDelete = async (name: string) => {
    try {
      const res = await api.deleteUser(name)
      toast.success(res.message)
      setConfirmDelete(null)
      if (selected === name) setSelected(null)
      await refreshUsers()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Échec de la suppression')
    }
  }

  const enter = async () => {
    const name = newName.trim() || selected
    if (!name) return
    setLoading(true)
    setError('')
    try {
      await api.updateSettings({ username: name })
      window.location.reload()
    } catch {
      setError("Erreur lors du changement d'utilisateur.")
      setLoading(false)
    }
  }

  const canEnter = !loading && (newName.trim().length > 0 || selected !== null)

  return (
    <>
      {/* backdrop invisible — clic pour fermer */}
      <div
        style={{ position: 'fixed', inset: 0, zIndex: 19 }}
        onClick={onDone}
      />

      {/* popover card — positionné sous la TitleBar, aligné à droite */}
      <div style={{
        position: 'fixed',
        top: 48, right: 10,
        zIndex: 20,
        width: 280,
        background: 'var(--paper-2)',
        border: '1px solid var(--rule-2)',
        borderRadius: 10,
        boxShadow: 'var(--shadow-md)',
        padding: 14,
        display: 'flex', flexDirection: 'column', gap: 10,
      }}>

        {/* header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ fontFamily: 'var(--mono)', fontSize: 9, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--ink-4)' }}>
            Changer d'utilisateur
          </div>
          <div
            onClick={onDone}
            style={{ width: 20, height: 20, borderRadius: 5, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--ink-3)', cursor: 'pointer' }}
            onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'var(--paper)' }}
            onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'transparent' }}
          >
            <X size={12} strokeWidth={2} />
          </div>
        </div>

        {/* liste des utilisateurs existants */}
        {users.length > 0 && (
          <div style={{ borderTop: '1px solid var(--rule)', paddingTop: 8 }}>
            <div style={{ fontFamily: 'var(--mono)', fontSize: 8, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--ink-4)', marginBottom: 6 }}>
              Artistes
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 3, maxHeight: 160, overflowY: 'auto' }}>
              {users.map(u => {
                const isActive = u === selected
                const isRenaming = renaming === u
                const isConfirming = confirmDelete === u
                return (
                  <div
                    key={u}
                    onClick={() => { if (!isRenaming && !isConfirming) { setSelected(u); setNewName('') } }}
                    onMouseEnter={() => setHovered(u)}
                    onMouseLeave={() => setHovered(h => (h === u ? null : h))}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 8,
                      padding: '6px 8px', borderRadius: 7,
                      background: isActive ? 'var(--accent-soft)' : (hovered === u ? 'var(--paper)' : 'transparent'),
                      border: '1px solid ' + (isActive ? 'var(--accent)' : 'transparent'),
                      cursor: isRenaming || isConfirming ? 'default' : 'pointer',
                      transition: 'border-color 0.12s, background 0.12s',
                    }}
                  >
                    <Avatar ch={u[0].toUpperCase()} size={20} />

                    {isRenaming ? (
                      <input
                        autoFocus
                        value={renameVal}
                        onClick={e => e.stopPropagation()}
                        onChange={e => setRenameVal(e.target.value.toUpperCase())}
                        onKeyDown={e => {
                          if (e.key === 'Enter') void doRename(u)
                          else if (e.key === 'Escape') setRenaming(null)
                        }}
                        style={{
                          flex: 1, minWidth: 0, height: 22, padding: '0 6px',
                          background: 'var(--bg-deep)', border: '1px solid var(--accent)',
                          borderRadius: 5, outline: 'none', fontSize: 11, color: 'var(--ink)',
                          textTransform: 'uppercase',
                        }}
                      />
                    ) : (
                      <span style={{ flex: 1, fontSize: 11, fontWeight: isActive ? 600 : 400, color: isActive ? 'var(--ink)' : 'var(--ink-2)' }}>{u}</span>
                    )}

                    {/* row actions */}
                    {isRenaming ? (
                      <IconBtn title="Valider" onClick={e => { e.stopPropagation(); void doRename(u) }}><Check size={12} /></IconBtn>
                    ) : isConfirming ? (
                      <>
                        <span style={{ fontSize: 9, color: 'var(--err)', fontFamily: 'var(--mono)' }}>Supprimer ?</span>
                        <IconBtn title="Confirmer" danger onClick={e => { e.stopPropagation(); void doDelete(u) }}><Check size={12} /></IconBtn>
                        <IconBtn title="Annuler" onClick={e => { e.stopPropagation(); setConfirmDelete(null) }}><X size={12} /></IconBtn>
                      </>
                    ) : hovered === u ? (
                      <>
                        <IconBtn title="Renommer" onClick={e => { e.stopPropagation(); setRenaming(u); setRenameVal(u); setConfirmDelete(null) }}><Pencil size={11} /></IconBtn>
                        <IconBtn title="Supprimer" danger onClick={e => { e.stopPropagation(); setConfirmDelete(u); setRenaming(null) }}><Trash2 size={11} /></IconBtn>
                      </>
                    ) : isActive ? (
                      <span style={{ fontFamily: 'var(--mono)', fontSize: 8, color: 'var(--accent-hi)', textTransform: 'uppercase' }}>✓</span>
                    ) : null}
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* champ nouvel artiste */}
        <div style={{ borderTop: '1px solid var(--rule)', paddingTop: 8 }}>
          <div style={{ fontFamily: 'var(--mono)', fontSize: 8, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--ink-4)', marginBottom: 6 }}>
            Nouvel artiste
          </div>
          <input
            ref={inputRef}
            value={newName}
            onChange={e => { setNewName(e.target.value.toUpperCase()); if (e.target.value) setSelected(null) }}
            onKeyDown={e => { if (e.key === 'Enter' && canEnter) void enter() }}
            placeholder="NOM DE L'ARTISTE"
            style={{
              width: '100%', padding: '7px 10px',
              background: 'var(--bg-deep)',
              border: '1px solid var(--rule-2)',
              borderRadius: 6, outline: 'none',
              fontFamily: 'inherit', fontSize: 11, color: 'var(--ink-2)',
              textTransform: 'uppercase',
              boxShadow: 'var(--shadow-inset)',
              boxSizing: 'border-box',
            }}
          />
        </div>

        {/* erreur */}
        {error && (
          <div style={{ fontSize: 10, color: 'var(--err)', fontFamily: 'var(--mono)' }}>{error}</div>
        )}

        {/* actions */}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <div
            onClick={onDone}
            style={{
              padding: '6px 12px', borderRadius: 6,
              border: '1px solid var(--rule-2)',
              fontSize: 11, color: 'var(--ink-3)',
              cursor: 'pointer',
              transition: 'background 0.1s',
            }}
            onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'var(--paper)' }}
            onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'transparent' }}
          >
            Annuler
          </div>
          <div
            onClick={() => { if (canEnter) void enter() }}
            style={{
              padding: '6px 14px', borderRadius: 6,
              background: canEnter ? 'var(--accent-soft)' : 'var(--paper)',
              border: '1px solid ' + (canEnter ? 'var(--accent)' : 'var(--rule)'),
              fontSize: 11, fontWeight: 600,
              color: canEnter ? 'var(--accent-hi)' : 'var(--ink-4)',
              cursor: canEnter ? 'pointer' : 'default',
              transition: 'background 0.12s, border-color 0.12s, color 0.12s',
            }}
          >
            {loading ? '…' : 'Entrer →'}
          </div>
        </div>
      </div>
    </>
  )
}

function IconBtn({ children, title, danger, onClick }: {
  children: React.ReactNode
  title: string
  danger?: boolean
  onClick: (e: React.MouseEvent) => void
}) {
  return (
    <div
      onClick={onClick}
      title={title}
      style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        width: 20, height: 20, borderRadius: 5, flexShrink: 0, cursor: 'pointer',
        color: danger ? 'var(--err)' : 'var(--ink-3)',
        border: '1px solid var(--rule-2)', background: 'var(--paper-2)',
      }}
      onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'var(--paper)' }}
      onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'var(--paper-2)' }}
    >
      {children}
    </div>
  )
}
