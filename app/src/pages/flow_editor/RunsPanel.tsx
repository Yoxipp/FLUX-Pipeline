// RunsPanel.tsx — Runs dock of the Flows editor (03_EDITEUR §7): history of the open flow
// (GET /flows/runs?flow=), newest first: time, trigger, artist / machine, duration, status,
// version. A click opens the run: the graph is coloured by its node states (FlowEditor),
// its report (dry run) and logs are listed here; a log line click selects its node.

import { useEffect, useState } from 'react'
import { X } from 'lucide-react'
import { flowsApi } from '../../api/flows'
import type { RunRecord, RunStatus, RunSummary } from './types'
import { useTr } from './useTr'

const STATUS_COLOR: Record<RunStatus, string> = {
  queued: 'var(--ink-3)', running: 'var(--accent)', ok: 'var(--ok)', error: 'var(--err)',
  cancelled: 'var(--ink-4)', interrupted: 'var(--warn)', skipped: 'var(--ink-4)', refused: 'var(--err)',
}

function when(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function duration(ms: number | null): string {
  if (ms === null || ms === undefined) return ''
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`
}

export function RunsPanel({ flow, project, refreshKey, openRunId, onOpen, onRecord, onSelectNode, onClose }: {
  flow: string
  project?: string
  refreshKey: number
  openRunId: string | null
  onOpen: (runId: string | null) => void
  onRecord: (record: RunRecord | null) => void
  onSelectNode: (id: string) => void
  onClose: () => void
}) {
  const { tr } = useTr()
  const [list, setList] = useState<RunSummary[] | null>(null)
  const [record, setRecord] = useState<RunRecord | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    flowsApi.listRuns({ flow, project, limit: 100 })
      .then(r => { if (alive) { setList(r); setError(null) } })
      .catch(e => { if (alive) setError(String(e?.message ?? e)) })
    return () => { alive = false }
  }, [flow, project, refreshKey])

  useEffect(() => {
    if (!openRunId) { setRecord(null); onRecord(null); return }
    let alive = true
    flowsApi.getRun(openRunId, project)
      .then(r => { if (alive) { setRecord(r); onRecord(r) } })
      .catch(() => { if (alive) { setRecord(null); onRecord(null) } })
    return () => { alive = false }
  }, [openRunId, project, refreshKey])  // eslint-disable-line react-hooks/exhaustive-deps

  const statusLabel: Record<RunStatus, string> = {
    queued: tr('en attente', 'queued'), running: tr('en cours', 'running'), ok: tr('fini', 'done'),
    error: tr('erreur', 'error'), cancelled: tr('annule', 'cancelled'), interrupted: tr('interrompu', 'interrupted'),
    skipped: tr('saute', 'skipped'), refused: tr('refuse', 'refused'),
  }
  const logs = record
    ? Object.entries(record.nodes).flatMap(([node, info]) => (info.logs ?? []).map(l => ({ node, ...l })))
        .sort((a, b) => String(a.at ?? '').localeCompare(String(b.at ?? '')))
    : []

  return (
    <div style={{ height: 230, flexShrink: 0, display: 'flex', borderTop: '1px solid var(--rule)', background: 'var(--paper)', fontSize: 11.5 }}>
      <div style={{ width: 430, flexShrink: 0, overflowY: 'auto', borderRight: '1px solid var(--rule)' }}>
        <div style={{ display: 'flex', alignItems: 'center', padding: '6px 10px', gap: 6, color: 'var(--ink-3)', position: 'sticky', top: 0, background: 'var(--paper)' }}>
          <span style={{ fontWeight: 600, color: 'var(--ink)' }}>{tr('Runs', 'Runs')}</span>
          <span>{flow}</span>
          <span style={{ flex: 1 }} />
          <button type="button" className="flow-tool" onClick={onClose} title={tr('Fermer', 'Close')}><X size={12} /></button>
        </div>
        {error && <div style={{ padding: '4px 10px', color: 'var(--err)' }}>{error}</div>}
        {list?.length === 0 && <div style={{ padding: '4px 10px', color: 'var(--ink-4)' }}>{tr('Aucun run pour ce flow.', 'No run for this flow.')}</div>}
        {list?.map(r => (
          <div
            key={r.run_id}
            onClick={() => onOpen(openRunId === r.run_id ? null : r.run_id)}
            style={{
              display: 'grid', gridTemplateColumns: '108px 1fr 58px 74px', gap: 6, padding: '3px 10px', cursor: 'default',
              background: openRunId === r.run_id ? 'var(--accent-soft)' : undefined,
            }}
          >
            <span style={{ color: 'var(--ink-3)' }}>{when(r.started ?? r.ended)}</span>
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {r.mode === 'dry' ? tr('essai', 'dry') : r.draft ? tr('brouillon', 'draft') : r.version ? `v${String(r.version).padStart(3, '0')}` : ''}
              {' '}{r.trigger?.event ?? ''} · {r.user ?? '?'}@{r.host}
            </span>
            <span style={{ color: 'var(--ink-3)', textAlign: 'right' }}>{duration(r.duration_ms)}</span>
            <span style={{ color: STATUS_COLOR[r.status] ?? 'var(--ink-3)' }}>{statusLabel[r.status] ?? r.status}</span>
          </div>
        ))}
      </div>
      <div style={{ flex: 1, minWidth: 0, overflowY: 'auto', padding: '6px 10px' }}>
        {!record && <div style={{ color: 'var(--ink-4)' }}>{tr('Clique un run pour voir ses logs et colorer le graph.', 'Click a run to see its logs and colour the graph.')}</div>}
        {record && (
          <>
            <div style={{ color: 'var(--ink-2)', marginBottom: 4 }}>
              {record.run_id} · <span style={{ color: STATUS_COLOR[record.status] }}>{statusLabel[record.status]}</span>
              {record.error && <span style={{ color: 'var(--err)' }}> · {record.error}</span>}
            </div>
            {record.issues?.map((i, k) => (
              <div key={`i${k}`} style={{ color: 'var(--err)' }} onClick={() => i.node && onSelectNode(i.node)}>{i.code} {i.node ?? ''} : {i.message_fr}</div>
            ))}
            {record.report?.map((l, k) => (
              <div key={`r${k}`} style={{ color: 'var(--ink-2)' }} onClick={() => l.node && onSelectNode(l.node)}>
                {l.node ? <span className="tag">{l.node}</span> : null} {l.text_fr}{l.path ? ` (${l.path})` : ''}
              </div>
            ))}
            {logs.map((l, k) => (
              <div key={`l${k}`} onClick={() => onSelectNode(l.node)}
                   style={{ color: l.level === 'error' ? 'var(--err)' : l.level === 'warn' ? 'var(--warn)' : 'var(--ink-2)' }}>
                <span className="tag">{l.node}</span> {l.text}
              </div>
            ))}
          </>
        )}
      </div>
    </div>
  )
}
