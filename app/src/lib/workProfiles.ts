// workProfiles.ts - artist work profiles (ADR 0042). Pure module, no React, no API.
//
// Three scopes, never mixed:
//   * global preference (machine, config.json): workspace, DCC paths, accent, language.
//     Not part of a profile, edited in Settings.
//   * user preference (USER/<user>/UserSettings/User.json "work_profile"): the working
//     prefs in use + the user's own saved profiles. Follows the artist on any machine.
//   * project preset (<project>/project.json "ui.work_profiles"): role profiles shared
//     with every artist of the project, read-only until someone saves over them.
// A profile is only a snapshot of WorkPrefs. Applying it copies its prefs into the
// working prefs; later tweaks in the pages change the working prefs and show "modified".
// ADR 0043: a profile presets the Production "Show" departments and the activity
// notifications; both stay editable by hand (Show menu, Activity > Notifications).
// A profile also narrows the software shown, inside what Settings > Logiciels enables.
// Folder Manager layout is NOT part of a profile (page preference, per browser).
// Values stay scalar (project.json only keeps str/bool/number): department lists are
// comma separated upper-case names, '' = every department.

export type StartPage = '/' | '/production?mode=shot' | '/production?mode=asset' | '/publisher' | '/projects' | '/usd' | '/calendar'
export type LauncherMode = 'compact' | 'full'

export interface WorkPrefs {
  startPage: StartPage
  launcher: LauncherMode
  /** Publisher software opened first ('' = Maya, the historical default). */
  publisherSoft: string
  /** Production columns shown, upper-case department names, comma separated ('' = all). */
  productionDepartments: string
  /** Software shown (launcher, status bar, Publisher, Shelf), DCC keys comma separated ('' = all).
   *  Always narrowed by Settings > Logiciels, never widened. */
  softwares: string
  /** Activity notifications (toast + system notification). */
  notifyMention: boolean
  /** Events on followed (favorite) tasks. */
  notifyFollowed: boolean
  /** Any publish / comment / error of another artist in the active project. */
  notifyPublish: boolean
  notifyComment: boolean
  notifyError: boolean
}

export type NotifyKey = 'notifyMention' | 'notifyFollowed' | 'notifyPublish' | 'notifyComment' | 'notifyError'

export const NOTIFY_OPTIONS: { key: NotifyKey; label: string; hint: string }[] = [
  { key: 'notifyMention', label: 'Mentions', hint: 'Quand un artiste vous mentionne dans le chat' },
  { key: 'notifyFollowed', label: 'Tâches suivies', hint: 'Publish ou commentaire sur une tâche en favori' },
  { key: 'notifyPublish', label: 'Publishs du projet', hint: 'Chaque publish d\'un autre artiste du projet actif' },
  { key: 'notifyComment', label: 'Commentaires du projet', hint: 'Chaque commentaire d\'un autre artiste du projet actif' },
  { key: 'notifyError', label: 'Erreurs', hint: 'Échecs de publish ou d\'export du projet actif' },
]

export type ProfileSource = 'builtin' | 'project' | 'user'

export interface WorkProfile {
  id: string
  name: string
  prefs: Partial<WorkPrefs>
}

export interface ProfileRef { source: ProfileSource; id: string }

export interface UserWorkProfile {
  active: ProfileRef
  prefs: WorkPrefs
  custom: WorkProfile[]
}

export const START_PAGES: { value: StartPage; label: string }[] = [
  { value: '/', label: 'Accueil' },
  { value: '/production?mode=shot', label: 'Production · Shots' },
  { value: '/production?mode=asset', label: 'Production · Assets' },
  { value: '/publisher', label: 'Publisher' },
  { value: '/projects', label: 'Folder Manager' },
  { value: '/usd', label: 'USD' },
  { value: '/calendar', label: 'Calendar' },
]

export const PUBLISHER_SOFTS = ['Maya', 'Houdini', 'Nuke', 'Marvelous', 'Painter', 'Designer', 'Mari', 'ZBrush', 'Photoshop', 'Fichier local']

export const DEFAULT_PREFS: WorkPrefs = {
  startPage: '/',
  launcher: 'compact',
  publisherSoft: '',
  productionDepartments: '',
  softwares: '',
  notifyMention: true,
  notifyFollowed: true,
  notifyPublish: false,
  notifyComment: false,
  notifyError: false,
}

