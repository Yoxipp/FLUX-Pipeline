// Login.tsx — popover de sélection / création d'utilisateur (déclenché depuis la TitleBar).

import { useEffect, useRef, useState } from 'react'
import { X } from 'lucide-react'
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
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    api.listUsers().then(d => setUsers(d.users)).catch(() => {})
  }, [])

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
                return (
                  <div
                    key={u}
                    onClick={() => { setSelected(u); setNewName('') }}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 8,
                      padding: '6px 8px', borderRadius: 7,
                      background: isActive ? 'var(--accent-soft)' : 'transparent',
                      border: '1px solid ' + (isActive ? 'var(--accent)' : 'transparent'),
                      cursor: 'pointer',
                      transition: 'border-color 0.12s, background 0.12s',
                    }}
                    onMouseEnter={e => { if (!isActive) (e.currentTarget as HTMLElement).style.background = 'var(--paper)' }}
                    onMouseLeave={e => { if (!isActive) (e.currentTarget as HTMLElement).style.background = 'transparent' }}
                  >
                    <Avatar ch={u[0].toUpperCase()} size={20} />
                    <span style={{ flex: 1, fontSize: 11, fontWeight: isActive ? 600 : 400, color: isActive ? 'var(--ink)' : 'var(--ink-2)' }}>{u}</span>
                    {isActive && (
                      <span style={{ fontFamily: 'var(--mono)', fontSize: 8, color: 'var(--accent-hi)', textTransform: 'uppercase' }}>✓</span>
                    )}
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
            onChange={e => { setNewName(e.target.value); if (e.target.value) setSelected(null) }}
            onKeyDown={e => { if (e.key === 'Enter' && canEnter) void enter() }}
            placeholder="Nom d'utilisateur…"
            style={{
              width: '100%', padding: '7px 10px',
              background: 'var(--bg-deep)',
              border: '1px solid var(--rule-2)',
              borderRadius: 6, outline: 'none',
              fontFamily: 'inherit', fontSize: 11, color: 'var(--ink)',
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
