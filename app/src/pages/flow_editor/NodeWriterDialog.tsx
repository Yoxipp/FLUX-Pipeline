// NodeWriterDialog.tsx — write a team Python node (03_EDITEUR §9), taken from the old
// editor's NodeWriter (ActionGraph.tsx): starts from GET /flows/nodes/template, saved by
// POST /flows/nodes into CONFIG/extensions/nodes/<name>.py (Team TD, shared with the team,
// reloaded per file without a restart). A load error is shown and the file is kept.

import { useEffect, useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { toast } from 'sonner'
import { flowsApi } from '../../api/flows'
import { Btn } from '../../components/shared/ui'
import { useTr } from './useTr'

const NAME_RE = /^[a-z][a-z0-9_]{1,40}$/

export function NodeWriterDialog({ open, onClose, onSaved }: { open: boolean; onClose: () => void; onSaved: () => void }) {
  const { tr } = useTr()
  const [name, setName] = useState('mon_node')
  const [code, setCode] = useState('')
  const [folder, setFolder] = useState<string | null>(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open) return
    setErr('')
    flowsApi.nodeTemplate().then(t => { setCode(c => c || t.text); setFolder(t.folder) }).catch(e => setErr(String(e?.message ?? e)))
  }, [open])

  const valid = NAME_RE.test(name)
  const save = () => {
    if (!valid) return
    setBusy(true)
    setErr('')
    flowsApi.saveTeamNode(name, code)
      .then(r => {
        if (r.error) { setErr(r.error); onSaved(); return }
        toast.success(tr(`Node ${name} enregistre (equipe)`, `Node ${name} saved (team)`))
        onSaved()
        onClose()
      })
      .catch(e => setErr(String(e?.message ?? e)))
      .finally(() => setBusy(false))
  }

  return (
    <Dialog.Root open={open} onOpenChange={o => { if (!o) onClose() }}>
      <Dialog.Portal>
        <Dialog.Overlay className="flow-dialog-overlay" />
        <Dialog.Content className="flow-dialog" aria-describedby={undefined} style={{ width: 760, top: '8%' }}>
          <div className="flow-dialog-heading">
            <Dialog.Title>{tr('Nouveau node Python (equipe)', 'New Python node (team)')}</Dialog.Title>
            <Dialog.Close aria-label={tr('Fermer', 'Close')}><X size={15} /></Dialog.Close>
          </div>
          <label className="flow-dialog-label">{tr('Nom du fichier', 'File name')}</label>
          <input value={name} onChange={e => setName(e.target.value.toLowerCase())} className="flow-dialog-input" />
          <div className="flow-dialog-hint">
            {folder ? `${folder}\\${name}.py` : `CONFIG/extensions/nodes/${name}.py`}
            {' · '}{tr('partage avec l\'equipe, recharge sans redemarrer', 'shared with the team, reloaded without a restart')}
          </div>
          <textarea value={code} onChange={e => setCode(e.target.value)} spellCheck={false} rows={22}
                    style={{ marginTop: 6, fontFamily: 'var(--mono)', fontSize: 11, background: 'var(--paper-2)', color: 'var(--ink)', border: '1px solid var(--rule-2)', borderRadius: 6, padding: 8, resize: 'vertical' }} />
          {err && <div style={{ fontSize: 11.5, color: 'var(--err)', whiteSpace: 'pre-wrap' }}>{err}</div>}
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 6, marginTop: 6 }}>
            <Btn sm ghost onClick={onClose}>{tr('Annuler', 'Cancel')}</Btn>
            <Btn sm primary disabled={!valid || busy} onClick={save}>{tr('Enregistrer', 'Save')}</Btn>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
