// SettingsPage.tsx - /settings, three scopes never mixed (retake 06, ADR 0046):
//   User    : the artist and this machine (UserSettings).
//   Projet  : the active project, shared by every artist (scope said before editing),
//             plus the pipe artists (create / rename / delete, moved from Avance and
//             from the TitleBar profile popover).
//   Avance  : risky settings behind "Understand" (N8): project technique + publish
//             switches, Disque, Editeur de Template (moved from the Pipeline sidebar),
//             uninstall.
//   Doc     : the FLUX manual (FLUX_DOC, ADR 0049), embedded.
// Deep links: ?tab=user|project|advanced|doc&sub=settings|disk|templates. The old routes
// /advanced, /disk and /templates redirect here (App.tsx).

import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ClipboardList, Check, KeyRound, Lock, Pencil, Trash2, UserPlus, Users, X } from 'lucide-react'
import { toast } from 'sonner'
import { api, type UserProfile } from '../../api/client'
import { EMPTY_NEW_ARTIST, NewArtistFields, newArtistError, newArtistPayload, type NewArtistValue } from '../FirstLaunch'
import { Btn, SecTitle } from '../../components/shared/ui'
import { ExpandPicker } from '../../components/shared/ExpandPicker'
import { openWorkProfile } from '../../components/shared/WorkProfileDialog'
import { useSettings } from '../../hooks/useSettings'
import { readSession, writeSession } from '../../hooks/useSessionState'
import { useProject } from '../../ProjectContext'
import { AdvancedSettings } from '../AdvancedSettings'
import { DiskUsage } from '../DiskUsage'
import { TemplateEditor } from '../TemplateEditor'
import { DocTab } from './DocTab'
import { AdvancedConfirm, UninstallConfirm } from './SettingsDialogs'
import { UserSettings } from './UserSettings'
import { ProjectRoles } from './ProjectRoles'
import { NotifyProjectSettings } from './NotifySettings'

type Tab = 'user' | 'project' | 'advanced' | 'doc'
type Sub = 'settings' | 'disk' | 'templates'
const TABS: { key: Tab; label: string; hint: string }[] = [
  { key: 'user',     label: 'User',   hint: 'Toi et ce poste' },
  { key: 'project',  label: 'Projet', hint: 'Le projet actif, pour tous ses artistes' },
  { key: 'advanced', label: 'Avancé', hint: 'Réglages à risque (confirmation)' },
  { key: 'doc',      label: 'Doc',    hint: 'Manuels de FLUX et des Flows' },
]
const SUBS: { key: Sub; label: string }[] = [
  { key: 'settings', label: 'Réglages' }, { key: 'disk', label: 'Disque' }, { key: 'templates', label: 'Editeur de Template' },
]
const UNLOCK_KEY = 'settings.advancedUnlocked'

