// FileLog — raw modif_logs.json entries about the selected file, plus the
// folder's whole log as a fallback. Complements PublishNote (which is a nice
// summary of *published* files only): FileLog surfaces the JSON log for any
// clicked file so nothing hides in the folder.

import { useEffect, useState } from 'react'
import { ChevronDown, ChevronRight, FileJson } from 'lucide-react'
import { api } from '../../api/client'

type Entry = Record<string, unknown>

export function FileLog({ project, relPath }: { project: string; relPath: string }) {
  const [matched, setMatched]     = useState<Entry[]>([])
  const [folderLog, setFolderLog] = useState<Entry[]>([])
  const [openMatched, setOpenMatched] = useState(true)
  const [openFolder, setOpenFolder]   = useState(false)

  useEffect(() => {
    let alive = true
    setMatched([]); setFolderLog([])
    if (!project || !relPath) return
    api.getFileLog(project, relPath)
      .then(r => { if (alive) { setMatched(r.matched); setFolderLog(r.folder_log) } })
      .catch(() => { /* no log: panel stays hidden */ })
    return () => { alive = false }
  }, [project, relPath])

  if (matched.length === 0 && folderLog.length === 0) return null

  return (
    <div style={{ padding: '10px 12px', borderTop: '1px solid var(--rule)',
                  flexShrink: 0, maxHeight: 320, overflowY: 'auto' }}>
      <div className="cap" style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
        <FileJson size={10} strokeWidth={2} color="var(--ink-3)" />
        LOG JSON
      </div>

      {matched.length > 0 && (
        <Section
          title={`Entrées pour ce fichier (${matched.length})`}
          open={openMatched}
          onToggle={() => setOpenMatched(o => !o)}
        >
          {matched.map((e, i) => <JsonBlock key={`m-${i}`} data={e} />)}
        </Section>
      )}

      {folderLog.length > 0 && (
        <Section
          title={`Log complet du dossier (${folderLog.length})`}
          open={openFolder}
          onToggle={() => setOpenFolder(o => !o)}
        >
          {folderLog.map((e, i) => <JsonBlock key={`f-${i}`} data={e} />)}
        </Section>
      )}
    </div>
  )
}

function Section({ title, open, onToggle, children }: {
  title: string; open: boolean; onToggle: () => void; children: React.ReactNode
}) {
  return (
    <div style={{ marginTop: 6 }}>
      <div
        onClick={onToggle}
        style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer',
                 fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink-3)',
                 textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}
      >
        {open ? <ChevronDown size={10} strokeWidth={2} /> : <ChevronRight size={10} strokeWidth={2} />}
        {title}
      </div>
      {open && children}
    </div>
  )
}

function JsonBlock({ data }: { data: Entry }) {
  return (
    <pre style={{
      margin: '3px 0', padding: '5px 7px', borderRadius: 4,
      border: '1px solid var(--rule-2)', background: 'var(--paper-2)',
      fontFamily: 'var(--code)', fontSize: 10.5, lineHeight: 1.4,
      color: 'var(--ink-2)', whiteSpace: 'pre-wrap', wordBreak: 'break-word',
    }}>
      {JSON.stringify(data, null, 2)}
    </pre>
  )
}
