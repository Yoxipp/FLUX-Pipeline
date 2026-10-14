// ProjectPicker - the active project selector (same as the Publisher toolbar).
// The project lives in ProjectContext, so a change here follows every page.

import { useProject } from '../../ProjectContext'
import { FolderIcon, Select, SelectTrigger, SelectContent, SelectItem } from './ui'
import { useI18n } from '../../i18n'

export function ProjectPicker({ width = 190 }: { width?: number }) {
  const { project, projects, setProject } = useProject()
  const { lang } = useI18n()
  const tr = (fr: string, en: string) => (lang === 'en' ? en : fr)
  return (
    <div style={{ position: 'relative', display: 'flex', alignItems: 'center', flexShrink: 0 }}>
      <span style={{ position: 'absolute', left: 8, pointerEvents: 'none', display: 'flex', zIndex: 1 }}>
        <FolderIcon color="var(--accent)" />
      </span>
      <Select value={project} onValueChange={setProject}>
        <SelectTrigger style={{ width, paddingLeft: 26 }} title={tr('Projet', 'Project')} />
        <SelectContent>
          {projects.length === 0
            ? <SelectItem value="__none__">{tr('Aucun projet', 'No project')}</SelectItem>
            : projects.map(p => <SelectItem key={p} value={p}>{p}</SelectItem>)}
        </SelectContent>
      </Select>
    </div>
  )
}
