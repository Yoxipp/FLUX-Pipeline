// ProjectContext.tsx — single source of truth for the active project.
//
// Usage:
//   const { project, projects, setProject, loading } = useProject()
//
// The active project is shared across every page, persisted to localStorage
// (instant on reload) and to the backend config.json (survives a restart).
// Mirrors the LanguageProvider pattern in i18n.tsx.

import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { api } from './api/client'

const LS_KEY = 'flux.project'

interface ProjectContextValue {
  project: string
  projects: string[]
  setProject: (name: string) => void
  refreshProjects: () => Promise<void>
  loading: boolean
}

const ProjectContext = createContext<ProjectContextValue | null>(null)

function readCachedProject(): string {
  try {
    return localStorage.getItem(LS_KEY) ?? ''
  } catch {
    return ''
  }
}

export function ProjectProvider({ children }: { children: ReactNode }) {
  const [projects, setProjects] = useState<string[]>([])
  const [project, setProjectState] = useState<string>(readCachedProject)
  const [loading, setLoading] = useState(true)

  const refreshProjects = useCallback(async () => {
    try {
      const r = await api.getProjects()
      setProjects(r.projects)
    } catch {
      /* backend down — keep what we have */
    }
  }, [])

  // On mount: load the project list + the backend's persisted active project.
  // Precedence: backend value (if still valid) > cached localStorage > projects[0].
  useEffect(() => {
    let alive = true
    ;(async () => {
      let list: string[] = []
      try {
        list = (await api.getProjects()).projects
      } catch {
        /* backend down */
      }
      let active = ''
      try {
        active = (await api.getCurrentProject()).project ?? ''
      } catch {
        /* backend down */
      }
      if (!alive) return
      setProjects(list)
      const cached = readCachedProject()
      const pick =
        (active && (list.length === 0 || list.includes(active)) && active) ||
        (cached && (list.length === 0 || list.includes(cached)) && cached) ||
        list[0] ||
        ''
      setProjectState(pick)
      try {
        if (pick) localStorage.setItem(LS_KEY, pick)
      } catch {
        /* blocked storage */
      }
      setLoading(false)
    })()
    return () => {
      alive = false
    }
  }, [])

  const setProject = useCallback((name: string) => {
    setProjectState(name)
    try {
      localStorage.setItem(LS_KEY, name)
    } catch {
      /* blocked storage */
    }
    // fire-and-forget persist; the UI already reflects the change
    void api.setCurrentProject(name).catch(() => {
      /* keep local choice even if the backend rejects it */
    })
  }, [])

  return (
    <ProjectContext.Provider value={{ project, projects, setProject, refreshProjects, loading }}>
      {children}
    </ProjectContext.Provider>
  )
}

export function useProject(): ProjectContextValue {
  const ctx = useContext(ProjectContext)
  if (!ctx) throw new Error('useProject must be used within a ProjectProvider')
  return ctx
}
