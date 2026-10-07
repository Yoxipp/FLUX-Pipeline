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

export type StartPage = '/' | '/production?mode=shot' | '/production?mode=asset' | '/publisher' | '/projects' | '/usd' | '/calendar'
export type LauncherMode = 'compact' | 'full'
export type TileSize = 'sm' | 'md' | 'lg'
export type PaneLayout = 'single' | 'stacked' | 'side' | 'quad'

export interface WorkPrefs {
  startPage: StartPage
  launcher: LauncherMode
  /** Publisher software opened first ('' = Maya, the historical default). */
  publisherSoft: string
  folderTileSize: TileSize
  folderLayout: PaneLayout
  /** Folder Manager creation forms (Projet / Asset / Shot / Dossier) unfolded. */
  folderCreatePanel: boolean
}

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
  folderTileSize: 'md',
  folderLayout: 'single',
  folderCreatePanel: true,
}

export const BUILTIN_PROFILES: WorkProfile[] = [
  { id: 'generalist', name: 'Généraliste', prefs: {} },
  { id: 'modeling', name: 'Modeling', prefs: { startPage: '/publisher', publisherSoft: 'Maya', folderCreatePanel: false } },
  { id: 'texturing', name: 'Texturing / Lookdev', prefs: { startPage: '/publisher', publisherSoft: 'Painter', folderCreatePanel: false, folderTileSize: 'lg' } },
  { id: 'animation', name: 'Animation', prefs: { startPage: '/production?mode=shot', publisherSoft: 'Maya', folderCreatePanel: false } },
  { id: 'fx_lighting', name: 'FX / Lighting', prefs: { startPage: '/usd', publisherSoft: 'Houdini', folderCreatePanel: false } },
  { id: 'compositing', name: 'Compositing', prefs: { startPage: '/projects', publisherSoft: 'Nuke', folderCreatePanel: false } },
  { id: 'production', name: 'Production', prefs: { startPage: '/production?mode=shot', folderTileSize: 'sm' } },
  { id: 'td', name: 'TD / Avancé', prefs: { launcher: 'full', folderLayout: 'side' } },
]

export const DEFAULT_REF: ProfileRef = { source: 'builtin', id: 'generalist' }

const START_VALUES = new Set<string>(START_PAGES.map(p => p.value))
const TILE_VALUES = new Set<string>(['sm', 'md', 'lg'])
const LAYOUT_VALUES = new Set<string>(['single', 'stacked', 'side', 'quad'])

/** Keep only known keys with valid values. Unknown or corrupt values are dropped. */
export function sanitizePrefs(raw: unknown): Partial<WorkPrefs> {
  if (!raw || typeof raw !== 'object') return {}
  const r = raw as Record<string, unknown>
  const out: Partial<WorkPrefs> = {}
  if (typeof r.startPage === 'string' && START_VALUES.has(r.startPage)) out.startPage = r.startPage as StartPage
  if (r.launcher === 'compact' || r.launcher === 'full') out.launcher = r.launcher
  if (typeof r.publisherSoft === 'string' && (r.publisherSoft === '' || PUBLISHER_SOFTS.includes(r.publisherSoft))) out.publisherSoft = r.publisherSoft
  if (typeof r.folderTileSize === 'string' && TILE_VALUES.has(r.folderTileSize)) out.folderTileSize = r.folderTileSize as TileSize
  if (typeof r.folderLayout === 'string' && LAYOUT_VALUES.has(r.folderLayout)) out.folderLayout = r.folderLayout as PaneLayout
  if (typeof r.folderCreatePanel === 'boolean') out.folderCreatePanel = r.folderCreatePanel
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

/**
 * Reads User.json "work_profile". `legacy` carries the old per-browser Folder Manager
 * values (tile size, layout) so a first load keeps what the artist already had.
 */
export function readUserWorkProfile(raw: unknown, legacy: Partial<WorkPrefs> = {}): UserWorkProfile {
  const r = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {}
  const hasPrefs = !!r.prefs && typeof r.prefs === 'object'
  return {
    active: sanitizeRef(r.active) ?? DEFAULT_REF,
    prefs: hasPrefs ? resolvePrefs(r.prefs as Partial<WorkPrefs>) : resolvePrefs(legacy),
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