export function SettingsPage() {
  const [params, setParams] = useSearchParams()
  const { settings } = useSettings()
  const tab = (TABS.some(t => t.key === params.get('tab')) ? params.get('tab') : 'user') as Tab
  const sub = (SUBS.some(s => s.key === params.get('sub')) ? params.get('sub') : 'settings') as Sub
  const [unlocked, setUnlocked] = useState(() => readSession<boolean>(UNLOCK_KEY) === true)
  const [asking, setAsking] = useState(false)
  // Avance (or a deep link to it) asks once per session.
  useEffect(() => { if (tab === 'advanced' && !unlocked) setAsking(true) }, [tab, unlocked])

  const go = (next: Tab, nextSub?: Sub) => setParams(nextSub ? { tab: next, sub: nextSub } : { tab: next }, { replace: true })

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <div className="page-toolbar" style={{ gap: 6 }}>
        {TABS.map(t => (
          <Btn key={t.key} sm primary={tab === t.key} ghost={tab !== t.key} title={t.hint} onClick={() => go(t.key)}>{t.label}</Btn>
        ))}
        {tab === 'advanced' && unlocked && <>
          <div style={{ width: 1, height: 18, background: 'var(--rule-2)', margin: '0 6px' }} />
          <ExpandPicker title="Section" value={sub} options={SUBS.map(s => ({ value: s.key, label: s.label }))} onChange={v => go('advanced', v as Sub)} />
        </>}
      </div>

      {tab === 'doc' ? (
        <DocTab />
      ) : tab === 'advanced' && unlocked && sub !== 'settings' ? (
        // Disk and Template Editor keep their own full-page layout.
        <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
          {sub === 'disk' ? <DiskUsage /> : <TemplateEditor />}
        </div>
      ) : (
        <div style={{ flex: 1, overflowY: 'auto', padding: '16px 24px 24px' }}>
          {tab === 'user' && <UserSettings username={settings?.username ?? 'USER'} />}
          {tab === 'project' && <ProjectTab currentUser={settings?.username ?? ''} />}
          {tab === 'advanced' && unlocked && <AdvancedTab />}
          {tab === 'advanced' && !unlocked && !asking && (
            <div style={{ fontSize: 11, color: 'var(--ink-3)' }}>
              Réglages avancés verrouillés. <Btn sm ghost onClick={() => setAsking(true)}>Déverrouiller</Btn>
            </div>
          )}
        </div>
      )}

      {asking && createPortal(
        <AdvancedConfirm
          onCancel={() => { setAsking(false); if (!unlocked) go('user') }}
          onConfirm={() => { writeSession(UNLOCK_KEY, true); setUnlocked(true); setAsking(false) }}
        />, document.body)}
    </div>
  )
}

function ProjectTab({ currentUser }: { currentUser: string }) {
  const { project } = useProject()
  const navigate = useNavigate()
  if (!project) return <div style={{ fontSize: 11, color: 'var(--ink-4)' }}>Aucun projet actif : choisis-en un pour voir ses réglages.</div>
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 760 }}>
      <div className="card" style={{ padding: '8px 12px', fontSize: 11, color: 'var(--ink-2)', lineHeight: 1.5, borderColor: 'var(--rule-3)' }}>
        Portée : projet <b>{project}</b>. Une modification ici s'applique à tous les artistes du projet.
      </div>
      <AdvancedSettings part="project" />
      <SecTitle>Profils de travail partagés</SecTitle>
      <div className="card" style={{ padding: '10px 12px', display: 'flex', alignItems: 'center', gap: 10 }}>
        <Users size={14} strokeWidth={1.75} color="var(--ink-3)" />
        <span style={{ flex: 1, fontSize: 11, color: 'var(--ink-2)' }}>Profils de rôle proposés à tout le projet (enregistrer, partager).</span>
        <Btn sm ghost onClick={openWorkProfile}>Ouvrir</Btn>
      </div>
      <SecTitle>Départements et statuts</SecTitle>
      <div className="card" style={{ padding: '10px 12px', display: 'flex', alignItems: 'center', gap: 10 }}>
        <ClipboardList size={14} strokeWidth={1.75} color="var(--ink-3)" />
        <span style={{ flex: 1, fontSize: 11, color: 'var(--ink-2)' }}>Colonnes, statuts et dépendances du suivi : Production &gt; Settings.</span>
        <Btn sm ghost onClick={() => navigate('/production')}>Production</Btn>
      </div>
      <ProjectRoles project={project} />
      <NotifyProjectSettings project={project} />
      <SecTitle>Artistes du pipe</SecTitle>
      <NewArtist />
      <OtherUsers currentUser={currentUser} />
      <div style={{ fontSize: 11.5, color: 'var(--ink-4)' }}>Unités USD, OCIO, variables d'env et stockage des versions : onglet Avancé.</div>
    </div>
  )
}