// Department names match the default Production departments (tracking.ts); a project
// with other names simply shows every column until the artist ticks its own.
export const BUILTIN_PROFILES: WorkProfile[] = [
  { id: 'generalist', name: 'Généraliste', prefs: {} },
  { id: 'modeling', name: 'Modeling', prefs: { startPage: '/production?mode=asset', publisherSoft: 'Maya', productionDepartments: 'MODELING' } },
  { id: 'rigging', name: 'Rigging', prefs: { startPage: '/production?mode=asset', publisherSoft: 'Maya', productionDepartments: 'MODELING,RIGGING' } },
  { id: 'texturing', name: 'Texturing / Lookdev', prefs: { startPage: '/production?mode=asset', publisherSoft: 'Painter', productionDepartments: 'MODELING,LOOK,GROOM' } },
  { id: 'animation', name: 'Animation', prefs: { startPage: '/production?mode=shot', publisherSoft: 'Maya', productionDepartments: 'LAYOUT,ANIMATION,RIGGING' } },
  { id: 'fx_lighting', name: 'FX / Lighting', prefs: { startPage: '/production?mode=shot', publisherSoft: 'Houdini', productionDepartments: 'ANIMATION,FX,LIGHTING,RENDERING,LOOK' } },
  { id: 'compositing', name: 'Compositing', prefs: { startPage: '/production?mode=shot', publisherSoft: 'Nuke', productionDepartments: 'LIGHTING,RENDERING,COMPOSITING' } },
  { id: 'production', name: 'Production', prefs: { startPage: '/production?mode=shot', notifyPublish: true, notifyComment: true, notifyError: true } },
  { id: 'td', name: 'TD / Avancé', prefs: { launcher: 'full', notifyError: true } },
]

export const DEFAULT_REF: ProfileRef = { source: 'builtin', id: 'generalist' }

const START_VALUES = new Set<string>(START_PAGES.map(p => p.value))

/** Keep only known keys with valid values. Unknown or corrupt values are dropped. */
export function sanitizePrefs(raw: unknown): Partial<WorkPrefs> {
  if (!raw || typeof raw !== 'object') return {}
  const r = raw as Record<string, unknown>
  const out: Partial<WorkPrefs> = {}
  if (typeof r.startPage === 'string' && START_VALUES.has(r.startPage)) out.startPage = r.startPage as StartPage
  if (r.launcher === 'compact' || r.launcher === 'full') out.launcher = r.launcher
  if (typeof r.publisherSoft === 'string' && (r.publisherSoft === '' || PUBLISHER_SOFTS.includes(r.publisherSoft))) out.publisherSoft = r.publisherSoft
  if (typeof r.productionDepartments === 'string') out.productionDepartments = joinDepartments(splitDepartments(r.productionDepartments))
  if (typeof r.softwares === 'string') out.softwares = joinSoftwares(splitSoftwares(r.softwares))
  for (const { key } of NOTIFY_OPTIONS) if (typeof r[key] === 'boolean') out[key] = r[key] as boolean
  return out
}

export function resolvePrefs(...layers: (Partial<WorkPrefs> | undefined)[]): WorkPrefs {
  return Object.assign({}, DEFAULT_PREFS, ...layers.map(sanitizePrefs))
}

export function sanitizeProfiles(raw: unknown): WorkProfile[] {
  if (!Array.isArray(raw)) return []
  const seen = new Set<string>()
  const out: WorkProfile[] = []
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue
    const p = item as Record<string, unknown>
    const id = typeof p.id === 'string' ? p.id.trim() : ''
    const name = typeof p.name === 'string' ? p.name.trim().slice(0, 40) : ''
    if (!id || !name || seen.has(id)) continue
    seen.add(id)
    out.push({ id, name, prefs: sanitizePrefs(p.prefs) })
  }
  return out
}

function sanitizeRef(raw: unknown): ProfileRef | null {
  if (!raw || typeof raw !== 'object') return null
  const r = raw as Record<string, unknown>
  if ((r.source === 'builtin' || r.source === 'project' || r.source === 'user') && typeof r.id === 'string' && r.id) return { source: r.source, id: r.id }
  return null
}

/** Reads User.json "work_profile"; unknown keys (old Folder Manager prefs) are dropped. */
export function readUserWorkProfile(raw: unknown): UserWorkProfile {
  const r = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {}
  return {
    active: sanitizeRef(r.active) ?? DEFAULT_REF,
    prefs: resolvePrefs(r.prefs as Partial<WorkPrefs> | undefined),
    custom: sanitizeProfiles(r.custom),
  }
}

