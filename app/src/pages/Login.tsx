// Login.tsx — écran de sélection / création d'utilisateur.

import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { Avatar } from '../components/shared/ui'

interface Props {
  onDone: () => void
}

export function Login({ onDone }: Props) {
  const [users, setUsers]         = useState<string[]>([])
  const [selected, setSelected]   = useState<string | null>(null)
  const [newMode, setNewMode]     = useState(false)
  const [newName, setNewName]     = useState('')
  const [loading, setLoading]     = useState(false)
  const [error, setError]         = useState('')

  useEffect(() => {
    api.listUsers().then(d => setUsers(d.users)).catch(() => {})
  }, [])

  const enter = async () => {
    const name = newMode ? newName.trim() : selected
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

  const canEnter = newMode ? newName.trim().length > 0 : selected !== null

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 100,
      background: 'var(--bg-deep)',
      backgroundImage: 'radial-gradient(circle, var(--rule-2) 1px, transparent 1px)',
      backgroundSize: '22px 22px',
      display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
      WebkitAppRegion: 'drag',
    } as React.CSSProperties}>

      {/* card */}
      <div style={{
        width: 380,
        background: 'var(--paper)',
        border: '1px solid var(--rule-2)',
        borderRadius: 14,
        boxShadow: 'var(--shadow-lg)',
        padding: '28px 28px 24px',
        display: 'flex', flexDirection: 'column', gap: 20,
        WebkitAppRegion: 'no-drag',
      } as React.CSSProperties}>

        {/* logo + titre */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{
            width: 30, height: 30, borderRadius: 8,
            background: 'var(--accent-soft)', border: '1px solid var(--accent)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontFamily: 'var(--mono)', fontWeight: 700, fontSize: 15,
            color: 'var(--accent-hi)',
            boxShadow: 'var(--shadow-xs)',
          }}>F</div>
          <div>
            <div style={{ fontFamily: 'var(--mono)', fontWeight: 700, fontSize: 14, letterSpacing: '0.14em', color: 'var(--ink)' }}>FLUX</div>
            <div style={{ fontSize: 10, color: 'var(--ink-4)', letterSpacing: '0.04em' }}>Pipeline Tool</div>
          </div>
        </div>

        {/* section utilisateurs */}
        {!newMode && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <div style={{ fontFamily: 'var(--mono)', fontSize: 9, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--ink-4)', marginBottom: 2 }}>
              Choisir un utilisateur
            </div>

            {users.length === 0 && (
              <div style={{ fontSize: 11, color: 'var(--ink-4)', fontStyle: 'italic', padding: '6px 0' }}>Chargement…</div>
            )}

            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 220, overflowY: 'auto' }}>
              {users.map(u => {
                const isActive = u === selected
                return (
                  <div
                    key={u}
                    onClick={() => setSelected(u)}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 10,
                      padding: '8px 12px', borderRadius: 8,
                      background: isActive ? 'var(--accent-soft)' : 'var(--paper-2)',
                      border: '1px solid ' + (isActive ? 'var(--accent)' : 'var(--rule)'),
                      cursor: 'pointer',
                      transition: 'border-color 0.12s, background 0.12s',
                    }}
                  >
                    <Avatar ch={u[0].toUpperCase()} size={26} />
                    <span style={{ flex: 1, fontSize: 12, fontWeight: isActive ? 600 : 400, color: isActive ? 'var(--ink)' : 'var(--ink-2)' }}>{u}</span>
                    {isActive && (
                      <span style={{ fontFamily: 'var(--mono)', fontSize: 8, letterSpacing: '0.08em', color: 'var(--accent-hi)', textTransform: 'uppercase' }}>
                        Sélectionné
                      </span>
                    )}
                  </div>
                )
              })}
            </div>

            <div
              onClick={() => { setNewMode(true); setSelected(null) }}
              style={{
                marginTop: 2,
                padding: '7px 12px',
                borderRadius: 8,
                border: '1px dashed var(--rule-2)',
                fontSize: 11, color: 'var(--ink-4)',
                cursor: 'pointer',
                textAlign: 'center',
                transition: 'border-color 0.12s, color 0.12s',
              }}
              onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = 'var(--accent)'; (e.currentTarget as HTMLElement).style.color = 'var(--accent-hi)' }}
              onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = 'var(--rule-2)'; (e.currentTarget as HTMLElement).style.color = 'var(--ink-4)' }}
            >
              + Nouvel artiste
            </div>
          </div>
        )}

        {/* section nouvel artiste */}
        {newMode && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ fontFamily: 'var(--mono)', fontSize: 9, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--ink-4)' }}>
              Nouvel artiste
            </div>
            <input
              autoFocus
              value={newName}
              onChange={e => setNewName(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && canEnter && !loading) void enter() }}
              placeholder="Nom d'utilisateur…"
              style={{
                width: '100%', padding: '8px 12px',
                background: 'var(--paper-2)',
                border: '1px solid var(--rule-2)',
                borderRadius: 8,
                fontFamily: 'inherit', fontSize: 12, color: 'var(--ink)',
                outline: 'none',
                boxSizing: 'border-box',
              }}
            />
            <div
              onClick={() => { setNewMode(false); setNewName('') }}
              style={{ fontSize: 10, color: 'var(--ink-4)', cursor: 'pointer', textAlign: 'right' }}
            >
              ← Retour à la liste
            </div>
          </div>
        )}

        {/* erreur */}
        {error && (
          <div style={{ fontSize: 10, color: 'var(--err)', fontFamily: 'var(--mono)' }}>{error}</div>
        )}

        {/* actions */}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <div
            onClick={onDone}
            style={{
              padding: '7px 14px', borderRadius: 7,
              border: '1px solid var(--rule-2)',
              fontSize: 11, color: 'var(--ink-3)',
              cursor: 'pointer',
              transition: 'background 0.1s',
            }}
            onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'var(--paper-2)' }}
            onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'transparent' }}
          >
            Annuler
          </div>
          <div
            onClick={() => { if (canEnter && !loading) void enter() }}
            style={{
              padding: '7px 16px', borderRadius: 7,
              background: canEnter ? 'var(--accent-soft)' : 'var(--paper-2)',
              border: '1px solid ' + (canEnter ? 'var(--accent)' : 'var(--rule)'),
              fontSize: 11, fontWeight: 600,
              color: canEnter ? 'var(--accent-hi)' : 'var(--ink-4)',
              cursor: canEnter && !loading ? 'pointer' : 'default',
              transition: 'background 0.12s, border-color 0.12s, color 0.12s',
              display: 'flex', alignItems: 'center', gap: 6,
            }}
          >
            {loading ? 'Chargement…' : 'Entrer dans le pipeline →'}
          </div>
        </div>
      </div>
    </div>
  )
}
