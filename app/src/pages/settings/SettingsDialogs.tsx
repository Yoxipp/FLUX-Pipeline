// SettingsDialogs.tsx - the two guarded confirmations of the Settings page (moved from
// TitleBar with the settings popover, retake 06): open Avance (type Understand) and
// uninstall FLUX (type the phrase, list what goes / stays).

import { useEffect, useState } from 'react'
import { api } from '../../api/client'

/* ── "Parametres avances": warning, then type Understand (N8) ── */
const ADVANCED_PHRASE = 'Understand'

export function AdvancedConfirm({ onConfirm, onCancel }: { onConfirm: () => void; onCancel: () => void }) {
  const [typed, setTyped] = useState('')
  const match = typed === ADVANCED_PHRASE
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onCancel() }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [onCancel])
  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)', zIndex: 10000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ background: 'var(--paper)', border: '1px solid var(--rule-2)', borderRadius: 10, padding: '22px 24px', minWidth: 340, maxWidth: 420, boxShadow: 'var(--shadow)' }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)', marginBottom: 10 }}>Parametres avances</div>
        <div style={{ fontSize: 11, color: 'var(--ink-3)', marginBottom: 14, lineHeight: 1.5 }}>
          Modifier ces reglages peut casser le projet (unites USD, stockage des versions, publish).
          A ne toucher que si tu sais ce que tu fais.
        </div>
        <div style={{ fontSize: 11, color: 'var(--ink-2)', marginBottom: 8 }}>
          Tape <code style={{ fontFamily: 'var(--mono)', fontSize: 11, background: 'var(--paper-2)', border: '1px solid var(--rule)', borderRadius: 4, padding: '1px 5px', color: 'var(--ink)' }}>{ADVANCED_PHRASE}</code> pour continuer.
        </div>
        <input
          autoFocus value={typed} onChange={e => setTyped(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && match) onConfirm() }}
          placeholder={ADVANCED_PHRASE} spellCheck={false} autoCapitalize="off" autoCorrect="off"
          style={{ width: '100%', boxSizing: 'border-box', marginBottom: 18, padding: '7px 10px', fontSize: 12, fontFamily: 'var(--mono)',
                   background: 'var(--paper-2)', color: 'var(--ink)', border: `1px solid ${match ? 'var(--rule-3)' : 'var(--rule-2)'}`, borderRadius: 6, outline: 'none' }}
        />
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <div className="btn ghost" onClick={onCancel} style={{ cursor: 'pointer' }}>Annuler</div>
          <div className="btn primary" onClick={() => { if (match) onConfirm() }}
               style={{ cursor: match ? 'pointer' : 'not-allowed', opacity: match ? 1 : 0.5 }}>
            Ouvrir
          </div>
        </div>
      </div>
    </div>
  )
}

/* ── "Desinstaller FLUX": list what goes / stays, then type the phrase ── */
const UNINSTALL_PHRASE = 'Understand'
type UninstallPlan = { remove: { label: string; paths: string[] }[]; keep: string[] }

