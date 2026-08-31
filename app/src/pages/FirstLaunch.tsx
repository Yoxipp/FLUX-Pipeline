// FirstLaunch.tsx — wizard de premier lancement (workspace + username).

import { useState } from 'react'
import { FolderOpen } from 'lucide-react'
import { api } from '../api/client'
import { Avatar } from '../components/shared/ui'

export function FirstLaunch() {
  const [step, setStep]           = useState<1 | 2>(1)
  const [workspace, setWorkspace] = useState('')
  const [username, setUsername]   = useState('')
  const [users, setUsers]         = useState<string[]>([])
  const [loading, setLoading]     = useState(false)
  const [error, setError]         = useState<string | null>(null)

  const handleWorkspace = async () => {
    if (!workspace.trim()) { setError('Chemin requis'); return }
    setLoading(true)
    setError(null)
    try {
      const { users: existing } = await api.listUsers()
      setUsers(existing)
    } catch {}
    setLoading(false)
    setStep(2)
  }

  const handleBrowse = async () => {
    const path = await window.electronAPI?.openFolder()
    if (path) setWorkspace(path)
  }

  const handleFinish = async () => {
    if (!username.trim()) { setError('Nom requis'); return }
    setLoading(true)
    setError(null)
    try {
      await api.initFirstLaunch(workspace.trim(), username.trim())
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
          <div style={{
            width: 30, height: 30, borderRadius: 8,
            background: 'var(--accent-soft)', border: '1px solid var(--accent)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontFamily: 'var(--mono)', fontWeight: 700, fontSize: 15,
            color: 'var(--accent-hi)', boxShadow: 'var(--shadow-xs)',
          }}>F</div>
          <div>
            <div style={{ fontFamily: 'var(--mono)', fontWeight: 700, fontSize: 14, letterSpacing: '0.14em', color: 'var(--ink)' }}>FLUX</div>
            <div style={{ fontSize: 10, color: 'var(--ink-4)', letterSpacing: '0.04em' }}>
              {step === 1 ? 'Étape 1 / 2 · Dossier de travail' : 'Étape 2 / 2 · Utilisateur'}
            </div>
          </div>
        </div>

        {/* ── étape 1 : workspace ── */}
        {step === 1 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ fontFamily: 'var(--mono)', fontSize: 9, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--ink-4)' }}>
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
                onMouseEnter={e => { const el = e.currentTarget as HTMLElement; el.style.borderColor = 'var(--accent)'; el.style.color = 'var(--accent-hi)' }}
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
                <div style={{ fontFamily: 'var(--mono)', fontSize: 9, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--ink-4)', marginBottom: 2 }}>
                  Artistes existants
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 3, maxHeight: 160, overflowY: 'auto' }}>
                  {users.map(u => {
                    const isActive = u === username
                    return (
                      <div
                        key={u}
                        onClick={() => setUsername(u)}
                        style={{
                          display: 'flex', alignItems: 'center', gap: 10,
                          padding: '7px 10px', borderRadius: 7,
                          background: isActive ? 'var(--accent-soft)' : 'var(--paper-2)',
                          border: '1px solid ' + (isActive ? 'var(--accent)' : 'var(--rule)'),
                          cursor: 'pointer',
                          transition: 'border-color 0.12s, background 0.12s',
                        }}
                      >
                        <Avatar ch={u[0].toUpperCase()} size={22} />
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
              </div>
            )}

            {/* nouveau nom */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <div style={{ fontFamily: 'var(--mono)', fontSize: 9, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--ink-4)' }}>
                {users.length > 0 ? 'Ou entrer un nouveau nom' : 'Votre prénom'}
              </div>
              <input
                value={username}
                onChange={e => setUsername(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && void handleFinish()}
                placeholder="Milo"
                autoFocus={users.length === 0}
                style={{
                  padding: '8px 10px',
                  background: 'var(--paper-2)',
                  border: '1px solid var(--rule-2)',
                  borderRadius: 7, outline: 'none',
                  fontFamily: 'inherit', fontSize: 12, color: 'var(--ink)',
                  boxSizing: 'border-box', width: '100%',
                }}
              />
            </div>
          </div>
        )}

        {/* erreur */}
        {error && (
          <div style={{ fontSize: 10, color: 'var(--err)', fontFamily: 'var(--mono)' }}>{error}</div>
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
              border: '1px solid var(--accent)',
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
