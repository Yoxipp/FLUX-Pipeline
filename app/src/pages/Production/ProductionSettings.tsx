import { useState } from 'react'
import { Menu, Plus, X } from 'lucide-react'
import type { ProductionDepartment, ProductionState } from '../../types'
import { moveDepartment, STATUS_TOKENS, trackingDepartments } from './tracking'

interface Props {
  state: ProductionState
  mode: 'asset' | 'shot'
  setState: (patch: (prev: ProductionState) => ProductionState) => void
}

export function ProductionSettings({ state, mode, setState }: Props) {
  const [draft, setDraft] = useState(() => trackingDepartments(state, mode).map(d => ({ ...d, task_tokens: [...d.task_tokens], statuses: [...d.statuses], depends_on: [...d.depends_on] })))
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  const [dragged, setDragged] = useState('')
  const patch = (id: string, value: Partial<ProductionDepartment>) => { setSaved(false); setDraft(prev => prev.map(d => d.id === id ? { ...d, ...value } : d)) }
  const save = () => {
    if (draft.some(d => !d.name.trim() || !d.task_tokens.length || !d.statuses.length)) { setError('Chaque département doit avoir un nom, des tokens et des statuts.'); return }
    const visiting = new Set<string>(), visited = new Set<string>()
    const cycle = (id: string): boolean => {
      if (visiting.has(id)) return true
      if (visited.has(id)) return false
      visiting.add(id)
      if ((draft.find(d => d.id === id)?.depends_on ?? []).some(cycle)) return true
      visiting.delete(id); visited.add(id); return false
    }
    if (draft.some(d => cycle(d.id))) { setError('Les dépendances forment un cycle.'); return }
    const departments = draft.map(d => ({ ...d, active: true, fixed: Boolean(d.fixed), name: d.name.trim(), statuses: [...new Set(d.statuses)], task_tokens: [...new Set(d.task_tokens)] }))
    setState(prev => ({ ...prev, tracking: { ...prev.tracking, departments: [...trackingDepartments(prev, mode === 'shot' ? 'asset' : 'shot'), ...departments] } }))
    setError(''); setSaved(true)
  }
  return <div className="production-tracking production-settings-page">
    <div className="tracking-settings-heading"><h2>Settings · {mode === 'shot' ? 'Shots' : 'Assets'}</h2><button onClick={save}>Enregistrer</button></div>
    <p>Fixe : TODO par défaut. Optionnel : vide jusqu’à la première review. Glissez les trois barres pour réordonner les colonnes.</p>
    <p>Ajouter ou supprimer un département ici ne crée ni ne supprime de dossier sur disque. Ses tâches et reviews sont conservées.</p>
    <div className="tracking-config-list"><div className="tracking-config-row tracking-config-labels"><span /><span>Département</span><span>Mode</span><span>Tokens de tâche</span><span>Statuts</span><span>Dépendances</span><span /></div>
      {draft.map((d, index) => <div key={d.id} className="tracking-config-row" data-department={d.id} onDragOver={e => { if (dragged) e.preventDefault() }} onDrop={e => { e.preventDefault(); setDraft(prev => moveDepartment(prev, dragged, d.id)); setDragged(''); setSaved(false) }}>
        <button className="tracking-department-grip" draggable aria-label={`Déplacer ${d.name}`} title="Glisser pour changer l’ordre · Alt + flèches" onDragStart={e => { setDragged(d.id); e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', d.id) }} onDragEnd={() => setDragged('')} onKeyDown={e => {
          if (!e.altKey || !['ArrowUp', 'ArrowDown'].includes(e.key)) return
          e.preventDefault(); const target = draft[index + (e.key === 'ArrowUp' ? -1 : 1)]
          if (target) { setDraft(prev => moveDepartment(prev, d.id, target.id)); setSaved(false) }
        }}><Menu size={16} /></button>
        <input aria-label={`Nom ${d.name}`} value={d.name} onChange={e => patch(d.id, { name: e.target.value })} />
        <select aria-label={`Mode ${d.name}`} value={d.fixed ? 'fixed' : 'optional'} onChange={e => patch(d.id, { fixed: e.target.value === 'fixed' })}><option value="fixed">Fixe</option><option value="optional">Optionnel</option></select>
        <input aria-label={`Tokens ${d.name}`} defaultValue={d.task_tokens.join(', ')} placeholder="ANIM, ANIMATION" onBlur={e => patch(d.id, { task_tokens: e.target.value.split(',').map(s => s.trim().toUpperCase()).filter(Boolean) })} />
        <input aria-label={`Statuts ${d.name}`} defaultValue={d.statuses.join(', ')} onBlur={e => patch(d.id, { statuses: e.target.value.split(',').map(s => s.trim().toUpperCase()).filter(Boolean) })} />
        <details><summary>Dépend de ({d.depends_on.length})</summary>{draft.filter(x => x.id !== d.id).map(x => <label key={x.id}><input type="checkbox" checked={d.depends_on.includes(x.id)} onChange={e => patch(d.id, { depends_on: e.target.checked ? [...d.depends_on, x.id] : d.depends_on.filter(id => id !== x.id) })} />{x.name}</label>)}</details>
        <button aria-label={`Supprimer ${d.name}`} onClick={() => { setDraft(prev => prev.filter(x => x.id !== d.id).map(x => ({ ...x, depends_on: x.depends_on.filter(id => id !== d.id) }))); setSaved(false) }}><X size={13} /></button>
      </div>)}
    </div>
    <div className="tracking-settings-actions"><button onClick={() => { setDraft(prev => [...prev, { id: `${mode}:${crypto.randomUUID()}`, name: 'Département', scope: mode, task_tokens: [], statuses: [...STATUS_TOKENS], depends_on: [], active: true, fixed: false }]); setSaved(false) }}><Plus size={13} />Département</button>{saved && <span role="status">Settings enregistrés.</span>}{error && <span role="alert">{error}</span>}</div>
  </div>
}