export function UninstallConfirm({ onCancel }: { onCancel: () => void }) {
  const [typed, setTyped] = useState('')
  const [plan, setPlan] = useState<UninstallPlan | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const match = typed === UNINSTALL_PHRASE
  useEffect(() => {
    api.getUninstallPlan().then(setPlan).catch(e => setError(e instanceof Error ? e.message : String(e)))
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onCancel() }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [onCancel])

  const run = async () => {
    if (!match || busy) return
    setBusy(true); setError('')
    const res = await window.electronAPI?.uninstallFlux?.()
    if (!res) { setError('Desinstallation indisponible dans cette fenetre.'); setBusy(false); return }
    if (!res.ok) {
      setError(res.reason === 'dev'
        ? "Mode dev : FLUX n'est pas installe, la desinstallation ne marche que dans FLUX installe."
        : `Le desinstalleur n'a pas pu demarrer : ${res.reason}`)
      setBusy(false)
    }
    // ok: the uninstaller is running and FLUX quits.
  }

  const code = { fontFamily: 'var(--mono)', fontSize: 11, background: 'var(--paper-2)', border: '1px solid var(--rule)', borderRadius: 4, padding: '1px 5px', color: 'var(--ink)' } as const
  const ready = match && !busy
  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)', zIndex: 10000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ background: 'var(--paper)', border: '1px solid var(--rule-2)', borderRadius: 10, padding: '22px 24px', width: 480, maxWidth: '92vw', maxHeight: '86vh', display: 'flex', flexDirection: 'column', boxShadow: 'var(--shadow)' }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)', marginBottom: 10 }}>Desinstaller FLUX</div>
        <div style={{ fontSize: 11, color: 'var(--ink-3)', marginBottom: 12, lineHeight: 1.5 }}>
          FLUX se ferme et son desinstalleur se lance. Il retire l'application et tout ce que FLUX a ajoute
          sur ce poste. C'est le meme que <code style={code}>Uninstall FLUX.exe</code> a cote de FLUX.exe.
        </div>
        <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', marginBottom: 14, display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div>
            <div className="cap" style={{ marginBottom: 4 }}>Supprime</div>
            {!plan && !error && <div style={{ fontSize: 11.5, color: 'var(--ink-4)' }}>Analyse du poste...</div>}
            {plan && plan.remove.length === 0 && (
              <div style={{ fontSize: 11.5, color: 'var(--ink-4)' }}>Aucune trace FLUX dans les logiciels.</div>
            )}
            {plan?.remove.map(r => (
              <div key={r.label} style={{ marginBottom: 5 }}>
                <div style={{ fontSize: 11, color: 'var(--ink)' }}>{r.label}</div>
                {r.paths.slice(0, 4).map(p => (
                  <div key={p} title={p} style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-4)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p}</div>
                ))}
                {r.paths.length > 4 && (
                  <div style={{ fontSize: 11, color: 'var(--ink-4)' }}>+ {r.paths.length - 4} autre(s)</div>
                )}
              </div>
            ))}
            <div style={{ fontSize: 11.5, color: 'var(--ink-3)' }}>+ l'application FLUX, ses raccourcis et son entree dans Windows</div>
          </div>
          {plan && (
            <div>
              <div className="cap" style={{ marginBottom: 4 }}>Garde</div>
              {plan.keep.map(k => <div key={k} style={{ fontSize: 11.5, color: 'var(--ink-3)', lineHeight: 1.5 }}>{k}</div>)}
            </div>
          )}
        </div>
        {error && <div style={{ fontSize: 11, color: 'var(--err)', marginBottom: 10, whiteSpace: 'pre-wrap' }}>{error}</div>}
        <div style={{ fontSize: 11, color: 'var(--ink-2)', marginBottom: 8 }}>
          Tape <code style={code}>{UNINSTALL_PHRASE}</code> pour confirmer.
        </div>
        <input
          autoFocus value={typed} onChange={e => setTyped(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') void run() }}
          placeholder={UNINSTALL_PHRASE} spellCheck={false} autoCapitalize="off" autoCorrect="off"
          style={{ width: '100%', boxSizing: 'border-box', marginBottom: 18, padding: '7px 10px', fontSize: 12, fontFamily: 'var(--mono)',
                   background: 'var(--paper-2)', color: 'var(--ink)', border: `1px solid ${match ? 'var(--err)' : 'var(--rule-2)'}`, borderRadius: 6, outline: 'none' }}
        />
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <div className="btn ghost" onClick={onCancel} style={{ cursor: 'pointer' }}>Annuler</div>
          <div className="btn" onClick={() => void run()}
               style={{ cursor: ready ? 'pointer' : 'not-allowed', opacity: ready ? 1 : 0.5, background: 'var(--err)', color: '#fff', borderColor: 'var(--err)' }}>
            {busy ? 'Lancement...' : 'Desinstaller'}
          </div>
        </div>
      </div>
    </div>
  )
}
