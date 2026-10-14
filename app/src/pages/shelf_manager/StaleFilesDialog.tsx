// StaleFilesDialog.tsx - after a shelf reinstall: the old FLUX files of that DCC that are
// no longer the real install (duplicate HDA copies, HDAs FLUX no longer ships, old
// backups, older FLUX shelves), each with why. Ticked by default, untick to keep.
// Only FLUX's own files are ever listed by the backend (shelf/stale), never an
// artist's HDA or shelf (2026-10-10).

import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import { useTr } from '../../i18n'

export type StaleItem = { path: string; reason: string }

export function StaleFilesDialog({ dcc, version, items, onDone }: {
  dcc: string
  version: string
  items: StaleItem[]
  onDone: (summary: string | null) => void
}) {
  const { tr } = useTr()
  const [picked, setPicked] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(items.map(i => [i.path, true])))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const chosen = items.filter(i => picked[i.path]).map(i => i.path)
  const all = chosen.length === items.length

  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape' && !busy) onDone(null) }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [busy, onDone])

  const run = async () => {
    if (busy || chosen.length === 0) return
    setBusy(true); setError('')
    try {
      const res = await api.removeStaleShelfFiles(dcc, version, chosen)
      const parts = [tr(`${res.removed.length} ancien(s) fichier(s) FLUX supprime(s)`,
                        `${res.removed.length} old FLUX file(s) removed`)]
      if (res.failed.length) parts.push(tr(`echec : ${res.failed.join(' ; ')}`, `failed: ${res.failed.join(' ; ')}`))
      if (res.skipped.length) parts.push(tr(`${res.skipped.length} ignore(s) (plus perime(s))`, `${res.skipped.length} skipped (no longer stale)`))
      onDone(parts.join(' | '))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setBusy(false)
    }
  }

  const name = (p: string) => p.split(/[\\/]/).pop() ?? p
  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)', zIndex: 10000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ background: 'var(--paper)', border: '1px solid var(--rule-2)', borderRadius: 10, padding: '22px 24px', width: 560, maxWidth: '92vw', maxHeight: '86vh', display: 'flex', flexDirection: 'column', boxShadow: 'var(--shadow)' }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)', marginBottom: 10 }}>
          {tr(`Anciens fichiers FLUX (${dcc} ${version})`, `Old FLUX files (${dcc} ${version})`)}
        </div>
        <div style={{ fontSize: 11, color: 'var(--ink-3)', marginBottom: 12, lineHeight: 1.5 }}>
          {tr("Ces fichiers sont a FLUX mais ne sont plus ceux qu'il vient d'installer. Decoche ce que tu veux garder. Les HDA et shelves qui ne sont pas a FLUX ne sont jamais listes.",
              "These files are FLUX's but no longer the ones it just installed. Untick what you want to keep. HDAs and shelves that are not FLUX's are never listed.")}
        </div>
        <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11, color: 'var(--ink-2)', marginBottom: 8, cursor: 'pointer' }}>
          <input type="checkbox" checked={all} disabled={busy}
                 onChange={() => setPicked(Object.fromEntries(items.map(i => [i.path, !all])))} />
          {tr(`Tout (${chosen.length} / ${items.length})`, `All (${chosen.length} / ${items.length})`)}
        </label>
        <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', marginBottom: 14, display: 'flex', flexDirection: 'column', gap: 6,
                      borderTop: '1px solid var(--rule)', paddingTop: 8 }}>
          {items.map(i => (
            <label key={i.path} title={i.path}
                   style={{ display: 'flex', gap: 8, alignItems: 'flex-start', cursor: busy ? 'default' : 'pointer' }}>
              <input type="checkbox" checked={!!picked[i.path]} disabled={busy} style={{ marginTop: 2 }}
                     onChange={() => setPicked(p => ({ ...p, [i.path]: !p[i.path] }))} />
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ fontSize: 11.5, color: 'var(--ink)' }}>{name(i.path)}</div>
                <div style={{ fontSize: 11, color: 'var(--ink-3)' }}>{i.reason}</div>
                <div style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-4)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{i.path}</div>
              </div>
            </label>
          ))}
        </div>
        {error && <div style={{ fontSize: 11, color: 'var(--err)', marginBottom: 10, whiteSpace: 'pre-wrap' }}>{error}</div>}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <div className="btn ghost" onClick={() => { if (!busy) onDone(null) }} style={{ cursor: busy ? 'default' : 'pointer' }}>
            {tr('Tout garder', 'Keep all')}
          </div>
          <div className="btn" onClick={() => void run()}
               style={{ cursor: chosen.length && !busy ? 'pointer' : 'not-allowed', opacity: chosen.length && !busy ? 1 : 0.5,
                        background: 'var(--err)', color: '#fff', borderColor: 'var(--err)' }}>
            {busy ? tr('Suppression...', 'Removing...') : tr(`Supprimer (${chosen.length})`, `Remove (${chosen.length})`)}
          </div>
        </div>
      </div>
    </div>
  )
}
