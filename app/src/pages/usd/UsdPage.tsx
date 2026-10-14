// UsdPage.tsx — the USD page: everything the project has published in USD (assets,
// decors), edited in place. Modelled on documented USD pipelines (AYON contribution
// workflow for the logic, Solaris Stage Manager for the composition view, ADR 0019).
// The old recipe builder ("Constructeur") is gone: assets are automatic and decors
// are edited here; the /usd/assemble API stays for old recipes.

import { UsdLibrary } from './UsdLibrary'
import { useProject } from '../../ProjectContext'

export function UsdPage() {
  const { project, projects, setProject } = useProject()

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <UsdLibrary project={project} projects={projects} onProject={setProject} />
    </div>
  )
}
