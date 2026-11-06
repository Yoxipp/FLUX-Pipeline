// Login.tsx — popover de sélection d'utilisateur (déclenché depuis la TitleBar).
// Créer / renommer / supprimer les artistes : Paramètres > Projet > Artistes ; son propre
// compte : Paramètres > User. Le champ de création ne reste ici que si aucun artiste n'existe.

import { useEffect, useState } from 'react'
import { Lock, UserPlus, X } from 'lucide-react'
import { api, type UserProfile } from '../api/client'
import { Avatar } from '../components/shared/ui'
import {
  EMPTY_NEW_ARTIST, NewArtistFields, RememberCheckbox, newArtistError, newArtistPayload,
  type NewArtistValue,
} from './FirstLaunch'

interface Props {
  onDone: () => void
}

export function Login({ onDone }: Props) {
  const [users, setUsers]     = useState<UserProfile[]>([])
  const [loaded, setLoaded]   = useState(false)
  const [selected, setSelected] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [newArtist, setNewArtist] = useState<NewArtistValue>(EMPTY_NEW_ARTIST)
  const [password, setPassword] = useState('')
  const [remember, setRemember] = useState(false)
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState('')
  const [hovered, setHovered]   = useState<string | null>(null)

  const refreshUsers = () => api.listUserProfiles()
    .then(d => setUsers(d.profiles))
    .catch(() => api.listUsers()
      .then(d => setUsers(d.users.map(id => ({ id, first_name: '', last_name: '', has_password: false }))))
      .catch(() => {}))
    .finally(() => setLoaded(true))

  useEffect(() => {
    void refreshUsers()
  }, [])

  // New-artist form: shown when asked, or when no artist exists yet.
  const showNew = creating || (loaded && users.length === 0)
  const selectedProfile = showNew ? null : users.find(u => u.id === selected) ?? null
  const needsPassword = !!selectedProfile?.has_password && !selectedProfile.free_entry

  const enter = async () => {
    setError('')
    if (showNew) {
      const err = newArtistError(newArtist)
      if (err) { setError(err); return }
    } else if (!selectedProfile) return
    setLoading(true)
    try {
      if (showNew) await api.createUser({ ...newArtistPayload(newArtist), switch: true })
      else await api.updateSettings(needsPassword
        ? { username: selectedProfile!.id, password, remember }
        : { username: selectedProfile!.id })
      window.location.reload()
    } catch (e) {
      // 403 "Mot de passe incorrect." and other backend messages are shown as they come.
      setError(e instanceof Error && e.message ? e.message : "Erreur lors du changement d'utilisateur.")
      setLoading(false)
    }
  }

  const canEnter = !loading && (showNew
    ? newArtist.first.trim().length > 0 && newArtist.last.trim().length > 0
    : selectedProfile !== null && (!needsPassword || password.length > 0))

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
          <div style={{ fontFamily: 'var(--mono)', fontSize: 10.5, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--ink-4)' }}>
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
            <div style={{ fontFamily: 'var(--mono)', fontSize: 10, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--ink-4)', marginBottom: 6 }}>
              Artistes
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 3, maxHeight: 160, overflowY: 'auto' }}>
              {users.map(p => {
                const u = p.id
                const isActive = !showNew && u === selected
                const full = `${p.first_name} ${p.last_name}`.trim()
                return (
                  <div
                    key={u}
                    onClick={() => { setSelected(u); setCreating(false); setPassword(''); setError('') }}
                    onMouseEnter={() => setHovered(u)}
                    onMouseLeave={() => setHovered(h => (h === u ? null : h))}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 8,
                      padding: '6px 8px', borderRadius: 7,
                      background: isActive ? 'var(--accent-soft)' : (hovered === u ? 'var(--paper)' : 'transparent'),
                      border: '1px solid ' + (isActive ? 'var(--rule-3)' : 'transparent'),
                      cursor: 'pointer',
                      transition: 'border-color 0.12s, background 0.12s',
                    }}
                  >
                    <Avatar ch={u[0].toUpperCase()} size={20} />

                    <span style={{ flex: 1, fontSize: 11, fontWeight: isActive ? 600 : 400, color: isActive ? 'var(--ink)' : 'var(--ink-2)' }}>{full ? `${full} (${u})` : u}</span>

                    {p.has_password && !p.free_entry && <Lock size={11} strokeWidth={1.75} color="var(--ink-4)" />}
                    {isActive && <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--accent-hi)', textTransform: 'uppercase' }}>✓</span>}
                  </div>
                )
              })}
              <div
                onClick={() => { setCreating(true); setSelected(null); setError('') }}
                style={{
                  display: 'flex', alignItems: 'center', gap: 8, padding: '6px 8px', borderRadius: 7,
                  background: showNew ? 'var(--accent-soft)' : 'transparent',
                  border: '1px solid ' + (showNew ? 'var(--rule-3)' : 'transparent'),
                  cursor: 'pointer', fontSize: 11, color: showNew ? 'var(--ink)' : 'var(--ink-3)',
                }}
              >
                <UserPlus size={14} strokeWidth={1.75} /> Nouvel artiste
              </div>
            </div>
          </div>
        )}

        {/* mot de passe de l'artiste choisi */}
        {needsPassword && <div style={{ borderTop: '1px solid var(--rule)', paddingTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div style={{ fontFamily: 'var(--mono)', fontSize: 10, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--ink-4)' }}>
            Mot de passe
          </div>
          <input
            type="password" autoFocus autoComplete="current-password"
            value={password}
            onChange={e => { setPassword(e.target.value); setError('') }}
            onKeyDown={e => { if (e.key === 'Enter' && canEnter) void enter() }}
            placeholder="Mot de passe"
            style={{
              width: '100%', padding: '7px 10px',
              background: 'var(--bg-deep)',
              border: '1px solid var(--rule-2)',
              borderRadius: 6, outline: 'none',
              fontFamily: 'inherit', fontSize: 11, color: 'var(--ink-2)',
              boxShadow: 'var(--shadow-inset)',
              boxSizing: 'border-box',
            }}
          />
          <RememberCheckbox checked={remember} onChange={setRemember} />
        </div>}

        {/* nouvel artiste : prénom + nom, aperçu de l'identifiant, mot de passe facultatif */}
        {showNew && <div style={{ borderTop: '1px solid var(--rule)', paddingTop: 8 }}>
          <div style={{ fontFamily: 'var(--mono)', fontSize: 10, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--ink-4)', marginBottom: 6 }}>
            Nouvel artiste
          </div>
          <NewArtistFields compact value={newArtist} onChange={v => { setNewArtist(v); setError('') }}
            onSubmit={() => { if (canEnter) void enter() }} />
        </div>}

        {/* erreur */}
        {error && (
          <div style={{ fontSize: 11, color: 'var(--err)', fontFamily: 'var(--mono)' }}>{error}</div>
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
              border: '1px solid ' + (canEnter ? 'var(--rule-3)' : 'var(--rule)'),
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
