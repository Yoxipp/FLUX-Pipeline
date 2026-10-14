// Publisher "Destination" card: where the publish lands (ADR 0017 flat layout),
// what it writes (new vNNN + LAST) and what already sits in that folder.
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Folder, FileText, Link2, RefreshCw, ExternalLink } from 'lucide-react'
import { api } from '../../api/client'
import { useTr } from '../../i18n'
import type { PublishDestination as Dest } from '../../types'

const mono = 'var(--mono)'
const okSoft = 'color-mix(in oklch, var(--ok) 14%, transparent)'

function Badge({ kind }: { kind: 'new' | 'upd' }) {
  const isNew = kind === 'new'
  if (isNew) return (
    <span style={{
      flexShrink: 0, padding: '1px 6px', borderRadius: 4, fontSize: 9, fontWeight: 700,
      letterSpacing: '0.06em', background: 'var(--accent)', color: 'var(--on-accent)',
    }}>NEW</span>
  )
  const Icon = RefreshCw
  return (
    <span style={{
      width: 18, height: 18, borderRadius: '50%', flexShrink: 0,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: isNew ? 'var(--accent-soft)' : okSoft,
      color: isNew ? 'var(--accent)' : 'var(--ok)',
    }}>
      <Icon size={10} strokeWidth={2.4} />
    </span>
  )
}

// Version comment of an existing file, from the folder's modif_logs.json.
interface VersionLog { modification?: string; user?: string; date?: string; time?: string; version?: string }

function Row({ name, kind, link, note, loadLog }: {
  name: string; kind: 'new' | 'upd' | 'old'; link?: boolean; note?: string
  loadLog?: (name: string) => Promise<VersionLog | null>
}) {
  const Icon = link ? Link2 : name.endsWith('/') ? Folder : FileText
  const color = kind === 'new' ? 'var(--accent)' : kind === 'upd' ? 'var(--ok)' : 'var(--ink-4)'
  const [open, setOpen] = useState(false)
  const [entry, setEntry] = useState<VersionLog | null | undefined>(undefined)
  const toggle = () => {
    if (!loadLog) return
    setOpen(o => !o)
    if (entry === undefined) void loadLog(name).then(setEntry, () => setEntry(null))
  }
  return (<>
    <div onClick={toggle} title={loadLog ? 'Voir le commentaire de la version' : undefined} style={{
      display: 'flex', alignItems: 'center', gap: 8, padding: '5px 6px', borderRadius: 5,
      background: kind === 'new' ? 'var(--accent-soft)' : open ? 'var(--paper-2)' : 'transparent',
      cursor: loadLog ? 'pointer' : undefined,
    }}>
      <Icon size={13} strokeWidth={1.7} style={{ color, flexShrink: 0 }} />
      <span title={name} style={{
        flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        fontSize: 10.5, fontFamily: mono, color: kind === 'old' ? 'var(--ink-3)' : 'var(--ink)',
      }}>{name}</span>
      {note && <span style={{ fontSize: 9.5, fontFamily: mono, color: 'var(--ink-3)' }}>{note}</span>}
      {kind !== 'old' && <Badge kind={kind} />}
    </div>
    {open && (
      <div style={{ margin: '0 6px 4px 27px', padding: '5px 8px', borderLeft: '2px solid var(--rule-3)', fontSize: 10.5, color: 'var(--ink-2)', whiteSpace: 'pre-wrap' }}>
        {entry === undefined ? '…'
          : !entry || !entry.modification ? <span style={{ color: 'var(--ink-4)' }}>Pas de commentaire</span>
          : <>
            {entry.modification}
            <div style={{ marginTop: 3, fontSize: 9.5, fontFamily: mono, color: 'var(--ink-4)' }}>
              {[entry.version, entry.user, entry.date && `${entry.date} ${entry.time ?? ''}`.trim()].filter(Boolean).join(' · ')}
            </div>
          </>}
      </div>
    )}
  </>)
}

