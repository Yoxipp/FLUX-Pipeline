// WorkProfileDialog.tsx - the one place where work profiles are managed (ADR 0042, 0043).
// A profile presets the Production Show columns and the activity notifications; both stay
// editable by hand where they live (Production > Show, Activity > Notifications).
// Opened from Settings, the Launcher context menu, Show and Activity through openWorkProfile().

import { useEffect, useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { Check, RotateCcw, Share2, Trash2, UserRound, X } from 'lucide-react'
import { useWorkProfile } from '../../WorkProfileContext'
import {
  BUILTIN_PROFILES, NOTIFY_OPTIONS, PUBLISHER_SOFTS, START_PAGES, joinDepartments, splitDepartments,
  type ProfileRef, type WorkPrefs, type WorkProfile,
} from '../../lib/workProfiles'
import { DEFAULT_DEPARTMENTS } from '../../pages/Production/tracking'
import './workProfile.css'

const OPEN_EVENT = 'flux:open-work-profile'

export function openWorkProfile() {
  window.dispatchEvent(new Event(OPEN_EVENT))
}

const PREF_LABELS: Record<keyof WorkPrefs, string> = {
  startPage: 'Page de démarrage',
  launcher: 'Launcher',
  publisherSoft: 'Logiciel du Publisher',
  productionDepartments: 'Production · colonnes de Show',
  notifyMention: 'Mentions',
  notifyFollowed: 'Tâches suivies',
  notifyPublish: 'Publishs du projet',
  notifyComment: 'Commentaires du projet',
  notifyError: 'Erreurs',
}

const DEPARTMENT_GROUPS = (['shot', 'asset'] as const).map(scope => ({
  scope, label: scope === 'shot' ? 'Shots' : 'Assets',
  names: DEFAULT_DEPARTMENTS.filter(d => d.scope === scope).map(d => d.name.toUpperCase()),
}))

function DepartmentChips({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const picked = splitDepartments(value)
  const known = DEPARTMENT_GROUPS.flatMap(g => g.names)
  const extra = picked.filter(n => !known.includes(n))
  const toggle = (name: string) => onChange(joinDepartments(picked.includes(name) ? picked.filter(n => n !== name) : [...picked, name]))
  const chip = (name: string) => <button key={name} role="checkbox" aria-checked={picked.includes(name)} data-on={picked.includes(name) || undefined} onClick={() => toggle(name)}>{name.charAt(0) + name.slice(1).toLowerCase()}</button>
  return <div className="work-profile-departments">
    <div className="work-profile-seg"><button role="checkbox" aria-checked={!picked.length} data-on={!picked.length || undefined} onClick={() => onChange('')}>Toutes</button></div>
    {DEPARTMENT_GROUPS.map(g => <div key={g.scope} className="work-profile-seg"><span className="work-profile-seg-label">{g.label}</span>{g.names.map(chip)}</div>)}
    {extra.length > 0 && <div className="work-profile-seg"><span className="work-profile-seg-label">Projet</span>{extra.map(chip)}</div>}
  </div>
}

function Segmented<T extends string>({ value, options, onChange, label }: {
  value: T; options: { value: T; label: string }[]; onChange: (v: T) => void; label: string
}) {
  return <div className="work-profile-seg" role="radiogroup" aria-label={label}>
    {options.map(o => <button key={o.value} role="radio" aria-checked={value === o.value} data-on={value === o.value || undefined} onClick={() => onChange(o.value)}>{o.label}</button>)}
  </div>
}

function ProfileGroup({ title, profiles, source, active, onApply, onDelete, empty }: {
  title: string; profiles: WorkProfile[]; source: ProfileRef['source']; active: ProfileRef
  onApply: (ref: ProfileRef) => void; onDelete?: (ref: ProfileRef) => void; empty?: string
}) {
  return <div className="work-profile-group">
    <div className="cap">{title}</div>
    {profiles.length === 0 && empty && <p className="work-profile-empty">{empty}</p>}
    {profiles.map(p => {
      const on = active.source === source && active.id === p.id
      return <div key={p.id} className="work-profile-item" data-on={on || undefined}>
        <button onClick={() => onApply({ source, id: p.id })} aria-pressed={on}>{on ? <Check size={13} /> : <span style={{ width: 13 }} />}{p.name}</button>
        {onDelete && <button className="work-profile-icon" aria-label={`Supprimer ${p.name}`} title="Supprimer" onClick={() => onDelete({ source, id: p.id })}><Trash2 size={12} /></button>}
      </div>
    })}
  </div>
}

export function WorkProfileDialog() {
  const wp = useWorkProfile()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [confirmDelete, setConfirmDelete] = useState<ProfileRef | null>(null)

  useEffect(() => {
    const show = () => setOpen(true)
    window.addEventListener(OPEN_EVENT, show)
    return () => window.removeEventListener(OPEN_EVENT, show)
  }, [])
  useEffect(() => { if (open) setName(wp.active.source === 'builtin' ? '' : wp.activeProfile?.name ?? '') }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  const { prefs, setPref, modified } = wp
  const dot = (key: keyof WorkPrefs) => modified.includes(key) ? <span className="work-profile-dot" title="Différent du profil" /> : null
  const deleting = confirmDelete && (confirmDelete.source === 'project' ? wp.projectProfiles : wp.customProfiles).find(p => p.id === confirmDelete.id)

  return <Dialog.Root open={open} onOpenChange={setOpen}>
    <Dialog.Portal>
      <Dialog.Overlay className="work-profile-overlay" />
      <Dialog.Content className="work-profile-dialog" aria-describedby={undefined}>
        <div className="work-profile-heading">
          <Dialog.Title><UserRound size={15} />Profil de travail</Dialog.Title>
          <Dialog.Close aria-label="Fermer"><X size={16} /></Dialog.Close>
        </div>
        <p className="work-profile-intro">
          Un profil pré-règle votre vue Production (colonnes de Show) et vos notifications d'activité, ainsi que la page
          d'accueil, le Launcher et le Publisher. Tout reste modifiable à la main : Production &gt; Show, Activity &gt; Notifications.
          Le profil suit votre utilisateur sur tous les postes.
        </p>
        <div className="work-profile-body">
          <div className="work-profile-list">
            <ProfileGroup title="FLUX" profiles={BUILTIN_PROFILES} source="builtin" active={wp.active} onApply={wp.applyProfile} />
            <ProfileGroup title={wp.project ? `Projet ${wp.project}` : 'Projet'} profiles={wp.projectProfiles} source="project" active={wp.active}
              onApply={wp.applyProfile} onDelete={setConfirmDelete} empty="Aucun profil partagé." />
            <ProfileGroup title="Mes profils" profiles={wp.customProfiles} source="user" active={wp.active}
              onApply={wp.applyProfile} onDelete={setConfirmDelete} empty="Aucun profil enregistré." />
          </div>
          <div className="work-profile-prefs">
            <div className="work-profile-current">
              <span>{wp.activeProfile?.name ?? 'Profil introuvable'}</span>
              {modified.length > 0 && <><span className="work-profile-modified">modifié</span>
                <button onClick={wp.resetToProfile}><RotateCcw size={12} />Revenir au profil</button></>}
            </div>
            <label>{PREF_LABELS.startPage}{dot('startPage')}
              <select value={prefs.startPage} onChange={e => setPref('startPage', e.target.value as WorkPrefs['startPage'])}>
                {START_PAGES.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
              </select>
            </label>
            <label>{PREF_LABELS.publisherSoft}{dot('publisherSoft')}
              <select value={prefs.publisherSoft} onChange={e => setPref('publisherSoft', e.target.value)}>
                <option value="">Par défaut (Maya)</option>
                {PUBLISHER_SOFTS.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </label>
            <div className="work-profile-field">{PREF_LABELS.launcher}{dot('launcher')}
              <Segmented label={PREF_LABELS.launcher} value={prefs.launcher} onChange={v => setPref('launcher', v)}
                options={[{ value: 'compact', label: 'Compact' }, { value: 'full', label: 'Tous les boutons' }]} />
              <small>Compact : lancer reste visible, les autres actions apparaissent au survol et au clic droit.</small>
            </div>
            <div className="work-profile-field">{PREF_LABELS.productionDepartments}{dot('productionDepartments')}
              <DepartmentChips value={prefs.productionDepartments} onChange={v => setPref('productionDepartments', v)} />
              <small>Un mode sans département coché affiche toutes ses colonnes.</small>
            </div>
            <div className="work-profile-field">Notifications d'activité
              {NOTIFY_OPTIONS.map(o => <label key={o.key} className="work-profile-check" title={o.hint}>
                <input type="checkbox" checked={prefs[o.key]} onChange={e => setPref(o.key, e.target.checked)} />
                {o.label}<small>{o.hint}</small>{dot(o.key)}
              </label>)}
            </div>
          </div>
        </div>
        <div className="work-profile-save">
          <input aria-label="Nom du profil" placeholder="Nom du profil…" value={name} maxLength={40} onChange={e => setName(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && name.trim()) wp.saveAsUser(name) }} />
          <button disabled={!name.trim()} onClick={() => wp.saveAsUser(name)}>Enregistrer dans mes profils</button>
          <button disabled={!name.trim() || !wp.project} title={wp.project ? `Visible par tous les artistes de ${wp.project}` : 'Aucun projet actif'}
            onClick={() => void wp.shareToProject(name)}><Share2 size={12} />Partager au projet</button>
        </div>
      </Dialog.Content>
    </Dialog.Portal>
    <Dialog.Root open={!!deleting} onOpenChange={o => { if (!o) setConfirmDelete(null) }}>
      <Dialog.Portal>
        <Dialog.Overlay className="work-profile-overlay" />
        <Dialog.Content className="work-profile-dialog work-profile-confirm">
          <Dialog.Title>Supprimer le profil ?</Dialog.Title>
          <Dialog.Description>
            {deleting?.name}{confirmDelete?.source === 'project' ? ` sera retiré pour tous les artistes de ${wp.project}.` : ' sera retiré de vos profils.'} Votre configuration en cours est conservée.
          </Dialog.Description>
          <div className="work-profile-actions">
            <Dialog.Close>Annuler</Dialog.Close>
            <button onClick={() => { if (confirmDelete) void wp.deleteProfile(confirmDelete); setConfirmDelete(null) }}>Supprimer</button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  </Dialog.Root>
}
