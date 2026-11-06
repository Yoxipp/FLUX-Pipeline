// FirstLaunch.tsx — wizard de premier lancement (workspace + username).

import { useEffect, useState } from 'react'
import { FolderOpen, Lock } from 'lucide-react'
import { api, type UserProfile } from '../api/client'
import { Avatar } from '../components/shared/ui'
import { FluxLogo } from '../components/shared/Logo'

// ── Shared "new artist" fields (first + last name, identifier preview, optional password) ──
// Also used by Login.tsx and Settings > Projet > Artistes.
export interface NewArtistValue {
  first: string; last: string; password: string; confirm: string; remember: boolean
}
export const EMPTY_NEW_ARTIST: NewArtistValue = { first: '', last: '', password: '', confirm: '', remember: false }

// Client-side check, null when the form can be submitted.
export function newArtistError(v: NewArtistValue): string | null {
  if (!v.first.trim() || !v.last.trim()) return 'Prénom et nom requis'
  if (v.password && v.password.length < 4) return 'Mot de passe trop court (4 caractères minimum)'
  if (v.password !== v.confirm) return 'Les mots de passe ne correspondent pas'
  return null
}

export function newArtistPayload(v: NewArtistValue) {
  return {
    first_name: v.first.trim(), last_name: v.last.trim(),
    ...(v.password ? { password: v.password, remember: v.remember } : {}),
  }
}

export function NewArtistFields({ value, onChange, onSubmit, compact }: {
  value: NewArtistValue; onChange: (v: NewArtistValue) => void; onSubmit?: () => void; compact?: boolean
}) {
  const [preview, setPreview] = useState<string | null>(null)
  const set = (patch: Partial<NewArtistValue>) => onChange({ ...value, ...patch })
  const fs = compact ? 11 : 12

  // Debounced identifier preview: the server computes it (accents, collisions).
  useEffect(() => {
    if (!value.first.trim() || !value.last.trim()) { setPreview(null); return }
    let alive = true
    const t = setTimeout(() => {
      api.previewUserId(value.first.trim(), value.last.trim())
        .then(r => { if (alive) setPreview(r.id) })
        .catch(() => { if (alive) setPreview(null) })
    }, 300)
    return () => { alive = false; clearTimeout(t) }
  }, [value.first, value.last])

  const input: React.CSSProperties = {
    padding: compact ? '6px 8px' : '8px 10px', background: 'var(--paper-2)',
    border: '1px solid var(--rule-2)', borderRadius: 7, outline: 'none',
    fontFamily: 'inherit', fontSize: fs, color: 'var(--ink)', boxSizing: 'border-box', minWidth: 0,
  }
  const key = (e: React.KeyboardEvent) => { if (e.key === 'Enter') onSubmit?.() }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={{ display: 'flex', gap: 6 }}>
        <input value={value.first} onChange={e => set({ first: e.target.value })} onKeyDown={key}
          placeholder="Prénom" style={{ ...input, flex: 1, width: '50%' }} />
        <input value={value.last} onChange={e => set({ last: e.target.value })} onKeyDown={key}
          placeholder="Nom" style={{ ...input, flex: 1, width: '50%' }} />
      </div>
      <div style={{ fontSize: 11, color: 'var(--ink-3)', fontFamily: 'var(--mono)', minHeight: 14 }}>
        {preview ? `Identifiant : ${preview}` : 'Identifiant : (prénom et nom requis)'}
      </div>
      <div style={{ display: 'flex', gap: 6 }}>
        <input type="password" value={value.password} onChange={e => set({ password: e.target.value })} onKeyDown={key}
          placeholder="Mot de passe (facultatif)" autoComplete="new-password" style={{ ...input, flex: 1, width: '50%' }} />
        <input type="password" value={value.confirm} onChange={e => set({ confirm: e.target.value })} onKeyDown={key}
          placeholder="Confirmation" autoComplete="new-password" disabled={!value.password}
          style={{ ...input, flex: 1, width: '50%', opacity: value.password ? 1 : 0.5 }} />
      </div>
      {value.password && <RememberCheckbox checked={value.remember} onChange={remember => set({ remember })} />}
    </div>
  )
}

export function RememberCheckbox({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: 'var(--ink-3)', cursor: 'pointer' }}>
      <input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)} />
      Se souvenir sur ce PC
    </label>
  )
}

