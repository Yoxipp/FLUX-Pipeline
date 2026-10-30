// ProjectRoles.tsx - Parametres > Projet > Roles (ADR 0064): junior < artist < lead < supervisor.
// The backend says which roles the active user may give each artist; the UI only offers those.

import { useEffect, useState } from 'react'
import { Shield } from 'lucide-react'
import { toast } from 'sonner'
import { rolesApi, type ProjectRole, type RolesSummary } from '../../api/roles'
import { Btn, SecTitle } from '../../components/shared/ui'

const HINTS: Record<ProjectRole, string> = {
  junior: 'Publie, importe, fait avancer ses taches. Ne modifie pas les seq / shots.',
  artist: '+ archive, renomme, regle les seq / shots.',
  lead: '+ suppression definitive, environnement farm, reglages du projet, roles junior / artist / lead, reset des mots de passe.',
  supervisor: '+ nomme les Supervisors, gere les comptes, supprime le projet.',
}

export function ProjectRoles({ project }: { project: string }) {
  const [data, setData] = useState<RolesSummary | null>(null)
  const [busy, setBusy] = useState(false)
  const refresh = () => rolesApi.get(project).then(setData).catch(e => toast.error(e instanceof Error ? e.message : String(e)))
  useEffect(() => { setData(null); void refresh() }, [project])   // eslint-disable-line react-hooks/exhaustive-deps

  const run = async (call: () => Promise<RolesSummary>, ok: string) => {
    setBusy(true)
    try { setData(await call()); toast.success(ok) }
    catch (e) { toast.error(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }

  if (!data) return null
  const label = (r: ProjectRole | null) => (r ? data.labels[r] : 'aucun')
  return (
    <>
      <SecTitle>Rôles du projet</SecTitle>
      <div className="card" style={{ padding: '8px 12px', fontSize: 11, color: 'var(--ink-2)', lineHeight: 1.5 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Shield size={14} strokeWidth={1.75} color="var(--ink-3)" />
          <span style={{ flex: 1 }}>
            Ton rôle : <b>{label(data.me.role)}</b>
            {data.created_by && <> · créé par {data.created_by}</>}
            {' · '}Supervisors : {data.supervisors.length ? data.supervisors.join(', ') : 'aucun'}
          </span>
          {data.can_claim && (
            <Btn sm ghost disabled={busy} title="Le projet n'a aucun Supervisor : tu le deviens"
              onClick={() => void run(() => rolesApi.claim(project), 'Tu es Supervisor du projet')}>Devenir Supervisor</Btn>
          )}
        </div>
        <div style={{ marginTop: 4, color: 'var(--ink-4)' }}>
          Sans rôle donné, un artiste est {data.labels[data.default_role]}. {data.note_fr}
        </div>
      </div>
      <div className="card" style={{ padding: '4px 12px' }}>
        {data.members.map(m => (
          <div key={m.name} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '5px 0', borderBottom: '1px solid var(--rule)' }}>
            <span style={{ flex: 1, fontSize: 11, color: 'var(--ink-2)' }}>{m.name}</span>
            {m.assignable.length > 1 ? (
              <select value={m.role} disabled={busy} title={HINTS[m.role]}
                onChange={e => void run(() => rolesApi.set(project, m.name, e.target.value as ProjectRole), `${m.name} : ${data.labels[e.target.value as ProjectRole]}`)}
                style={{ height: 24, fontSize: 11, background: 'var(--paper-2)', color: 'var(--ink)', border: '1px solid var(--rule-2)', borderRadius: 5 }}>
                {m.assignable.map(r => <option key={r} value={r}>{data.labels[r]}</option>)}
              </select>
            ) : (
              <span title={HINTS[m.role]} style={{ fontSize: 11, color: m.listed ? 'var(--ink-2)' : 'var(--ink-4)' }}>{data.labels[m.role]}</span>
            )}
          </div>
        ))}
      </div>
    </>
  )
}
