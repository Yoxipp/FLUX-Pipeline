// UsdPage.tsx — the USD page: everything the project has published in USD (assets,
// decors), edited in place. Modelled on documented USD pipelines (AYON contribution
// workflow for the logic, Solaris Stage Manager for the composition view, ADR 0019).
// The old recipe builder ("Constructeur") is gone: assets are automatic and decors
// are edited here; the /usd/assemble API stays for old recipes.

import { UsdLibrary } from './UsdLibrary'
import { useProject } from '../../ProjectContext'
import { useI18n } from '../../i18n'

export function UsdPage() {
  const { t: tr } = useI18n()
  const { project, projects, setProject } = useProject()

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <div style={{ padding: '12px 20px 10px', borderBottom: '1px solid var(--rule)', flexShrink: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)' }}>{tr('usd.title')}</div>
        <div className="lbl" style={{ fontSize: 10, color: 'var(--ink-4)', marginTop: 2 }}>{tr('usd.subtitle')}</div>
      </div>
      <UsdLibrary project={project} projects={projects} onProject={setProject} />
    </div>
  )
}
