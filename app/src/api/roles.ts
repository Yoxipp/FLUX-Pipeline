// roles.ts - artists' roles on a project (ADR 0064). Kept out of client.ts on purpose.

import { apiCall } from './client'

export type ProjectRole = 'junior' | 'artist' | 'lead' | 'supervisor'

export interface RoleMember {
  name: string
  role: ProjectRole
  listed: boolean            // false = default role (not written in roles.json)
  assignable: ProjectRole[]  // roles the active user may give this member
  departments: string[]      // ADR 0078, targets TOOL pages
  can_set_departments: boolean
}

export interface RolesSummary {
  project: string
  roles: ProjectRole[]
  labels: Record<ProjectRole, string>
  default_role: ProjectRole
  departments: string[]      // the departments offered
  created_by: string | null
  legacy: boolean
  supervisors: string[]
  can_claim: boolean
  me: { user: string | null; role: ProjectRole | null; departments: string[]; can: Record<string, boolean> }
  members: RoleMember[]
  note_fr: string
}

const enc = encodeURIComponent

export const rolesApi = {
  get: (project: string) => apiCall<RolesSummary>('GET', `/roles/${enc(project)}`),
  set: (project: string, user: string, role: ProjectRole) =>
    apiCall<RolesSummary>('PUT', `/roles/${enc(project)}`, { user, role }),
  setDepartments: (project: string, user: string, departments: string[]) =>
    apiCall<RolesSummary>('PUT', `/roles/${enc(project)}/departments`, { user, departments }),
  claim: (project: string) => apiCall<RolesSummary>('POST', `/roles/${enc(project)}/claim`),
}
