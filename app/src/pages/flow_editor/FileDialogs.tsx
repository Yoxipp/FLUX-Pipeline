// FileDialogs.tsx — dialogs of the File menu (ADR 0058): Nouveau / Enregistrer sous (name +
// category) and "Migrer les actions v1" (report of a dry run before anything is written).

import { useEffect, useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { Btn } from '../../components/shared/ui'
import type { FlowRights, FlowScope, MigrateReport } from './types'
import { useTr } from './useTr'

const NAME_RE = /^[a-z][a-z0-9_]{1,40}$/

export interface ScopeChoice { scope: FlowScope; label: string; disabled?: string }

// Writable scopes, greyed with the reason when a box or the project is missing.
export function scopeChoices(rights: FlowRights | null | undefined, project: string, tr: (fr: string, en: string) => string): ScopeChoice[] {
  const noBox = (scope: FlowScope) => rights?.can[scope]?.write ? undefined
    : scope === 'perso' ? tr('Case TD requise', 'TD box required') : tr('Case Team TD requise', 'Team TD box required')
  return [
    { scope: 'perso', label: tr('Perso', 'Personal'), disabled: noBox('perso') },
    { scope: 'team', label: tr('Pipe (equipe)', 'Pipe (team)'), disabled: noBox('team') },
    { scope: 'project', label: project ? tr(`Projet ${project}`, `Project ${project}`) : tr('Projet', 'Project'),
      disabled: project ? noBox('project') : tr('Aucun projet actif', 'No active project') },
  ]
}

export function NameDialog({ open, title, initialName, choices, initialScope, onClose, onConfirm }: {
  open: boolean
  title: string
  initialName: string
  choices: ScopeChoice[]
  initialScope?: FlowScope
  onClose: () => void
  onConfirm: (name: string, scope: FlowScope) => void
}) {
  const { tr } = useTr()
  const firstOk = choices.find(c => !c.disabled)?.scope
  const [name, setName] = useState(initialName)
  const [scope, setScope] = useState<FlowScope | undefined>(initialScope ?? firstOk)
  useEffect(() => {
    if (!open) return
    setName(initialName)
    const wanted = choices.find(c => c.scope === initialScope && !c.disabled)
    setScope(wanted ? wanted.scope : firstOk)
  }, [open])  // eslint-disable-line react-hooks/exhaustive-deps
  const valid = NAME_RE.test(name)
  const submit = () => { if (valid && scope) onConfirm(name, scope) }
  return (
    <Dialog.Root open={open} onOpenChange={o => { if (!o) onClose() }}>
      <Dialog.Portal>
        <Dialog.Overlay className="flow-dialog-overlay" />
        <Dialog.Content className="flow-dialog" aria-describedby={undefined}>
          <div className="flow-dialog-heading">
            <Dialog.Title>{title}</Dialog.Title>
            <Dialog.Close aria-label={tr('Fermer', 'Close')}><X size={15} /></Dialog.Close>
          </div>
          <label className="flow-dialog-label">{tr('Nom', 'Name')}</label>
          <input
            autoFocus value={name} onChange={e => setName(e.target.value.toLowerCase())}
            onKeyDown={e => { if (e.key === 'Enter') submit() }}
            className="flow-dialog-input"
          />
          <div className="flow-dialog-hint" style={{ color: valid || !name ? 'var(--ink-4)' : 'var(--err)' }}>
            {tr('Minuscules, chiffres et _ (2 a 41 caracteres, commence par une lettre).',
                'Lowercase, digits and _ (2 to 41 characters, starts with a letter).')}
          </div>
          <label className="flow-dialog-label">{tr('Categorie', 'Category')}</label>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {choices.map(c => (
              <label key={c.scope} title={c.disabled} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12,
                color: c.disabled ? 'var(--ink-4)' : 'var(--ink-2)', cursor: c.disabled ? 'default' : 'pointer' }}>
                <input type="radio" name="flow-scope" disabled={!!c.disabled} checked={scope === c.scope}
                  onChange={() => setScope(c.scope)} style={{ accentColor: 'var(--accent)', margin: 0 }} />
                {c.label}{c.disabled && <span style={{ fontSize: 11 }}> · {c.disabled}</span>}
              </label>
            ))}
          </div>
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 14 }}>
            <Btn sm ghost onClick={onClose}>{tr('Annuler', 'Cancel')}</Btn>
            <Btn sm primary disabled={!valid || !scope} onClick={submit}>{tr('Creer', 'Create')}</Btn>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

