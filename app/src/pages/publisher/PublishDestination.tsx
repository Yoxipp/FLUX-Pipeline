// Publisher "Destination" card: where the publish lands (ADR 0017 flat layout),
// what it writes (new vNNN + LAST) and what already sits in that folder.
import { useEffect, useState } from 'react'
import { Folder, FileText, Link2, Plus, RefreshCw, ExternalLink } from 'lucide-react'
import { api } from '../../api/client'
import { useTr } from '../../i18n'
import type { PublishDestination as Dest } from '../../types'

const mono = 'var(--mono)'
const okSoft = 'color-mix(in oklch, var(--ok) 14%, transparent)'

function Badge({ kind }: { kind: 'new' | 'upd' }) {
  const isNew = kind === 'new'
  const Icon = isNew ? Plus : RefreshCw
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

function Row({ name, kind, link, note }: {
  name: string; kind: 'new' | 'upd' | 'old'; link?: boolean; note?: string
}) {
  const Icon = link ? Link2 : name.endsWith('/') ? Folder : FileText
  const color = kind === 'new' ? 'var(--accent)' : kind === 'upd' ? 'var(--ok)' : 'var(--ink-4)'
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 8, padding: '5px 6px', borderRadius: 5,
      background: kind === 'new' ? 'var(--accent-soft)' : 'transparent',
    }}>
      <Icon size={13} strokeWidth={1.7} style={{ color, flexShrink: 0 }} />
      <span title={name} style={{
        flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        fontSize: 10.5, fontFamily: mono, color: kind === 'old' ? 'var(--ink-3)' : 'var(--ink)',
      }}>{name}</span>
      {note && <span style={{ fontSize: 9.5, fontFamily: mono, color: 'var(--ink-3)' }}>{note}</span>}
      {kind !== 'old' && <Badge kind={kind} />}
    </div>
  )
}

export function PublishDestination({ project, base, ext, sequence, ready }: {
  project: string; base: string; ext: string; sequence: boolean; ready: boolean
}) {
  const { tr } = useTr()
  const [dest, setDest] = useState<Dest | null>(null)

  useEffect(() => {
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
                <span style={i === crumbs.length - 1 ? { color: 'var(--ink)', fontWeight: 500 } : undefined}>{c}</span>
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
          {dest.existing.map(n => <Row key={n} name={n} kind="old" link={n.includes('_LAST')} note={dest.existing_versions?.[n] ?? undefined} />)}
          {dest.more > 0 && (
            <div style={{ padding: '3px 6px', fontSize: 9.5, color: 'var(--ink-4)' }}>+ {dest.more}</div>
          )}
        </>))}
      </div>
    </div>
  )
}
