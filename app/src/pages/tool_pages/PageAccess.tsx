// PageAccess.tsx — who a TOOL page is meant for (ADR 0078), at creation and in the page
// properties. Everyone, or any mix of people, project roles and departments (a person
// matches one list). The others still find the page under "Other tools": a filter, no lock.

import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import { rolesApi } from '../../api/roles'
import type { PageAccess } from '../flow_editor/types'
import { useTr } from '../flow_editor/useTr'

const ROLES = ['junior', 'artist', 'lead', 'supervisor']
const ROLE_LABELS: Record<string, string> = { junior: 'Junior', artist: 'Artist', lead: 'Lead', supervisor: 'Supervisor' }
// Mirror of project_roles.DEPARTMENTS, used only without a project (team page, no roles.json).
const FALLBACK_DEPARTMENTS = ['MODELING', 'SURFACING', 'GROOM', 'RIG', 'CFX', 'LAYOUT', 'ANIM', 'FX', 'LIGHT', 'COMP']

export function isEveryone(a: PageAccess | undefined | null): boolean {
  return !a || !(a.users?.length || a.roles?.length || a.departments?.length)
}

/** Access without its empty lists, undefined for everyone (the YAML then has no access key). */
export function cleanAccess(a: PageAccess): PageAccess | undefined {
  const out: PageAccess = {}
  if (a.users?.length) out.users = a.users
  if (a.roles?.length) out.roles = a.roles
  if (a.departments?.length) out.departments = a.departments
  return isEveryone(out) ? undefined : out
}

function Chips({ title, options, labels, value, onChange }: { title: string; options: string[]; labels?: Record<string, string>; value: string[]; onChange: (v: string[]) => void }) {
  if (!options.length) return null
  return (
    <div style={{ marginBottom: 6 }}>
      <div className="cap" style={{ marginBottom: 3 }}>{title}</div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3 }}>
        {options.map(o => {
          const on = value.includes(o)
          return (
            <button key={o} type="button" onClick={() => onChange(on ? value.filter(x => x !== o) : [...value, o])}
              style={{ height: 20, padding: '0 7px', fontSize: 10.5, borderRadius: 4, cursor: 'pointer',
                       border: `1px solid ${on ? 'var(--accent)' : 'var(--rule-2)'}`, background: on ? 'var(--accent-soft)' : 'transparent',
                       color: on ? 'var(--ink)' : 'var(--ink-3)' }}>{labels?.[o] ?? o}</button>
          )
        })}
      </div>
    </div>
  )
}

export function AccessPicker({ value, onChange, project }: { value: PageAccess | undefined; onChange: (v: PageAccess | undefined) => void; project?: string }) {
  const { tr } = useTr()
  const [custom, setCustom] = useState(!isEveryone(value))
  const [users, setUsers] = useState<string[]>([])
  const [departments, setDepartments] = useState<string[]>(FALLBACK_DEPARTMENTS)

  useEffect(() => {
    let alive = true
    api.listUsers().then(r => { if (alive) setUsers(r.users.map(u => u.toUpperCase()).sort()) }).catch(() => { /* names stay empty */ })
    if (project) rolesApi.get(project).then(r => { if (alive) setDepartments(r.departments) }).catch(() => { /* fallback list */ })
    return () => { alive = false }
  }, [project])

  const cur: PageAccess = value ?? {}
  const patch = (p: PageAccess) => onChange(cleanAccess({ ...cur, ...p }))
  // Names already chosen stay offered even when the account is gone.
  const names = [...new Set([...users, ...(cur.users ?? [])])].sort()

  return (
    <div>
      <div style={{ display: 'flex', gap: 4, marginBottom: 6 }}>
        <button type="button" className={`btn sm${custom ? ' ghost' : ''}`} onClick={() => { setCustom(false); onChange(undefined) }}>{tr('Tout le monde', 'Everyone')}</button>
        <button type="button" className={`btn sm${custom ? '' : ' ghost'}`} onClick={() => setCustom(true)}>{tr('Choisir', 'Choose')}</button>
      </div>
      {custom && <>
        <Chips title={tr('Roles', 'Roles')} options={ROLES} labels={ROLE_LABELS} value={cur.roles ?? []} onChange={v => patch({ roles: v })} />
        <Chips title={tr('Departements', 'Departments')} options={departments} value={cur.departments ?? []} onChange={v => patch({ departments: v })} />
        <Chips title={tr('Personnes', 'People')} options={names} value={cur.users ?? []} onChange={v => patch({ users: v })} />
        <div className="tp-note" style={{ color: 'var(--ink-4)' }}>
          {isEveryone(value)
            ? tr('Rien de coche : la page reste pour tout le monde.', 'Nothing ticked: the page stays for everyone.')
            : tr('Les autres la trouvent sous "Other tools".', 'The others find it under "Other tools".')}
        </div>
      </>}
    </div>
  )
}
