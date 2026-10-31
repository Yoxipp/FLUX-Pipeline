// WelcomeDialog.tsx - first run of an artist on a project: name, work profile, Discord link.
// Shown once per project and artist (User.json "welcome.projects", follows the artist on every PC),
// for a new account as for an existing one opening a project for the first time. Closing it counts
// as seen; Paramètres > User > Revoir l'accueil opens it again (openWelcome()).

import { useEffect, useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { Check, X } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '../../api/client'
import { notifyApi, type NotifyMe } from '../../api/notify'
import { useProject } from '../../ProjectContext'
import { useWorkProfile } from '../../WorkProfileContext'
import { BUILTIN_PROFILES, type ProfileRef, type WorkProfile } from '../../lib/workProfiles'
import { DiscordLink } from '../../pages/settings/DiscordLink'
import './workProfile.css'

const OPEN_EVENT = 'flux:open-welcome'
type StepKey = 'name' | 'profile' | 'discord'

export function openWelcome() {
  window.dispatchEvent(new Event(OPEN_EVENT))
}

/** Projects where the artist has already seen the welcome dialog. */
export function seenProjects(userData: Record<string, unknown>): string[] {
  const w = userData.welcome as { projects?: unknown } | undefined
  return Array.isArray(w?.projects) ? w.projects.filter((p): p is string => typeof p === 'string') : []
}

const field = { display: 'flex', flexDirection: 'column', gap: 4, flex: 1, minWidth: 0, color: 'var(--ink-3)', fontSize: 11 } as const

function ProfileChips({ title, profiles, source, active, onApply }: {
  title?: string; profiles: WorkProfile[]; source: ProfileRef['source']; active: ProfileRef; onApply: (ref: ProfileRef) => void
}) {
  if (!profiles.length) return null
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {title && <div className="cap">{title}</div>}
      <div className="work-profile-seg">
        {profiles.map(p => {
          const on = active.source === source && active.id === p.id
          return <button key={p.id} role="radio" aria-checked={on} data-on={on || undefined} onClick={() => onApply({ source, id: p.id })}>{p.name}</button>
        })}
      </div>
    </div>
  )
}