function AdvancedTab() {
  const [uninstall, setUninstall] = useState(false)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 760 }}>
      <AdvancedSettings part="advanced" />
      <SecTitle>Désinstaller</SecTitle>
      <div><Btn sm ghost onClick={() => setUninstall(true)} style={{ color: 'var(--err)' }}><Trash2 size={11} /> Désinstaller FLUX</Btn></div>
      {uninstall && createPortal(<UninstallConfirm onCancel={() => setUninstall(false)} />, document.body)}
    </div>
  )
}

// Create an artist from first + last name (identifier computed by the backend, optional
// password), switch to it and reload.
function NewArtist() {
  const [value, setValue] = useState<NewArtistValue>(EMPTY_NEW_ARTIST)
  const [busy, setBusy] = useState(false)
  const create = async () => {
    const err = newArtistError(value)
    if (err) { toast.error(err); return }
    setBusy(true)
    try { await api.createUser({ ...newArtistPayload(value), switch: true }); window.location.reload() }
    catch (e) { toast.error(e instanceof Error ? e.message : String(e)); setBusy(false) }
  }
  const ready = !!value.first.trim() && !!value.last.trim()
  return (
    <div className="card" style={{ padding: '8px 12px', display: 'flex', alignItems: 'flex-start', gap: 8 }}>
      <UserPlus size={14} strokeWidth={1.75} color="var(--ink-3)" style={{ marginTop: 6 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <NewArtistFields compact value={value} onChange={setValue} onSubmit={() => void create()} />
      </div>
      <Btn sm ghost disabled={busy || !ready} title="Crée l'artiste et bascule dessus" onClick={() => void create()}>Créer et basculer</Btn>
    </div>
  )
}

// First / last name of an artist being renamed, with the identifier it would get (server
// side: initials of the last name, ADR 0079; no last name = the first name alone).
function RenameFields({ user, first, last, onChange, onSubmit, onCancel }: {
  user: string; first: string; last: string
  onChange: (first: string, last: string) => void; onSubmit: () => void; onCancel: () => void
}) {
  const [preview, setPreview] = useState<string | null>(null)
  useEffect(() => {
    if (!first.trim()) { setPreview(null); return }
    let alive = true
    const t = setTimeout(() => {
      api.previewRename(user, first.trim(), last.trim())
        .then(r => { if (alive) setPreview(r.id) })
        .catch(() => { if (alive) setPreview(null) })
    }, 300)
    return () => { alive = false; clearTimeout(t) }
  }, [user, first, last])
  const input: React.CSSProperties = {
    flex: 1, minWidth: 0, height: 24, padding: '0 6px', fontSize: 11, background: 'var(--paper-2)',
    color: 'var(--ink)', border: '1px solid var(--rule-3)', borderRadius: 5,
  }
  const key = (e: React.KeyboardEvent) => { if (e.key === 'Enter') onSubmit(); if (e.key === 'Escape') onCancel() }
  return (
    <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 4 }}>
      <div style={{ display: 'flex', gap: 6 }}>
        <input autoFocus value={first} placeholder="Prénom" onChange={e => onChange(e.target.value, last)} onKeyDown={key} style={input} />
        <input value={last} placeholder="Nom (facultatif)" onChange={e => onChange(first, e.target.value)} onKeyDown={key} style={input} />
      </div>
      <span style={{ fontSize: 10.5, color: 'var(--ink-3)', fontFamily: 'var(--mono)' }}>
        {preview ? `${user} → ${preview}${preview === user ? ' (identifiant inchangé)' : ''}` : 'Identifiant : (prénom requis)'}
      </span>
    </div>
  )
}