export function FirstLaunch() {
  const [step, setStep]           = useState<1 | 2>(1)
  const [workspace, setWorkspace] = useState('')
  const [username, setUsername]   = useState('')          // selected existing artist ('' = new artist)
  const [users, setUsers]         = useState<UserProfile[]>([])
  const [newArtist, setNewArtist] = useState<NewArtistValue>(EMPTY_NEW_ARTIST)
  const [password, setPassword]   = useState('')          // existing artist's password
  const [remember, setRemember]   = useState(false)
  const [loading, setLoading]     = useState(false)
  const [error, setError]         = useState<string | null>(null)

  const handleWorkspace = async () => {
    if (!workspace.trim()) { setError('Chemin requis'); return }
    setLoading(true)
    setError(null)
    try {
      const { profiles } = await api.listUserProfilesAt(workspace.trim())
      setUsers(profiles)
    } catch {
      setUsers([])
    }
    setUsername('')
    setLoading(false)
    setStep(2)
  }

  const handleBrowse = async () => {
    const path = await window.electronAPI?.openFolder()
    if (path) setWorkspace(path)
  }

  const selected = users.find(u => u.id === username) ?? null

  const handleFinish = async () => {
    setError(null)
    if (!selected) {
      const err = newArtistError(newArtist)
      if (err) { setError(err); return }
    } else if (selected.has_password && !password) { setError('Mot de passe requis'); return }
    setLoading(true)
    try {
      if (selected) {
        await api.initFirstLaunch(workspace.trim(), selected.id,
          selected.has_password ? { password, remember } : undefined)
      } else {
        await api.initFirstLaunch(workspace.trim(), '', newArtistPayload(newArtist))
      }
      window.location.reload()
    } catch (e) {
      setError((e as Error).message)
      setLoading(false)
    }
  }

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 100,
      background: 'var(--bg-deep)',
      backgroundImage: 'radial-gradient(circle, var(--rule-2) 1px, transparent 1px)',
      backgroundSize: '22px 22px',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      WebkitAppRegion: 'drag',
    } as React.CSSProperties}>

      <div style={{
        width: 360,
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
          <FluxLogo size={30} />
          <div>
            <div style={{ fontFamily: 'var(--mono)', fontWeight: 700, fontSize: 14, letterSpacing: '0.14em', color: 'var(--ink)' }}>FLUX</div>
            <div style={{ fontSize: 11, color: 'var(--ink-4)', letterSpacing: '0.04em' }}>
              {step === 1 ? 'Étape 1 / 2 · Dossier de travail' : 'Étape 2 / 2 · Utilisateur'}
            </div>
          </div>
        </div>

        {/* ── étape 1 : workspace ── */}
        {step === 1 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ fontFamily: 'var(--mono)', fontSize: 10.5, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--ink-4)' }}>
              Dossier de travail de l'équipe
            </div>
            <div style={{ fontSize: 11, color: 'var(--ink-3)', lineHeight: 1.5 }}>
              Chemin local, réseau (\\serveur\pipe) ou OneDrive synchronisé.
            </div>
            <div style={{ display: 'flex', gap: 6 }}>
              <input
                value={workspace}
                onChange={e => setWorkspace(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && void handleWorkspace()}
                placeholder="C:\MonPipe ou \\serveur\pipe"
                autoFocus
                style={{
                  flex: 1, padding: '8px 10px',
                  background: 'var(--paper-2)',
                  border: '1px solid var(--rule-2)',
                  borderRadius: 7, outline: 'none',
                  fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink)',
                  boxSizing: 'border-box',
                }}
              />
              <div
                onClick={() => void handleBrowse()}
                title="Parcourir…"
                style={{
                  width: 32, height: 32, borderRadius: 7, flexShrink: 0,
                  border: '1px solid var(--rule-2)',
                  background: 'var(--paper-2)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  color: 'var(--ink-3)', cursor: 'pointer',
                  transition: 'border-color 0.12s, color 0.12s',
                }}
                onMouseEnter={e => { const el = e.currentTarget as HTMLElement; el.style.borderColor = 'var(--rule-3)'; el.style.color = 'var(--accent-hi)' }}
                onMouseLeave={e => { const el = e.currentTarget as HTMLElement; el.style.borderColor = 'var(--rule-2)'; el.style.color = 'var(--ink-3)' }}
              >
                <FolderOpen size={14} strokeWidth={1.75} />
              </div>
            </div>
          </div>
        )}

        {/* ── étape 2 : utilisateur ── */}
        {step === 2 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>

            {/* utilisateurs existants */}
            {users.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <div style={{ fontFamily: 'var(--mono)', fontSize: 10.5, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--ink-4)', marginBottom: 2 }}>
                  Artistes existants
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 3, maxHeight: 160, overflowY: 'auto' }}>
                  {users.map(p => {
                    const u = p.id
                    const isActive = u === username
                    const full = `${p.first_name} ${p.last_name}`.trim()
                    return (
                      <div
                        key={u}
                        onClick={() => { setUsername(isActive ? '' : u); setPassword(''); setError(null) }}
                        style={{
                          display: 'flex', alignItems: 'center', gap: 10,
                          padding: '7px 10px', borderRadius: 7,
                          background: isActive ? 'var(--accent-soft)' : 'var(--paper-2)',
                          border: '1px solid ' + (isActive ? 'var(--rule-3)' : 'var(--rule)'),
                          cursor: 'pointer',
                          transition: 'border-color 0.12s, background 0.12s',
                        }}
                      >
                        <Avatar ch={u[0].toUpperCase()} size={22} />
                        <span style={{ flex: 1, fontSize: 12, fontWeight: isActive ? 600 : 400, color: isActive ? 'var(--ink)' : 'var(--ink-2)' }}>{full ? `${full} (${u})` : u}</span>
                        {p.has_password && <Lock size={11} strokeWidth={1.75} color="var(--ink-4)" />}
                        {isActive && (
                          <span style={{ fontFamily: 'var(--mono)', fontSize: 10, letterSpacing: '0.08em', color: 'var(--accent-hi)', textTransform: 'uppercase' }}>
                            Sélectionné
                          </span>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            {selected ? (
              selected.has_password && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <div style={{ fontFamily: 'var(--mono)', fontSize: 10.5, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--ink-4)' }}>
                    Mot de passe de {selected.id}
                  </div>
                  <input
                    type="password" value={password} autoFocus autoComplete="current-password"
                    onChange={e => setPassword(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && void handleFinish()}
                    placeholder="Mot de passe"
                    style={{
                      padding: '8px 10px', background: 'var(--paper-2)', border: '1px solid var(--rule-2)',
                      borderRadius: 7, outline: 'none', fontFamily: 'inherit', fontSize: 12, color: 'var(--ink)',
                      boxSizing: 'border-box', width: '100%',
                    }}
                  />
                  <RememberCheckbox checked={remember} onChange={setRemember} />
                </div>
              )
            ) : (
              /* nouvel artiste */
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <div style={{ fontFamily: 'var(--mono)', fontSize: 10.5, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--ink-4)' }}>
                  {users.length > 0 ? 'Ou créer un nouvel artiste' : 'Votre prénom et votre nom'}
                </div>
                <NewArtistFields value={newArtist} onChange={setNewArtist} onSubmit={() => void handleFinish()} />
              </div>
            )}
          </div>
        )}

        {/* erreur */}
        {error && (
          <div style={{ fontSize: 11, color: 'var(--err)', fontFamily: 'var(--mono)' }}>{error}</div>
        )}

        {/* actions */}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          {step === 2 && (
            <div
              onClick={() => setStep(1)}
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
              ← Retour
            </div>
          )}
          <div
            onClick={step === 1 ? () => void handleWorkspace() : () => void handleFinish()}
            style={{
              flex: 1, padding: '7px 16px', borderRadius: 7, textAlign: 'center',
              background: 'var(--accent-soft)',
              border: '1px solid var(--rule-3)',
              fontSize: 11, fontWeight: 600,
              color: 'var(--accent-hi)',
              cursor: loading ? 'default' : 'pointer',
              opacity: loading ? 0.5 : 1,
              transition: 'opacity 0.12s',
            }}
          >
            {loading ? '…' : step === 1 ? 'Suivant →' : 'Démarrer FLUX →'}
          </div>
        </div>
      </div>
    </div>
  )
}
