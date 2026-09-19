// PublishNote — the note of a published file (N7): who, when, version and description
// read from modif_logs.json (GET /files/projects/<p>/publish-note), plus the history of
// the same publish, folded by default. Renders nothing for a file without a note.

import { useEffect, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { api } from '../../api/client'
import type { PublishNoteEntry } from '../../api/client'

export function PublishNote({ project, relPath }: { project: string; relPath: string }) {
  const [latest, setLatest] = useState<PublishNoteEntry | null>(null)
  const [history, setHistory] = useState<PublishNoteEntry[]>([])
  const [open, setOpen] = useState(false)

  useEffect(() => {
    let alive = true
    setLatest(null); setHistory([]); setOpen(false)
    if (!project || !relPath) return
    api.getPublishNote(project, relPath)
      .then(r => { if (alive) { setLatest(r.latest); setHistory(r.history) } })
      .catch(() => { /* no note: the panel stays hidden */ })
    return () => { alive = false }
  }, [project, relPath])

  if (!latest && history.length === 0) return null
  return (
    <div style={{ padding: '10px 12px', borderTop: '1px solid var(--rule)', flexShrink: 0, maxHeight: 260, overflowY: 'auto' }}>
      <div className="cap" style={{ marginBottom: 6 }}>NOTE DE PUBLISH</div>
      {latest ? <NoteCard entry={latest} strong /> : (
        <div style={{ fontSize: 9, color: 'var(--ink-4)' }}>Pas de note pour cette version</div>
      )}
      {history.length > 1 && (
        <>
          <div
            onClick={() => setOpen(o => !o)}
            style={{ display: 'flex', alignItems: 'center', gap: 4, marginTop: 8, cursor: 'pointer',
                     fontFamily: 'var(--mono)', fontSize: 8.5, color: 'var(--ink-3)', textTransform: 'uppercase',
                     letterSpacing: '0.06em' }}
          >
            {open ? <ChevronDown size={10} strokeWidth={2} /> : <ChevronRight size={10} strokeWidth={2} />}
            Historique ({history.length})
          </div>
          {open && history.map((e, i) => <NoteCard key={`${e.version}-${i}`} entry={e} />)}
        </>
      )}
    </div>
  )
}

function NoteCard({ entry, strong }: { entry: PublishNoteEntry; strong?: boolean }) {
  return (
    <div style={{
      padding: '6px 8px', borderRadius: 5, marginTop: strong ? 0 : 4,
      border: '1px solid var(--rule-2)', background: strong ? 'var(--paper)' : 'transparent',
    }}>
      <div style={{ display: 'flex', gap: 6, alignItems: 'baseline' }}>
        <span style={{ fontFamily: 'var(--mono)', fontSize: 9.5, fontWeight: 600, color: 'var(--ink)' }}>{entry.version}</span>
        <span style={{ fontSize: 8.5, color: 'var(--ink-4)' }}>{entry.user} · {entry.date} {entry.time}</span>
      </div>
      {entry.modification && (
        <div style={{ fontSize: 9.5, color: 'var(--ink-2)', marginTop: 3, lineHeight: 1.4, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
          {entry.modification}
        </div>
      )}
    </div>
  )
}