export function PublishDestination({ project, base, ext, sequence, ready }: {
  project: string; base: string; ext: string; sequence: boolean; ready: boolean
}) {
  const { tr } = useTr()
  const [dest, setDest] = useState<Dest | null>(null)
  const [showAll, setShowAll] = useState(false)

  useEffect(() => {
    setShowAll(false)
    if (!project || !ready || !ext) { setDest(null); return }
    let cancelled = false
    // Debounced: the composer fires on every keystroke.
    const t = setTimeout(() => {
      api.getPublishDestination(project, base, ext, sequence)
        .then(d => { if (!cancelled) setDest(d) })
        .catch(() => { if (!cancelled) setDest(null) })
    }, 250)
    const refresh = () => {
      api.getPublishDestination(project, base, ext, sequence)
        .then(d => { if (!cancelled) setDest(d) }).catch(() => {})
    }
    window.addEventListener('flux:refresh', refresh)
    return () => { cancelled = true; clearTimeout(t); window.removeEventListener('flux:refresh', refresh) }
  }, [project, base, ext, sequence, ready])

  const ver = dest?.version ?? 'v001'
  const crumbs = (dest?.rel_path ?? '').split('/').filter(Boolean)
  // Folder listing (with each file's latest modif_log entry), fetched once on the first click.
  const [logs, setLogs] = useState<Promise<Record<string, VersionLog>> | null>(null)
  useEffect(() => { setLogs(null) }, [dest?.rel_path])
  const loadLog = async (name: string) => {
    let p = logs
    if (!p) {
      p = api.browseProject(project, dest?.rel_path ?? '').then(r =>
        Object.fromEntries(r.files.map(f => [f.name, f as unknown as VersionLog])))
      setLogs(p)
    }
    return (await p)[name] ?? null
  }
  const navigate = useNavigate()
  // Absolute folder of crumb i: the destination path minus the crumbs after it.
  const crumbPath = (i: number) => {
    const parts = (dest?.abs_path ?? '').split(/[\\/]/)
    return parts.slice(0, parts.length - (crumbs.length - 1 - i)).join('\\')
  }

  return (
    <div className="subcard" style={{ padding: 0, overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '9px 10px 6px' }}>
        <Folder size={13} strokeWidth={1.7} style={{ color: 'var(--accent)', flexShrink: 0 }} />
        <div style={{
          flex: 1, minWidth: 0, display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 4,
          fontSize: 10.5, color: 'var(--ink-3)',
        }}>
          {crumbs.length === 0
            ? <span style={{ color: 'var(--ink-4)' }}>{tr('Complète le nom', 'Complete the name')}</span>
            : crumbs.map((c, i) => (
              <span key={i} style={{ display: 'inline-flex', gap: 4 }}>
                {i > 0 && <span style={{ color: 'var(--ink-4)' }}>›</span>}
                <span role="link" tabIndex={0} className="dest-crumb" title={tr('Ouvrir dans le Folder Manager', 'Open in the Folder Manager')}
                  onClick={() => navigate('/projects', { state: { openPath: crumbPath(i) } })}
                  onKeyDown={e => { if (e.key === 'Enter') navigate('/projects', { state: { openPath: crumbPath(i) } }) }}
                  style={{ cursor: 'pointer', ...(i === crumbs.length - 1 ? { color: 'var(--ink)', fontWeight: 500 } : {}) }}>{c}</span>
              </span>
            ))}
        </div>
        {dest && window.electronAPI?.openPath && (
          <button
            title={tr('Ouvrir le dossier', 'Open the folder')}
            onClick={() => void window.electronAPI?.openPath(dest.abs_path)}
            className="scale-hover"
            style={{
              display: 'flex', padding: 4, borderRadius: 5, cursor: 'pointer',
              border: '1px solid var(--rule-2)', background: 'var(--paper-2)', color: 'var(--ink-3)',
            }}
          ><ExternalLink size={11} strokeWidth={1.8} /></button>
        )}
      </div>

      <div style={{ padding: '0 4px 6px' }}>
        {sequence ? (
          <Row name={`${base}_${ver}/`} kind="new" note={`.$F4${ext}`} />
        ) : (<>
          <Row name={`${base}_${ver}${ext}`} kind="new" />
          <Row name={`${base}_LAST${ext}`} kind={dest?.last_exists === false ? 'new' : 'upd'} link note={ver} />
        </>)}

        {dest && (dest.first ? (
          <div style={{ padding: '4px 6px', fontSize: 9.5, color: 'var(--ink-4)' }}>{tr('Première version', 'First version')}</div>
        ) : (<>
          {(dest.existing.length > 0 || dest.more > 0) && (
            <div style={{ height: 1, background: 'var(--rule)', margin: '4px 6px' }} />
          )}
          {dest.existing.map(n => <Row key={n} name={n} kind="old" link={n.includes('_LAST')} note={dest.existing_versions?.[n] ?? undefined} loadLog={loadLog} />)}
          {showAll && (dest.others ?? []).map(n => <Row key={n} name={n} kind="old" link={n.includes('_LAST')} loadLog={loadLog} />)}
          {dest.more > 0 && (
            <button
              onClick={() => setShowAll(v => !v)}
              style={{
                display: 'block', border: 'none', background: 'transparent', cursor: 'pointer',
                padding: '3px 6px', fontSize: 10, fontFamily: mono, color: 'var(--ink-3)',
              }}
            >{showAll ? tr('Réduire', 'Collapse') : `+ ${dest.more}`}</button>
          )}
        </>))}
      </div>
    </div>
  )
}
