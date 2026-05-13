// FirstLaunch.tsx — wizard de premier lancement (workspace + username).

import { useState } from 'react'
import { api } from '../api/client'

export function FirstLaunch() {
  const [step, setStep]           = useState<1 | 2>(1)
  const [workspace, setWorkspace] = useState('')
  const [username, setUsername]   = useState('')
  const [users, setUsers]         = useState<string[]>([])
  const [loading, setLoading]     = useState(false)
  const [error, setError]         = useState<string | null>(null)

  const handleWorkspace = async () => {
    if (!workspace.trim()) {
      setError('Chemin requis')
      return
    }
    setLoading(true)
    try {
      const { users: existing } = await api.listUsers()
      setUsers(existing)
      setStep(2)
    } catch {
      setStep(2) // continue même si l'API échoue
    } finally {
      setLoading(false)
    }
  }

  const handleBrowse = async () => {
    const path = await window.electronAPI?.openFolder()
    if (path) setWorkspace(path)
  }

  const handleFinish = async () => {
    if (!username.trim()) {
      setError('Nom requis')
      return
    }
    setLoading(true)
    setError(null)
    try {
      await api.initFirstLaunch(workspace.trim(), username.trim())
      // Rechargement complet pour que App relise les settings
      window.location.reload()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      className="flex items-center justify-center h-screen"
      style={{ backgroundColor: 'var(--color-bg)' }}
    >
      <div
        className="w-96 p-8 rounded border"
        style={{ backgroundColor: 'var(--color-surface)', borderColor: '#2a2a2a' }}
      >
        <h1 className="text-lg font-bold mb-1" style={{ color: 'var(--color-accent)' }}>
          FLUX
        </h1>
        <p className="text-xs text-gray-500 mb-6">
          {step === 1 ? 'Étape 1 / 2 — Dossier de travail' : 'Étape 2 / 2 — Utilisateur'}
        </p>

        {step === 1 && (
          <>
            <label className="block text-sm mb-2">Dossier de travail de l'équipe</label>
            <p className="text-xs text-gray-500 mb-3">
              Peut être un chemin local, réseau (\\serveur\pipe) ou OneDrive synchronisé.
            </p>
            <div className="flex gap-2 mb-4">
              <input
                className="flex-1 bg-black/30 border rounded px-3 py-2 text-sm font-mono outline-none focus:border-gray-500"
                style={{ borderColor: '#2a2a2a' }}
                placeholder="C:\MonPipe ou \\serveur\pipe"
                value={workspace}
                onChange={(e) => setWorkspace(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && void handleWorkspace()}
              />
              <button
                onClick={() => void handleBrowse()}
                className="px-3 py-2 text-xs border rounded hover:bg-white/5"
                style={{ borderColor: '#444' }}
              >
                …
              </button>
            </div>
          </>
        )}

        {step === 2 && (
          <>
            <label className="block text-sm mb-2">Votre prénom</label>
            <input
              className="w-full bg-black/30 border rounded px-3 py-2 text-sm mb-3 outline-none focus:border-gray-500"
              style={{ borderColor: '#2a2a2a' }}
              placeholder="Milo"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && void handleFinish()}
              autoFocus
            />
            {users.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mb-4">
                {users.map((u) => (
                  <button
                    key={u}
                    onClick={() => setUsername(u)}
                    className="text-xs px-2 py-1 border rounded hover:bg-white/5"
                    style={{ borderColor: '#333' }}
                  >
                    {u}
                  </button>
                ))}
              </div>
            )}
          </>
        )}

        {error && <p className="text-xs text-red-400 mb-3">{error}</p>}

        <button
          onClick={step === 1 ? () => void handleWorkspace() : () => void handleFinish()}
          disabled={loading}
          className="w-full py-2 rounded text-sm font-semibold transition-opacity hover:opacity-80 disabled:opacity-40"
          style={{ backgroundColor: 'var(--color-accent)' }}
        >
          {loading ? '…' : step === 1 ? 'Suivant' : 'Démarrer FLUX'}
        </button>
      </div>
    </div>
  )
}
