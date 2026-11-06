// SupEntryBanner — a supervisor is inside another artist's account (ADR 0087).
// Always visible while it lasts, with the only way back. Flat fill, no glow.

import { useState } from 'react'
import { UserRound } from 'lucide-react'
import { api } from '../../api/client'
import type { Settings } from '../../types'

export function SupEntryBanner({ entry }: { entry: NonNullable<Settings['sup_entry']> }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const leave = async () => {
    setBusy(true)
    setError('')
    try {
      await api.updateSettings({ username: entry.by })
      window.location.reload()
    } catch (e) {
      setError(e instanceof Error && e.message ? e.message : 'Retour impossible.')
      setBusy(false)
    }
  }

  return (
    <div role="status" style={{
      display: 'flex', alignItems: 'center', gap: 10, padding: '6px 14px',
      background: 'var(--accent-soft)', borderBottom: '1px solid var(--rule-2)',
      fontFamily: 'var(--sans)', fontSize: 11, color: 'var(--ink)',
    }}>
      <UserRound size={13} strokeWidth={1.75} aria-hidden />
      <span style={{ flex: 1 }}>
        Connecté en tant que <strong>{entry.user}</strong>, ouvert par {entry.by} sur le projet {entry.project} seulement.
        {error && <span style={{ color: 'var(--err)', marginLeft: 8 }}>{error}</span>}
      </span>
      <button type="button" className="btn" disabled={busy} onClick={() => void leave()}>
        Revenir à mon compte
      </button>
    </div>
  )
}