const STATUS: Record<string, [string, string]> = {
  would_write: ['a ecrire', 'to write'], written: ['ecrit', 'written'], unchanged: ['deja migre', 'already migrated'],
  exists: ['existe (modifie, garde)', 'exists (edited, kept)'], failed: ['echec', 'failed'],
  copied: ['copie', 'copied'], conflict: ['different, garde', 'differs, kept'],
}

export function MigrateDialog({ report, busy, onClose, onConfirm }: {
  report: MigrateReport | null
  busy: boolean
  onClose: () => void
  onConfirm: () => void
}) {
  const { tr } = useTr()
  const st = (s: string) => { const t = STATUS[s]; return t ? tr(t[0], t[1]) : s }
  const toWrite = (report?.actions ?? []).filter(a => a.status === 'would_write').length
    + (report?.nodes ?? []).filter(n => n.status === 'copied').length
  return (
    <Dialog.Root open={!!report} onOpenChange={o => { if (!o) onClose() }}>
      <Dialog.Portal>
        <Dialog.Overlay className="flow-dialog-overlay" />
        <Dialog.Content className="flow-dialog" style={{ width: 520 }} aria-describedby={undefined}>
          <div className="flow-dialog-heading">
            <Dialog.Title>{report?.dry_run ? tr('Migrer les actions v1', 'Migrate v1 actions') : tr('Migration faite', 'Migration done')}</Dialog.Title>
            <Dialog.Close aria-label={tr('Fermer', 'Close')}><X size={15} /></Dialog.Close>
          </div>
          <div className="flow-dialog-hint">
            {tr('Actions de CONFIG/actions vers des flows d\'equipe inactifs (v001). Les originaux ne sont jamais modifies ; le publish tourne encore sur v1.',
                'CONFIG/actions to inactive team flows (v001). Originals are never changed; publish still runs on v1.')}
          </div>
          <div style={{ maxHeight: 300, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 3, margin: '10px 0' }}>
            {(report?.actions ?? []).length === 0 && <div style={{ fontSize: 12, color: 'var(--ink-3)' }}>{tr('Aucune action d\'equipe.', 'No team action.')}</div>}
            {(report?.actions ?? []).map(a => (
              <div key={a.action} style={{ fontSize: 12, display: 'flex', gap: 8 }}>
                <span style={{ fontFamily: 'var(--mono)', color: 'var(--ink)' }}>{a.action}</span>
                <span style={{ color: 'var(--ink-4)' }}>→ {a.flow}</span>
                <span style={{ marginLeft: 'auto', color: a.status === 'failed' ? 'var(--err)' : 'var(--ink-3)' }}>
                  {st(a.status)}{a.error ? ` : ${a.error}` : ''}
                </span>
              </div>
            ))}
            {(report?.nodes ?? []).map(n => (
              <div key={n.file} style={{ fontSize: 12, display: 'flex', gap: 8 }}>
                <span style={{ fontFamily: 'var(--mono)', color: 'var(--ink-2)' }}>nodes/{n.file}</span>
                <span style={{ marginLeft: 'auto', color: 'var(--ink-3)' }}>{st(n.status)}</span>
              </div>
            ))}
          </div>
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
            <Btn sm ghost onClick={onClose}>{report?.dry_run ? tr('Annuler', 'Cancel') : tr('Fermer', 'Close')}</Btn>
            {report?.dry_run && (
              <Btn sm primary disabled={busy || toWrite === 0} onClick={onConfirm}>
                {tr(`Migrer (${toWrite})`, `Migrate (${toWrite})`)}
              </Btn>
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
