// DiscordLink.tsx - link the artist's Discord account with a /link code (ADR 0073).
// Linked: a check, the Discord account, Changer / Délier. Not linked: two short steps.
// Used by Paramètres > User > Notifications téléphone and the first-run dialog (WelcomeDialog).

import { useState } from 'react'
import { CircleCheck, Copy, Link2, Unlink } from 'lucide-react'
import { toast } from 'sonner'
import { notifyApi, type NotifyMe } from '../../api/notify'
import { Btn } from '../../components/shared/ui'

const LINK_CODE = /^[A-Z0-9]{8}$/
const row = { display: 'flex', alignItems: 'center', gap: 8 } as const
const hint = { fontSize: 11, color: 'var(--ink-4)', lineHeight: 1.5 } as const
const num = {
  width: 16, height: 16, borderRadius: '50%', flex: 'none', display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
  fontSize: 10, fontWeight: 700, background: 'var(--accent-soft)', color: 'var(--accent-hi)',
} as const
const inputStyle = {
  height: 26, padding: '0 8px', fontSize: 12, letterSpacing: '.12em', fontFamily: 'var(--mono)', background: 'var(--paper-2)', color: 'var(--ink)',
  border: '1px solid var(--rule-2)', borderRadius: 5, outline: 'none', boxSizing: 'border-box', width: 130,
} as const

/** Keeps only the 8 code characters of a pasted /link answer ("Ton code : **ABCD2345** ..."). */
export function cleanLinkCode(raw: string): string {
  const up = raw.toUpperCase()
  const bold = up.match(/\*\*([A-Z0-9]{8})\*\*/)
  return bold ? bold[1] : up.replace(/[^A-Z0-9]/g, '').slice(0, 8)
}

export function discordLabel(me: NotifyMe): string {
  return me.prefs.discord_name || `#${me.prefs.discord_id}`
}

export function DiscordLink({ project, me, onChange }: { project: string; me: NotifyMe; onChange: (me: NotifyMe) => void }) {
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [changing, setChanging] = useState(false)

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true)
    try {
      await fn()
      onChange(await notifyApi.me(project))
      setCode(''); setChanging(false)
      toast.success(ok)
    } catch (e) { toast.error(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) }
  }
  const link = (value: string) => run(() => notifyApi.linkDiscord(value, project), 'Compte Discord lié')
  const onCode = (raw: string) => {
    const value = cleanLinkCode(raw)
    setCode(value)
    if (LINK_CODE.test(value) && !busy) void link(value)   // complete code (usually pasted): link at once
  }

  if (!me.project_has_bot) {
    return <div style={hint}>Le projet n'a pas encore de bot Discord : un lead l'ajoute dans Paramètres &gt; Projet.</div>
  }

  if (me.discord_linked && !changing) {
    return (
      <div style={row}>
        <CircleCheck size={15} strokeWidth={2} color="var(--ok)" />
        <span style={{ flex: 1, fontSize: 12, color: 'var(--ink-2)' }}>
          Discord lié : <b style={{ color: 'var(--ink)' }}>{discordLabel(me)}</b>
        </span>
        <Btn sm ghost disabled={busy} onClick={() => setChanging(true)}><Link2 size={11} strokeWidth={1.75} /> Changer</Btn>
        <Btn sm ghost disabled={busy} onClick={() => void run(() => notifyApi.setMe({ discord_id: '' }, project), 'Discord délié')}>
          <Unlink size={11} strokeWidth={1.75} /> Délier
        </Btn>
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={row}>
        <span style={num}>1</span>
        <span style={{ fontSize: 12, color: 'var(--ink-2)' }}>Dans Discord, tape</span>
        <button type="button" title="Copier /link" onClick={() => { void navigator.clipboard?.writeText('/link'); toast.success('/link copié') }}
          style={{ display: 'inline-flex', alignItems: 'center', gap: 4, padding: '1px 6px', fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--ink)', background: 'var(--paper-2)', border: '1px solid var(--rule-2)', borderRadius: 4, cursor: 'pointer' }}>
          /link <Copy size={10} strokeWidth={1.75} color="var(--ink-4)" />
        </button>
        <span style={hint}>sur le serveur du projet</span>
      </div>
      <div style={row}>
        <span style={num}>2</span>
        <span style={{ fontSize: 12, color: 'var(--ink-2)' }}>Colle le code ici</span>
        <input style={inputStyle} value={code} placeholder="ABCD2345" disabled={busy} aria-label="Code de /link"
          onChange={e => onCode(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && LINK_CODE.test(code)) void link(code) }} />
        <Btn sm primary disabled={busy || !LINK_CODE.test(code)} onClick={() => void link(code)}>Lier</Btn>
        {changing && <Btn sm ghost disabled={busy} onClick={() => { setChanging(false); setCode('') }}>Annuler</Btn>}
      </div>
    </div>
  )
}
