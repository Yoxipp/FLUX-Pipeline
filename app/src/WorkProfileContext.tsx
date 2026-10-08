// WorkProfileContext.tsx - working prefs + artist work profiles (ADR 0042).
//
// Loads User.json "work_profile" once (debounced save afterwards, like the Folder
// Manager favorites) and the profiles shared by the active project. Pages read
// `prefs` and write through `setPref`; nothing here touches Production state.

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { api } from './api/client'
import { useProject } from './ProjectContext'
import {
  BUILTIN_PROFILES, DEFAULT_REF, findProfile, modifiedKeys, profilePrefs, readUserWorkProfile,
  sanitizeProfiles, upsertProfile,
  type ProfileRef, type UserWorkProfile, type WorkPrefs, type WorkProfile,
} from './lib/workProfiles'

interface WorkProfileValue {
  ready: boolean
  prefs: WorkPrefs
  setPref: <K extends keyof WorkPrefs>(key: K, value: WorkPrefs[K]) => void
  active: ProfileRef
  activeProfile: WorkProfile | null
  modified: (keyof WorkPrefs)[]
  project: string
  projectProfiles: WorkProfile[]
  customProfiles: WorkProfile[]
  applyProfile: (ref: ProfileRef) => void
  resetToProfile: () => void
  saveAsUser: (name: string) => void
  shareToProject: (name: string) => Promise<void>
  deleteProfile: (ref: ProfileRef) => Promise<void>
}

const WorkProfileContext = createContext<WorkProfileValue | null>(null)

export function WorkProfileProvider({ children }: { children: ReactNode }) {
  const { project } = useProject()
  const [state, setState] = useState<UserWorkProfile>(() => readUserWorkProfile(undefined))
  const [ready, setReady] = useState(false)
  const [projectProfiles, setProjectProfiles] = useState<WorkProfile[]>([])
  const loaded = useRef(false)

  useEffect(() => {
    let alive = true
    api.getUserData()
      .then(data => { if (alive) setState(readUserWorkProfile(data.work_profile)) })
      .catch(() => { /* backend down: keep the local seed, never overwrite the store */ })
      .finally(() => { if (alive) { loaded.current = true; setReady(true) } })
    return () => { alive = false }
  }, [])

  // Debounced save; the guard keeps the initial seed from overwriting the store.
  useEffect(() => {
    if (!loaded.current) return
    const timer = setTimeout(() => { void api.setUserData({ work_profile: state }).catch(() => {}) }, 400)
    return () => clearTimeout(timer)
  }, [state])

  const loadProjectProfiles = useCallback(() => {
    if (!project) { setProjectProfiles([]); return }
    api.getProjectWorkProfiles(project)
      .then(r => setProjectProfiles(sanitizeProfiles(r.profiles)))
      .catch(() => setProjectProfiles([]))
  }, [project])
  useEffect(() => {
    loadProjectProfiles()
    window.addEventListener('flux:refresh', loadProjectProfiles)
    return () => window.removeEventListener('flux:refresh', loadProjectProfiles)
  }, [loadProjectProfiles])

  const setPref = useCallback(<K extends keyof WorkPrefs>(key: K, value: WorkPrefs[K]) => {
    setState(prev => prev.prefs[key] === value ? prev : { ...prev, prefs: { ...prev.prefs, [key]: value } })
  }, [])

  const activeProfile = findProfile(state.active, projectProfiles, state.custom)

  const applyProfile = useCallback((ref: ProfileRef) => {
    const profile = findProfile(ref, projectProfiles, state.custom)
    if (!profile) return
    setState(prev => ({ ...prev, active: ref, prefs: profilePrefs(profile) }))
    toast.success(`Profil appliqué : ${profile.name}`)
  }, [projectProfiles, state.custom])

  const resetToProfile = useCallback(() => {
    setState(prev => ({ ...prev, prefs: profilePrefs(findProfile(prev.active, projectProfiles, prev.custom)) }))
  }, [projectProfiles])

  const saveAsUser = useCallback((name: string) => {
    if (!name.trim()) return
    setState(prev => {
      const { list, id } = upsertProfile(prev.custom, name, prev.prefs)
      return { ...prev, custom: list, active: { source: 'user', id } }
    })
    toast.success(`Profil enregistré : ${name.trim()}`)
  }, [])

  const shareToProject = useCallback(async (name: string) => {
    if (!project || !name.trim()) return
    const { list, id } = upsertProfile(projectProfiles, name, state.prefs)
    try {
      const r = await api.setProjectWorkProfiles(project, list)
      setProjectProfiles(sanitizeProfiles(r.profiles))
      setState(prev => ({ ...prev, active: { source: 'project', id } }))
      toast.success(`Profil partagé avec ${project}`)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Partage du profil impossible')
    }
  }, [project, projectProfiles, state.prefs])

  const deleteProfile = useCallback(async (ref: ProfileRef) => {
    if (ref.source === 'builtin') return
    if (ref.source === 'user') {
      setState(prev => ({ ...prev, custom: prev.custom.filter(p => p.id !== ref.id), active: prev.active.source === 'user' && prev.active.id === ref.id ? DEFAULT_REF : prev.active }))
      return
    }
    if (!project) return
    try {
      const r = await api.setProjectWorkProfiles(project, projectProfiles.filter(p => p.id !== ref.id))
      setProjectProfiles(sanitizeProfiles(r.profiles))
      setState(prev => prev.active.source === 'project' && prev.active.id === ref.id ? { ...prev, active: DEFAULT_REF } : prev)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Suppression du profil impossible')
    }
  }, [project, projectProfiles])

  const value = useMemo<WorkProfileValue>(() => ({
    ready, prefs: state.prefs, setPref, active: state.active, activeProfile,
    modified: modifiedKeys(state.prefs, activeProfile), project, projectProfiles,
    customProfiles: state.custom, applyProfile, resetToProfile, saveAsUser, shareToProject, deleteProfile,
  }), [ready, state, setPref, activeProfile, project, projectProfiles, applyProfile, resetToProfile, saveAsUser, shareToProject, deleteProfile])

  return <WorkProfileContext.Provider value={value}>{children}</WorkProfileContext.Provider>
}

export function useWorkProfile(): WorkProfileValue {
  const ctx = useContext(WorkProfileContext)
  if (!ctx) throw new Error('useWorkProfile must be used within a WorkProfileProvider')
  return ctx
}

/** Opens the profile's start page once, when FLUX starts on Home. */
export function StartPageRedirect() {
  const { ready, prefs } = useWorkProfile()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const done = useRef(false)
  useEffect(() => {
    if (!ready || done.current) return
    done.current = true
    if (pathname === '/' && prefs.startPage !== '/') navigate(prefs.startPage, { replace: true })
  }, [ready, prefs.startPage, pathname, navigate])
  return null
}

export { BUILTIN_PROFILES }
