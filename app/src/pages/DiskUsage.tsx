// DiskUsage — heaviest files under DOSSIER_PROJETS (or a single project).
// A simple readable table, on-demand refresh. No fancy visualisation:
// see which files weigh the most on the drive.

import { useCallback, useEffect, useState } from 'react'
import { RotateCcw, FolderOpen } from 'lucide-react'
import { api } from '../api/client'
import { Btn, SecTitle } from '../components/shared/ui'
import { useProject } from '../ProjectContext'
import { toast } from 'sonner'
import { CleanupPanel } from './disk/CleanupPanel'
import { HoudiniBackupsPanel } from './disk/HoudiniBackupsPanel'

const errMsg = (e: unknown): string => (e instanceof Error ? e.message : String(e))

function humanSize(n: number): string {
  if (n < 1024) return `${n} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let v = n / 1024
  let i = 0
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++ }
  return `${v.toFixed(v < 10 ? 2 : v < 100 ? 1 : 0)} ${units[i]}`
}

function humanDate(t: number): string {
  try { return new Date(t * 1000).toISOString().slice(0, 10) } catch { return '' }
}

type Row = { rel: string; project: string; size: number; mtime: number }
type ProjRow = { project: string; size: number; file_count: number }

export function DiskUsage() {
  const { project: activeProject } = useProject()
  const [scope, setScope] = useState<'all' | 'active'>('all')
  const [limit, setLimit] = useState(200)
  const [rows, setRows] = useState<Row[]>([])
  const [byProject, setByProject] = useState<ProjRow[]>([])
  const [total, setTotal] = useState(0)
  const [fileCount, setFileCount] = useState(0)
  const [root, setRoot] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(() => {
    setBusy(true); setError('')
    const p = scope === 'active' ? (activeProject || undefined) : undefined
    api.getDiskUsage(p, limit)
      .then(r => {
        setRows(r.top_files); setByProject(r.by_project)
        setTotal(r.total_bytes); setFileCount(r.file_count); setRoot(r.root)
      })
      .catch(e => setError(errMsg(e)))
      .finally(() => setBusy(false))
  }, [scope, activeProject, limit])

  useEffect(() => { load() }, [load])

  const copyRel = async (row: Row) => {
    try {
      await navigator.clipboard.writeText(row.rel)
      toast.success('Chemin copié')
    } catch {
      toast.error('Impossible de copier')
    }
  }

  return (
    <div style={{ padding: '16px 20px', overflow: 'auto', height: '100%' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
        <div style={{ flex: 1 }} />
        <select
          value={scope}
          onChange={e => setScope(e.target.value as 'all' | 'active')}
          style={{ padding: '4px 8px', fontSize: 11, fontFamily: 'var(--sans)',
                   background: 'var(--paper-2)', color: 'var(--ink)',
                   border: '1px solid var(--rule-2)', borderRadius: 5 }}
        >
          <option value="all">Tous les projets</option>
          <option value="active" disabled={!activeProject}>
            {activeProject ? `Projet actif : ${activeProject}` : 'Projet actif (aucun)'}
          </option>
        </select>
        <select
          value={String(limit)}
          onChange={e => setLimit(parseInt(e.target.value, 10) || 200)}
          style={{ padding: '4px 8px', fontSize: 11, fontFamily: 'var(--sans)',
                   background: 'var(--paper-2)', color: 'var(--ink)',
                   border: '1px solid var(--rule-2)', borderRadius: 5 }}
        >
          <option value="50">Top 50</option>
          <option value="200">Top 200</option>
          <option value="500">Top 500</option>
          <option value="1000">Top 1000</option>
        </select>
        <Btn onClick={load} disabled={busy}>
          <RotateCcw size={12} strokeWidth={2} />
          {busy ? 'Analyse…' : 'Rafraîchir'}
        </Btn>
      </div>

      {error && (
        <div style={{ padding: '8px 12px', borderRadius: 6, marginBottom: 12,
                      background: 'color-mix(in oklch, var(--err) 12%, transparent)',
                      border: '1px solid var(--err)', color: 'var(--err)', fontSize: 11 }}>
          {error}
        </div>
      )}

      <div style={{ display: 'flex', gap: 20, marginBottom: 16, flexWrap: 'wrap' }}>
        <Stat label="Racine" value={root || '—'} mono />
        <Stat label="Fichiers scannés" value={fileCount.toLocaleString('fr')} />
        <Stat label="Total" value={humanSize(total)} />
      </div>

      {byProject.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <SecTitle>Par projet</SecTitle>
          <div style={{ border: '1px solid var(--rule-2)', borderRadius: 6, overflow: 'hidden' }}>
            {byProject.map(p => {
              const pct = total > 0 ? (p.size / total) * 100 : 0
              return (
                <div key={p.project}
                  style={{ display: 'flex', alignItems: 'center', gap: 12,
                           padding: '7px 10px', borderBottom: '1px solid var(--rule)',
                           fontSize: 11 }}>
                  <FolderOpen size={11} strokeWidth={1.75} color="var(--ink-3)" />
                  <span style={{ fontFamily: 'var(--mono)', width: 200, overflow: 'hidden',
                                 textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {p.project}
                  </span>
                  <div style={{ flex: 1, height: 6, borderRadius: 3, background: 'var(--paper-2)',
                                overflow: 'hidden' }}>
                    <div style={{ width: `${pct}%`, height: '100%', background: 'var(--accent)' }} />
                  </div>
                  <span style={{ fontFamily: 'var(--mono)', color: 'var(--ink-2)', width: 90, textAlign: 'right' }}>
                    {humanSize(p.size)}
                  </span>
                  <span style={{ fontFamily: 'var(--mono)', color: 'var(--ink-3)', width: 60, textAlign: 'right', fontSize: 11 }}>
                    {p.file_count.toLocaleString('fr')} f.
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      <CleanupPanel activeProject={activeProject || null} />
      <HoudiniBackupsPanel activeProject={activeProject || null} />

      <SecTitle>Fichiers les plus lourds</SecTitle>
      <div style={{ border: '1px solid var(--rule-2)', borderRadius: 6, overflow: 'hidden' }}>
        <div style={{ display: 'flex', gap: 12, padding: '7px 10px', fontSize: 11, fontWeight: 600,
                      textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--ink-2)',
                      background: 'var(--paper-2)', borderBottom: '1px solid var(--rule)' }}>
          <span style={{ width: 90, textAlign: 'right' }}>Taille</span>
          <span style={{ width: 90 }}>Modifié</span>
          <span style={{ flex: 1 }}>Chemin (relatif à DOSSIER_PROJETS)</span>
        </div>
        {rows.length === 0
          ? <div style={{ padding: 14, fontSize: 11, color: 'var(--ink-4)' }}>
              {busy ? 'Analyse en cours…' : 'Aucun fichier trouvé.'}
            </div>
          : rows.map((row, i) => (
              <div key={`${row.rel}-${i}`}
                onClick={() => void copyRel(row)}
                title="Cliquer pour copier le chemin"
                style={{ display: 'flex', gap: 12, padding: '6px 10px', fontSize: 12,
                         cursor: 'pointer',
                         borderBottom: i === rows.length - 1 ? 'none' : '1px solid var(--rule)',
                         fontFamily: 'var(--mono)', color: 'var(--ink)' }}
                onMouseEnter={e => (e.currentTarget.style.background = 'var(--accent-soft)')}
                onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
              >
                <span style={{ width: 90, textAlign: 'right', color: 'var(--ink)', fontWeight: 600 }}>
                  {humanSize(row.size)}
                </span>
                <span style={{ width: 90, color: 'var(--ink-2)' }}>{humanDate(row.mtime)}</span>
                <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {/* Folder in a softer tone, file name in full ink: the name is what you look for. */}
                  <span style={{ color: 'var(--ink-2)' }}>{row.rel.slice(0, row.rel.lastIndexOf('/') + 1)}</span>
                  <span style={{ color: 'var(--ink)', fontWeight: 600 }}>{row.rel.slice(row.rel.lastIndexOf('/') + 1)}</span>
                </span>
              </div>
            ))}
      </div>
    </div>
  )
}

function Stat({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <div style={{ fontSize: 10.5, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--ink-3)' }}>
        {label}
      </div>
      <div style={{ fontSize: 13, fontFamily: mono ? 'var(--mono)' : 'var(--sans)',
                    color: 'var(--ink)', marginTop: 2 }}>
        {value}
      </div>
    </div>
  )
}