// Rename / delete OTHER artists (old accounts). One's own user is in the User tab.
// Rename = first / last name for a lead or supervisor; delete = supervisor.
function OtherUsers({ currentUser }: { currentUser: string }) {
  const { project } = useProject()
  const [profiles, setProfiles] = useState<UserProfile[]>([])
  const [renaming, setRenaming] = useState<string | null>(null)
  const [names, setNames] = useState({ first: '', last: '' })
  const [confirm, setConfirm] = useState<string | null>(null)
  const [confirmReset, setConfirmReset] = useState<string | null>(null)
  const refresh = () => api.listUserProfiles()
    .then(d => setProfiles(d.profiles.filter(p => p.id.toUpperCase() !== currentUser.toUpperCase())))
    .catch(() => setProfiles([]))
  useEffect(() => { void refresh() }, [currentUser])   // eslint-disable-line react-hooks/exhaustive-deps
  const run = async (call: () => Promise<{ message: string }>) => {
    try { toast.success((await call()).message); setRenaming(null); setConfirm(null); setConfirmReset(null); await refresh() }
    catch (e) { toast.error(e instanceof Error ? e.message : String(e)) }   // 403 messages explain the needed role
  }
  const proj = project || undefined
  if (!profiles.length) return <div style={{ fontSize: 11, color: 'var(--ink-4)' }}>Aucun autre utilisateur.</div>
  return (
    <div className="card" style={{ padding: '4px 12px' }}>
      {profiles.map(p => { const u = p.id; const full = `${p.first_name} ${p.last_name}`.trim(); return (
        <div key={u}style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '5px 0', borderBottom: '1px solid var(--rule)' }}>
          {renaming === u
            ? <RenameFields user={u} first={names.first} last={names.last} onChange={(first, last) => setNames({ first, last })}
                onSubmit={() => void run(() => api.renameUserByName(u, names.first.trim(), names.last.trim(), proj))}
                onCancel={() => setRenaming(null)} />
            : <span style={{ flex: 1, fontSize: 11, color: 'var(--ink-2)', display: 'flex', alignItems: 'center', gap: 6 }}>
                {full ? `${full} (${u})` : u}
                {p.has_password && <Lock size={10} strokeWidth={1.75} color="var(--ink-4)" />}
              </span>}
          {renaming === u ? <>
            <Btn sm ghost title="Valider" disabled={!names.first.trim()}
              onClick={() => void run(() => api.renameUserByName(u, names.first.trim(), names.last.trim(), proj))}><Check size={11} /></Btn>
            <Btn sm ghost title="Annuler" onClick={() => setRenaming(null)}><X size={11} /></Btn>
          </> : confirm === u ? <>
            <span style={{ fontSize: 11, color: 'var(--err)' }}>Supprimer {u} et ses données ?</span>
            <Btn sm ghost title="Confirmer" onClick={() => void run(() => api.deleteUser(u, proj))} style={{ color: 'var(--err)' }}><Check size={11} /></Btn>
            <Btn sm ghost title="Annuler" onClick={() => setConfirm(null)}><X size={11} /></Btn>
          </> : confirmReset === u ? <>
            <span style={{ fontSize: 11, color: 'var(--err)' }}>Réinitialiser le mot de passe de {u} ?</span>
            <Btn sm ghost title="Confirmer"
              onClick={() => void run(async () => { await api.resetUserPassword(u, proj ?? ''); return { message: `Mot de passe de ${u} réinitialisé` } })}
              style={{ color: 'var(--err)' }}><Check size={11} /></Btn>
            <Btn sm ghost title="Annuler" onClick={() => setConfirmReset(null)}><X size={11} /></Btn>
          </> : <>
            {p.has_password && <Btn sm ghost title="Réinitialiser le mot de passe" onClick={() => { setConfirmReset(u); setRenaming(null); setConfirm(null) }}><KeyRound size={11} /></Btn>}
            <Btn sm ghost title="Renommer (prénom et nom)" onClick={() => {
              setRenaming(u); setConfirm(null); setConfirmReset(null)
              // Artists without a profile: their identifier is their first name.
              setNames({ first: p.first_name || u.charAt(0) + u.slice(1).toLowerCase(), last: p.last_name })
            }}><Pencil size={11} /></Btn>
            <Btn sm ghost title="Supprimer" onClick={() => { setConfirm(u); setRenaming(null); setConfirmReset(null) }}><Trash2 size={11} /></Btn>
          </>}
        </div>
      )})}
    </div>
  )
}
