// DiscordSettings.tsx - Discord notifications (ADR 0062, 0073, 0091), Parametres > User and > Projet.
// User: Discord on / off, account linked by /link (DiscordLink.tsx) or an ID typed by hand when the
// project has no bot (webhook only), test.
// Project: the bot (token on the host PCs, invite), the webhook (fallback while the bot is offline,
// ADR 0073), grouping delay and text options. ntfy and the Team <-> Discord bridge are gone (ADR 0091).

import { useEffect, useState } from 'react'
import { BellRing, Bot, ChevronRight, Send, UserPlus, Users } from 'lucide-react'
import { toast } from 'sonner'
import { notifyApi, type NotifyBot, type NotifyChannel, type NotifyMe, type NotifyProject, type NotifyType } from '../../api/notify'
import { Btn, SecTitle } from '../../components/shared/ui'
import { DiscordLink } from './DiscordLink'

const card = { padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 8 } as const
const row = { display: 'flex', alignItems: 'center', gap: 8 } as const
const hint = { fontSize: 11, color: 'var(--ink-4)', lineHeight: 1.5 } as const
const label = { width: 100, fontSize: 11, color: 'var(--ink-2)', flex: 'none' } as const
const inputStyle = {
  height: 26, padding: '0 8px', fontSize: 11, background: 'var(--paper-2)', color: 'var(--ink)',
  border: '1px solid var(--rule-2)', borderRadius: 5, outline: 'none', boxSizing: 'border-box', flex: 1,
} as const
const selectStyle = { height: 24, fontSize: 11, background: 'var(--paper-2)', color: 'var(--ink)', border: '1px solid var(--rule-2)', borderRadius: 5 } as const
const SHARED_NOTE = 'Le texte envoyé : type, entité, auteur, et le message du chat ou le titre du calendrier si le projet l\'autorise. Jamais de chemin.'
const DEV_PORTAL = 'https://discord.com/developers/applications'
const err = (e: unknown) => toast.error(e instanceof Error ? e.message : String(e))
// Per type opt-out (ADR 0091): what a DM can be about. Buttons: tasks, retakes, calendar proposals.
const TYPES: { id: NotifyType; label: string }[] = [
  { id: 'task', label: 'Tâches assignées' }, { id: 'retake', label: 'Retakes' }, { id: 'calendar', label: 'Calendrier' },
  { id: 'mention', label: 'Mentions' }, { id: 'publish', label: 'Publishs suivis' },
]

