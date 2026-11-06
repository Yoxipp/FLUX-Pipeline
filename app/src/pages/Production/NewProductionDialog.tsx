import { useEffect, useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { api } from '../../api/client'
import { useI18n } from '../../i18n'
import type { ProductionState } from '../../types'
import type { Selection } from './Production'
import { createShotBatch } from './taskActions'
import { CATEGORY_ORDER, categoryLabelKey } from './util'
import type { CreateKind } from './CreateMenu'

interface Props {
  project: string; mode: 'asset' | 'shot'; state: ProductionState
  setState: (patch: (prev: ProductionState) => ProductionState) => void
  selection: Selection; setSelection: (selection: Selection) => void; onClose: () => void
  initialKind?: CreateKind   // chosen in the Create menu (retake 05)
}

const KIND_LABEL: Record<string, string> = { shot: 'Shot', seq: 'Séquence', asset: 'Asset', group: 'Groupe' }

export function NewProductionDialog({ project, mode, state, setState, selection, setSelection, onClose, initialKind }: Props) {
  const [kind, setKind] = useState<string>(initialKind && !(initialKind === 'shot' && !state.sequences.length)
    ? initialKind : mode === 'shot' ? state.sequences.length ? 'shot' : 'seq' : 'asset')
  const [seqId, setSeqId] = useState(selection.kind === 'seq' ? selection.id : selection.kind === 'shot' ? state.shots.find(s => s.id === selection.id)?.seq_id ?? '' : state.sequences[0]?.id ?? '')
  const [category, setCategory] = useState('CHAR')
  const [categories, setCategories] = useState<string[]>([...CATEGORY_ORDER])
  const { t } = useI18n()
  const [name, setName] = useState('')
  const [main, setMain] = useState('')
  const [secondary, setSecondary] = useState('')
  const [label, setLabel] = useState('')
  const [count, setCount] = useState(1)
  const [error, setError] = useState('')
  useEffect(() => { void api.getTokens(project).then(r => {
    // FXRIG is no longer created from Production (2026-11-06). Known classes first, in display order.
    const rank = (c: string) => { const i = (CATEGORY_ORDER as readonly string[]).indexOf(c); return i < 0 ? CATEGORY_ORDER.length : i }
    const classes = Object.entries(r.tokens.CLASS ?? {}).filter(([token, path]) => token !== 'FXRIG' && !path.includes('{seq}') && !path.includes('{shot}')).map(([token]) => token).sort((a, b) => rank(a) - rank(b))
    if (classes.length) { setCategories(classes); setCategory(classes.includes('CHAR') ? 'CHAR' : classes[0]) }
  }).catch(() => {}) }, [project])
  const create = () => {
    const id = () => `${kind}_${crypto.randomUUID()}`
    try {
      let next = state, selected: Selection = { kind: 'none' }
      if (kind === 'shot') {
        next = createShotBatch(state, seqId, count, main, secondary, label, id)
        selected = { kind: 'shot', id: next.shots.find(s => !state.shots.some(old => old.id === s.id))!.id }
      } else if (kind === 'seq') {
        const nums = state.sequences.map(s => Number(s.name.replace(/^SEQ/i, ''))).filter(Number.isFinite)
        const n = (main ? Number(main) * 10 : (Math.floor(Math.max(0, ...nums) / 10) + 1) * 10) + Number(secondary || 0)
        if (n <= 0 || n > 9999) throw new Error('Numéro de séquence invalide.')
        const seqName = `SEQ${String(n).padStart(4, '0')}`
        if (state.sequences.some(s => s.name === seqName)) throw new Error('Cette séquence existe déjà.')
        const newId = id()
        next = { ...state, sequences: [...state.sequences, { id: newId, name: seqName, label: label.trim() || undefined, order: state.sequences.length, tasks: [], assets: [], task_details: {}, origin: 'user' }] }
        selected = { kind: 'seq', id: newId }
      } else {
        const token = name.trim().toUpperCase()
        if (!/^[A-Z0-9_]+$/.test(token)) throw new Error('Utilisez un nom composé de lettres, chiffres ou underscores.')
        const newId = id()
        if (kind === 'asset') {
          if (state.assets.some(a => a.class === category && a.name === token)) throw new Error('Cet asset existe déjà.')
          next = { ...state, assets: [...state.assets, { id: newId, class: category, name: token, group_id: null, order: state.assets.length, tasks: [], task_details: {}, origin: 'user' }] }
          selected = { kind: 'asset', id: newId }
        } else {
          if (state.asset_groups.some(g => g.class === category && g.name === token)) throw new Error('Ce groupe existe déjà.')
          next = { ...state, asset_groups: [...state.asset_groups, { id: newId, class: category, name: token, order: state.asset_groups.length }] }
          selected = { kind: 'group', id: newId }
        }
      }
      // The modal is synchronous; validation completes before the store is updated.
      setState(() => next); setSelection(selected); onClose()
    } catch (e) { setError(e instanceof Error ? e.message : 'Création impossible') }
  }
  return <Dialog.Root open onOpenChange={open => { if (!open) onClose() }}><Dialog.Portal>
    <Dialog.Overlay className="production-dialog-overlay" /><Dialog.Content className="production-dialog">
      <div className="production-dialog-heading"><Dialog.Title>Create · {KIND_LABEL[kind] ?? kind}</Dialog.Title><Dialog.Close aria-label="Fermer"><X size={16} /></Dialog.Close></div>
      <Dialog.Description>Créer dans {project}</Dialog.Description>
      <form onSubmit={e => { e.preventDefault(); create() }} className="production-create-form">
        <label>Type<select value={kind} onChange={e => { setKind(e.target.value); setError('') }}>{mode === 'shot' ? <><option value="shot">Shot</option><option value="seq">Séquence</option></> : <><option value="asset">Asset</option><option value="group">Groupe</option></>}</select></label>
        {mode === 'asset' ? <><label>Catégorie<select value={category} onChange={e => setCategory(e.target.value)}>{categories.map(c => <option key={c} value={c}>{categoryLabelKey(c) ? t(categoryLabelKey(c)) : c}</option>)}</select></label><label>Nom<input autoFocus value={name} onChange={e => setName(e.target.value)} placeholder="HERO" required /></label></> : <>
          {kind === 'shot' && <><label>Séquence<select required value={seqId} onChange={e => setSeqId(e.target.value)}><option value="">Choisir une séquence</option>{state.sequences.map(s => <option key={s.id} value={s.id} disabled={Boolean(s.locked)}>{s.name}{s.label ? ` · ${s.label}` : ''}{s.locked ? ' · verrouillée' : ''}</option>)}</select></label><label>Nombre de shots<input type="number" min={1} max={1000} required value={count} onChange={e => setCount(Number(e.target.value))} /></label></>}
          <div className="production-number-fields"><label>Numéro principal<input inputMode="numeric" pattern="[0-9]{0,3}" maxLength={3} value={main} onChange={e => setMain(e.target.value.replace(/\D/g, ''))} placeholder="Auto" /></label><label>Secondaire<input inputMode="numeric" pattern="[0-9]?" maxLength={1} value={secondary} onChange={e => setSecondary(e.target.value.replace(/\D/g, ''))} placeholder="0" /></label></div>
          <p className="tracking-muted">1 + 0 → 0010. Les shots suivants avancent par pas de 10.</p><label>Libellé<input value={label} onChange={e => setLabel(e.target.value)} placeholder="Optionnel" /></label>
        </>}
        {error && <p role="alert">{error}</p>}<div className="production-dialog-actions"><Dialog.Close>Annuler</Dialog.Close><button type="submit">{kind === 'shot' && count > 1 ? `Créer ${count} shots` : 'Créer'}</button></div>
      </form>
    </Dialog.Content>
  </Dialog.Portal></Dialog.Root>
}
