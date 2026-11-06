// TeamArchive.tsx - archived Team channels and groups of a project, in Projects > Archived
// (2026-10-31). The only way back for an archived channel: a new channel with the same
// name starts empty (ChatWidget). Restoring needs the lead role (backend 403) and is refused
// while a live channel shows the same name (409).

import { useCallback, useEffect, useState } from 'react'
import { Folder, Hash, RotateCcw, Volume2 } from 'lucide-react'
import { toast } from 'sonner'
import { teamApi, type TeamRecord } from '../../api/team'
import { useTr } from '../flow_editor/useTr'

export function TeamArchive({ project }: { project: string }) {
  const { tr } = useTr()
  const [items, setItems] = useState<TeamRecord[]>([])
  const [lead, setLead] = useState(false)

  const load = useCallback(() => {
    teamApi.meta(project).then(r => {
      setLead(r.lead)
      if (!r.unchanged) setItems(r.records.filter(x => (x.kind === 'channel' || x.kind === 'group') && x.archived))
    }).catch(() => setItems([]))
  }, [project])
  useEffect(load, [load])

  const restore = (r: TeamRecord) =>
    teamApi.writeMeta(project, [{ op: 'put', rid: r.rid, fields: { archived: null } }])
      .then(() => { toast.success(tr(`${label(r)} restaure dans Team`, `${label(r)} restored in Team`)); load() })
      .catch(err => toast.error((err as Error).message))

  if (!items.length) return null
  return (
    <div style={{ marginBottom: 8, paddingBottom: 6, borderBottom: '1px solid var(--rule)' }}>
      <div className="cap" style={{ padding: '4px 8px' }}>{tr('Team : canaux et groupes archives', 'Team: archived channels and groups')}</div>
      {items.map(r => (
        <div key={r.rid} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '5px 8px', fontSize: 11 }}>
          {r.kind === 'group' ? <Folder size={14} /> : r.type === 'voice' ? <Volume2 size={14} /> : <Hash size={14} />}
          <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{label(r)}</span>
          <span style={{ color: 'var(--ink-4)' }}>{r._by}</span>
          {lead && <button type="button" className="btn ghost sm" onClick={() => void restore(r)}><RotateCcw size={11} /> {tr('Restaurer', 'Restore')}</button>}
        </div>
      ))}
    </div>
  )
}

const label = (r: TeamRecord) => r.kind === 'group' ? String(r.name) : `#${r.title || r.name}`