export function DiscordUser({ project }: { project: string | null }) {
  const [me, setMe] = useState<NotifyMe | null>(null)
  const [discordId, setDiscordId] = useState('')
  const [busy, setBusy] = useState(false)

  const load = (data: NotifyMe) => { setMe(data); setDiscordId(data.prefs.discord_id) }
  useEffect(() => { notifyApi.me(project).then(load).catch(err) }, [project])

  const save = async (patch: { channel?: NotifyChannel; discord_id?: string; muted?: NotifyType[] }, ok?: string) => {
    setBusy(true)
    try {
      const res = await notifyApi.setMe(patch, project)
      setMe(m => (m ? { ...m, prefs: res.prefs, has_channel: res.has_channel } : m))
      setDiscordId(res.prefs.discord_id)
      if (ok) toast.success(ok)
    } catch (e) { err(e) } finally { setBusy(false) }
  }
  const test = async () => {
    setBusy(true)
    try {
      const res = await notifyApi.test(project)
      if (res.ok) toast.success('Test envoyé : regarde Discord')
      else if (res.reason === 'no_channel') toast.error('Discord pas prêt : lie ton compte (/link) ou demande un webhook au lead')
      else toast.error(`Envoi refusé par Discord (HTTP ${res.status ?? 0})`)
    } catch (e) { err(e) } finally { setBusy(false) }
  }

  if (!me) return null
  const on = me.prefs.channel === 'discord'
  return (
    <>
      <SecTitle>Notifications Discord</SecTitle>
      <div className="card" style={card}>
        <label style={{ ...row, cursor: 'pointer' }}>
          <BellRing size={13} strokeWidth={1.75} color="var(--ink-3)" />
          <span style={{ flex: 1, fontSize: 11, color: 'var(--ink-2)' }}>Messages privés du bot : mentions, tâches et retakes tout de suite ; publishs suivis et calendrier regroupés.</span>
          <input type="checkbox" checked={on} disabled={busy}
            onChange={e => void save({ channel: e.target.checked ? 'discord' : 'none' }, e.target.checked ? 'Notifications Discord activées' : 'Notifications Discord coupées')} />
        </label>

        {on && project && me.project_has_bot && <DiscordLink project={project} me={me} onChange={load} />}
        {on && !me.project_has_bot && (
          <>
            <div style={row}>
              <input style={inputStyle} value={discordId} placeholder="Identifiant Discord (nombre)" disabled={busy}
                onChange={e => setDiscordId(e.target.value.replace(/\D/g, ''))} />
              <Btn sm ghost disabled={busy || discordId === me.prefs.discord_id}
                onClick={() => void save({ discord_id: discordId }, 'Identifiant Discord enregistré')}>Enregistrer</Btn>
            </div>
            <div style={hint}>
              Sans bot, la notification arrive dans le salon du webhook avec une mention. Discord : Paramètres &gt; Avancés &gt; Mode développeur,
              puis clic droit sur ton nom &gt; Copier l'identifiant.
              {!me.project_has_webhook && <> <b style={{ color: 'var(--warn)' }}>Le projet n'a pas encore de bot ni de webhook</b> (Paramètres &gt; Projet, lead ou supervisor).</>}
            </div>
          </>
        )}

        {on && (
          <div style={{ ...row, flexWrap: 'wrap', gap: 10 }}>
            <span style={{ fontSize: 11, color: 'var(--ink-2)' }}>Recevoir :</span>
            {TYPES.map(t => {
              const muted = me.prefs.muted ?? []
              const checked = !muted.includes(t.id)
              return (
                <label key={t.id} style={{ ...row, gap: 4, fontSize: 11, color: 'var(--ink-2)' }}>
                  <input type="checkbox" checked={checked} disabled={busy}
                    onChange={() => void save({ muted: checked ? [...muted, t.id] : muted.filter(m => m !== t.id) })} />
                  {t.label}
                </label>
              )
            })}
          </div>
        )}
        {on && me.project_has_bot && (
          <div style={hint}>Sous un message de tâche, de retake ou de proposition du calendrier : Valider, Refuser, Décaler, Donner à.
            Le clic est enregistré par le PC qui héberge le bot ; bot hors ligne = « l'application n'a pas répondu ».</div>
        )}

        {on && (
          <div style={row}>
            <span style={{ flex: 1, ...hint }}>{SHARED_NOTE}</span>
            <Btn sm ghost disabled={busy || !me.has_channel} onClick={() => void test()}><Send size={11} strokeWidth={1.75} /> Envoyer un test</Btn>
          </div>
        )}
      </div>
    </>
  )
}

// Discord bot (ADR 0073): the token is typed on the PC that hosts the bot and stays there,
// encrypted. ADR 0082: a lead can type it on other PCs too; one hosts, the others take over
// when it leaves (FLUX closed, PC off). Other PCs only see its name, host and status.
function BotBody({ project, bot, ro, reload }: { project: string; bot: NotifyBot; ro: boolean; reload: () => Promise<void> }) {
  const [token, setToken] = useState('')
  const [busy, setBusy] = useState(false)
  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true)
    try { await fn(); setToken(''); await reload(); toast.success(ok) } catch (e) { err(e) } finally { setBusy(false) }
  }
  const off = ro || busy
  const hereIsHost = bot.online && bot.host === bot.this_pc
  const others = (bot.candidates ?? []).filter(c => c !== bot.this_pc)
  if (!bot.configured) {
    return (
      <>
        <div style={row}>
          <input style={inputStyle} type="password" value={token} disabled={off} placeholder="Jeton du bot" aria-label="Jeton du bot"
            onChange={e => setToken(e.target.value)} autoComplete="off" />
          <Btn sm primary disabled={off || !token.trim()} onClick={() => void run(() => notifyApi.setBot(project, token), 'Bot enregistré sur ce PC')}>Héberger ici</Btn>
        </div>
        <div style={hint}>
          <a href={DEV_PORTAL} target="_blank" rel="noreferrer" style={{ color: 'var(--accent-hi)' }}>Portail développeur</a> : New Application,
          puis Bot &gt; Reset Token &gt; Copy. Le jeton reste chiffré sur ce PC.
        </div>
      </>
    )
  }
  return (
    <>
      <div style={row}>
        <Bot size={13} strokeWidth={1.75} color="var(--ink-3)" />
        <span style={{ flex: 1, fontSize: 11, color: 'var(--ink-2)' }}>
          {bot.name} sur {bot.host}{hereIsHost ? ' (ce PC)' : ''} :{' '}
          <b style={{ color: bot.online ? 'var(--ok)' : 'var(--warn)' }}>{bot.online ? 'en ligne' : 'hors ligne'}</b>
          {others.length > 0 && <span style={hint}> · secours : {others.join(', ')}</span>}
        </span>
        <Btn sm ghost disabled={off} onClick={() => void run(() => notifyApi.removeBot(project), 'Bot retiré du projet')}>Retirer le bot</Btn>
      </div>
      {!bot.online && <div style={{ ...hint, color: 'var(--warn)' }}>Hors ligne : les boutons des messages ne répondent pas et le webhook prend le relais. Ouvre FLUX sur un PC qui a le jeton, ou coche « En ligne même FLUX fermé » sur le PC hébergeur.</div>}
      <div style={row}>
        {bot.hosted_here
          ? <>
              <span style={{ flex: 1, ...hint }}>{hereIsHost ? 'Ce PC héberge le bot.' : 'Ce PC peut reprendre le bot.'}</span>
              <Btn sm ghost disabled={off} onClick={() => void run(() => notifyApi.removeBot(project, true), 'Ce PC n’héberge plus le bot')}>Retirer ce PC</Btn>
            </>
          : <>
              <input style={inputStyle} type="password" value={token} disabled={off} placeholder="Même jeton : ce PC devient secours"
                onChange={e => setToken(e.target.value)} autoComplete="off" />
              <Btn sm ghost disabled={off || !token.trim()} onClick={() => void run(() => notifyApi.setBot(project, token), 'Ce PC peut reprendre le bot')}>Ajouter ce PC</Btn>
            </>}
      </div>
      {bot.hosted_here && (
        <label style={{ ...hint, display: 'flex', alignItems: 'center', gap: 6 }}>
          <input type="checkbox" checked={!!bot.background} disabled={busy}
            onChange={e => { const on = e.target.checked; void run(() => notifyApi.setBotBackground(project, on), on ? 'Bot gardé en ligne quand FLUX est fermé' : 'Bot seulement quand FLUX est ouvert') }} />
          En ligne même FLUX fermé (démarre avec Windows){bot.runs_in === 'headless' && ' : en arrière-plan'}
        </label>
      )}
      {bot.invite_url && (
        <div style={row}>
          <span style={{ flex: 1, ...hint }}>Le bot doit être sur un serveur Discord commun avec les artistes pour leur écrire.</span>
          <a href={bot.invite_url} target="_blank" rel="noreferrer" className="btn sm ghost" style={{ textDecoration: 'none' }}>
            <UserPlus size={11} strokeWidth={1.75} /> Inviter le bot
          </a>
        </div>
      )}
    </>
  )
}