export function findProfile(ref: ProfileRef, project: WorkProfile[], custom: WorkProfile[]): WorkProfile | null {
  const list = ref.source === 'builtin' ? BUILTIN_PROFILES : ref.source === 'project' ? project : custom
  return list.find(p => p.id === ref.id) ?? null
}

export function profilePrefs(profile: WorkProfile | null): WorkPrefs {
  return resolvePrefs(profile?.prefs)
}

/** Keys where the working prefs differ from the active profile. */
export function modifiedKeys(prefs: WorkPrefs, profile: WorkProfile | null): (keyof WorkPrefs)[] {
  const base = profilePrefs(profile)
  return (Object.keys(DEFAULT_PREFS) as (keyof WorkPrefs)[]).filter(k => prefs[k] !== base[k])
}

/** Stable id from a display name, unique among `taken`. */
export function profileId(name: string, taken: string[]): string {
  const base = name.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '') || 'profil'
  let id = base, n = 2
  while (taken.includes(id)) id = `${base}_${n++}`
  return id
}

/** Saves `prefs` as a profile named `name`, replacing a profile of the same name. */
export function upsertProfile(list: WorkProfile[], name: string, prefs: WorkPrefs): { list: WorkProfile[]; id: string } {
  const clean = name.trim().slice(0, 40)
  const existing = list.find(p => p.name.toLowerCase() === clean.toLowerCase())
  const id = existing?.id ?? profileId(clean, list.map(p => p.id))
  const profile = { id, name: clean, prefs: { ...prefs } }
  return { id, list: existing ? list.map(p => p.id === id ? profile : p) : [...list, profile] }
}

// ── Production "Show" departments ──────────────────────────────────────────────

export function splitDepartments(value: string): string[] {
  return Array.from(new Set(value.split(',').map(x => x.trim().toUpperCase()).filter(Boolean)))
}

export function joinDepartments(names: string[]): string {
  return Array.from(new Set(names.map(x => x.trim().toUpperCase()).filter(Boolean))).join(',')
}

/**
 * Columns to show for one mode. `pref` may list departments of the other mode too; when
 * none of its names exists in this mode (or pref is empty), every column stays visible
 * so a table is never empty because of a profile.
 */
export function visibleDepartments<T extends { name: string }>(departments: T[], pref: string): T[] {
  const names = new Set(splitDepartments(pref))
  const shown = departments.filter(d => names.has(d.name.toUpperCase()))
  return shown.length ? shown : departments
}

/** Ticks / unticks one column by hand, keeping the other mode's choice and at least one column. */
export function toggleDepartment(departments: { name: string }[], pref: string, name: string): string {
  const modeNames = departments.map(d => d.name.toUpperCase())
  const other = splitDepartments(pref).filter(x => !modeNames.includes(x))
  const current = visibleDepartments(departments, pref).map(d => d.name.toUpperCase())
  const key = name.toUpperCase()
  const next = current.includes(key) ? current.filter(x => x !== key) : [...current, key]
  if (!next.length) return pref
  if (next.length === modeNames.length && !other.length) return ''
  return joinDepartments([...other, ...modeNames.filter(x => next.includes(x))])
}

/** Shows every column of this mode again, keeping the other mode's choice. */
export function showAllDepartments(departments: { name: string }[], pref: string): string {
  const modeNames = departments.map(d => d.name.toUpperCase())
  return joinDepartments(splitDepartments(pref).filter(x => !modeNames.includes(x)))
}

// ── Software shown ─────────────────────────────────────────────────────────────

export function splitSoftwares(value: string): string[] {
  return Array.from(new Set(value.split(',').map(x => x.trim().toLowerCase()).filter(Boolean)))
}

export function joinSoftwares(keys: string[]): string {
  return Array.from(new Set(keys.map(x => x.trim().toLowerCase()).filter(Boolean))).join(',')
}

/**
 * Is `key` shown? Settings > Logiciels (`isEnabled`) always wins. When the profile picks
 * nothing, or only software disabled in Settings, every enabled software stays visible so
 * the launcher is never empty because of a profile.
 */
export function isSoftwareVisible(key: string, pref: string, allKeys: string[], isEnabled: (key: string) => boolean): boolean {
  if (!isEnabled(key)) return false
  const picked = splitSoftwares(pref).filter(k => allKeys.includes(k) && isEnabled(k))
  return !picked.length || picked.includes(key.toLowerCase())
}