export function WelcomeDialog() {
  const { project } = useProject()
  const wp = useWorkProfile()
  const [open, setOpen] = useState(false)
  const [seen, setSeen] = useState<string[]>([])
  const [me, setMe] = useState<NotifyMe | null>(null)
  const [step, setStep] = useState(0)
  const [first, setFirst] = useState('')
  const [last, setLast] = useState('')
  const [saved, setSaved] = useState({ first: '', last: '' })
  const [busy, setBusy] = useState(false)

  const prepare = async (force: boolean) => {
    if (!project) return
    const [data, profile, notify] = await Promise.all([
      api.getUserData(), api.getOwnProfile(), notifyApi.me(project).catch(() => null),
    ])
    const already = seenProjects(data)
    setSeen(already)
    if (!force && already.includes(project)) return
    setFirst(profile.first_name); setLast(profile.last_name); setSaved({ first: profile.first_name, last: profile.last_name })
    setMe(notify); setStep(0); setOpen(true)
  }

  useEffect(() => { setOpen(false); void prepare(false).catch(() => { /* backend down: ask next time */ }) }, [project]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const show = () => { void prepare(true).catch(e => toast.error(e instanceof Error ? e.message : String(e))) }
    window.addEventListener(OPEN_EVENT, show)
    return () => window.removeEventListener(OPEN_EVENT, show)
  }, [project]) // eslint-disable-line react-hooks/exhaustive-deps

  const steps: StepKey[] = me?.project_has_bot ? ['name', 'profile', 'discord'] : ['name', 'profile']
  const key = steps[Math.min(step, steps.length - 1)]
  const isLast = step >= steps.length - 1

  const close = () => {
    setOpen(false)
    if (!project || seen.includes(project)) return
    const next = [...seen, project]
    setSeen(next)
    void api.setUserData({ welcome: { projects: next } }).catch(() => { /* shown again next time */ })
  }
  const next = async () => {
    if (key === 'name' && (first.trim() !== saved.first || last.trim() !== saved.last)) {
      setBusy(true)
      try {
        const p = await api.setOwnProfile(first.trim(), last.trim())
        setSaved({ first: p.first_name, last: p.last_name })
      } catch (e) { toast.error(e instanceof Error ? e.message : String(e)); setBusy(false); return }
      setBusy(false)
    }
    if (isLast) close()
    else setStep(step + 1)
  }

  return (
    <Dialog.Root open={open} onOpenChange={o => { if (!o) close() }}>
      <Dialog.Portal>
        <Dialog.Overlay className="work-profile-overlay" />
        <Dialog.Content className="work-profile-dialog" style={{ width: 'min(460px, calc(100vw - 32px))' }} aria-describedby={undefined}
          onInteractOutside={e => e.preventDefault()}>
          <div className="work-profile-heading">
            <Dialog.Title>Bienvenue sur {project}</Dialog.Title>
            <Dialog.Close aria-label="Fermer"><X size={16} /></Dialog.Close>
          </div>

          <div style={{ display: 'flex', gap: 6, margin: '12px 0 16px' }} aria-label={`Étape ${step + 1} sur ${steps.length}`}>
            {steps.map((s, i) => (
              <span key={s} style={{ flex: 1, height: 3, borderRadius: 2, background: i <= step ? 'var(--accent)' : 'var(--rule-2)' }} />
            ))}
          </div>

          {key === 'name' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div style={{ fontWeight: 600 }}>Ton nom</div>
              <div style={{ display: 'flex', gap: 8 }}>
                <label style={field}>Prénom<input autoFocus value={first} onChange={e => setFirst(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && first.trim()) void next() }} /></label>
                <label style={field}>Nom<input value={last} onChange={e => setLast(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && first.trim()) void next() }} /></label>
              </div>
              <div style={{ fontSize: 11, color: 'var(--ink-4)' }}>Visible par l'équipe (Team, Production, chat).</div>
            </div>
          )}

          {key === 'profile' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div style={{ fontWeight: 600 }}>Ton profil de travail</div>
              <div style={{ fontSize: 11, color: 'var(--ink-4)' }}>Règle ta page d'accueil, tes colonnes et tes notifications. Généraliste si tu touches à tout.</div>
              <ProfileChips profiles={BUILTIN_PROFILES} source="builtin" active={wp.active} onApply={wp.applyProfile} />
              <ProfileChips title={`Projet ${project}`} profiles={wp.projectProfiles} source="project" active={wp.active} onApply={wp.applyProfile} />
              <div style={{ fontSize: 11, color: 'var(--ink-4)' }}>Modifiable à tout moment : Paramètres &gt; User &gt; Profil de travail.</div>
            </div>
          )}

          {key === 'discord' && me && project && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div style={{ fontWeight: 600 }}>Lier ton Discord</div>
              <div style={{ fontSize: 11, color: 'var(--ink-4)' }}>Pour recevoir tes mentions et tâches en message privé du bot.</div>
              <DiscordLink project={project} me={me} onChange={setMe} />
            </div>
          )}

          <div className="work-profile-actions" style={{ marginTop: 20 }}>
            {step > 0 && <button onClick={() => setStep(step - 1)}>Retour</button>}
            <span style={{ flex: 1 }} />
            {key === 'discord' && !me?.discord_linked && <button onClick={close}>Plus tard</button>}
            <button disabled={busy || (key === 'name' && !first.trim())} onClick={() => void next()}
              style={{ background: 'var(--accent)', borderColor: 'var(--accent)', color: 'var(--on-accent)', fontWeight: 600 }}>
              {isLast ? <><Check size={13} /> Terminer</> : 'Suivant'}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