export function DiscordProjectSettings({ project }: { project: string }) {
  const [data, setData] = useState<NotifyProject | null>(null)
  const [webhook, setWebhook] = useState('')
  const [busy, setBusy] = useState(false)
  const [showMissing, setShowMissing] = useState(false)

  const load = (d: NotifyProject) => { setData(d); setWebhook(d.settings.discord_webhook) }
  useEffect(() => { setData(null); notifyApi.project(project).then(load).catch(err) }, [project])
  // The bot online status moves on its own (heartbeat 30 s): refresh it, not the field being typed.
  useEffect(() => {
    const t = setInterval(() => { notifyApi.project(project).then(setData).catch(() => undefined) }, 30000)
    return () => clearInterval(t)
  }, [project])

  const save = async (patch: Parameters<typeof notifyApi.setProject>[1], ok: string) => {
    setBusy(true)
    try {
      await notifyApi.setProject(project, patch)
      load(await notifyApi.project(project))
      toast.success(ok)
    } catch (e) { err(e) } finally { setBusy(false) }
  }

  if (!data) return null
  const s = data.settings
  const ro = !data.can_edit || busy
  const missing = data.without_channel.length
  return (
    <>
      <SecTitle>Notifications Discord</SecTitle>
      <div className="card" style={card}>
        {!data.can_edit && <div style={hint}>Modifiable par un lead ou un supervisor.</div>}

        <div style={{ ...hint, color: 'var(--ink-2)', fontWeight: 600 }}>Bot (messages privés avec boutons)</div>
        <BotBody project={project} bot={data.bot} ro={ro} reload={async () => load(await notifyApi.project(project))} />

        <div style={{ ...hint, color: 'var(--ink-2)', fontWeight: 600, borderTop: '1px solid var(--rule)', paddingTop: 8 }}>Webhook (relais si le bot est hors ligne)</div>
        <div style={row}>
          <input style={inputStyle} value={webhook} disabled={ro} placeholder="https://discord.com/api/webhooks/..."
            onChange={e => setWebhook(e.target.value)} />
          <Btn sm primary disabled={ro || webhook === s.discord_webhook} onClick={() => void save({ discord_webhook: webhook }, 'Webhook enregistré')}>Enregistrer</Btn>
        </div>
        <div style={hint}>Salon partagé : tout le salon lit la notification (mention de la personne), sans boutons.</div>

        <div style={{ ...row, flexWrap: 'wrap', borderTop: '1px solid var(--rule)', paddingTop: 8 }}>
          <span style={label}>Regroupement</span>
          <select value={s.digest_minutes} disabled={ro} onChange={e => void save({ digest_minutes: Number(e.target.value) }, 'Délai enregistré')} style={selectStyle}>
            {[1, 5, 10, 15, 30, 60].map(m => <option key={m} value={m}>{m} min</option>)}
          </select>
          <label style={{ ...row, fontSize: 11, color: 'var(--ink-2)' }}>
            <input type="checkbox" checked={s.include_project} disabled={ro}
              onChange={e => void save({ include_project: e.target.checked }, 'Réglage enregistré')} />
            Nom du projet
          </label>
          <label style={{ ...row, fontSize: 11, color: 'var(--ink-2)' }}>
            <input type="checkbox" checked={s.include_text} disabled={ro}
              onChange={e => void save({ include_text: e.target.checked }, 'Réglage enregistré')} />
            Message du chat et titre du calendrier
          </label>
        </div>

        <div style={{ ...row, borderTop: '1px solid var(--rule)', paddingTop: 8, cursor: missing ? 'pointer' : 'default' }}
          onClick={() => setShowMissing(v => !v)}>
          <Users size={13} strokeWidth={1.75} color={missing ? 'var(--warn)' : 'var(--ok)'} />
          <span style={{ fontSize: 11, color: 'var(--ink-3)' }}>
            {missing ? `${missing} artiste${missing > 1 ? 's' : ''} sans Discord (ne reçoivent rien)` : 'Tous les artistes reçoivent les notifications'}
          </span>
          {missing > 0 && <ChevronRight size={12} strokeWidth={1.75} color="var(--ink-4)" style={{ transform: showMissing ? 'rotate(90deg)' : 'none' }} />}
        </div>
        {showMissing && missing > 0 && (
          <div style={{ ...hint, paddingLeft: 21 }}>
            {data.without_channel.join(', ')}. Chacun active Discord dans Paramètres &gt; User (avec le bot : <b>/link</b> dans Discord).
          </div>
        )}
      </div>
    </>
  )
}
