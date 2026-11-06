// PageProps.tsx — the Properties column of the page editor (04_PAGES_TOOL §5): the selected
// widget, folder or data collection. ADR 0068: the page knows no flow; a button or a field
// shows, read only, the flows whose InputsPageReader uses it ("Lance par" / "Lu par", from
// GET /flows/pages/{id}/flows), with a link to open each flow.

import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from 'react'
import { ExternalLink, Plus, Trash2 } from 'lucide-react'
import { flowsApi } from '../../api/flows'
import type { FlowListItem, InterfaceInput, InterfaceOutput, PageDataField, PageDataSpec, PageDoc, PageFieldType, PageFolder, PageScope, PageUse, PageWidget } from '../flow_editor/types'
import { useTr } from '../flow_editor/useTr'
import { ID_RE } from './builder'
import { PAGE_ICONS } from './icons'
import { isDataKind, isValueKind } from './links'

export const propInput: CSSProperties = { flex: 1, minWidth: 0, height: 24, padding: '0 6px', border: '1px solid var(--rule-2)', background: 'var(--bg-deep)', borderRadius: 5, fontSize: 12, color: 'var(--ink)' }
const FIELD_TYPES: PageFieldType[] = ['str', 'text', 'int', 'float', 'bool', 'date', 'datetime', 'user', 'select', 'image', 'path']

export function PropRow({ label, children, tip }: { label: string; children: ReactNode; tip?: string }) {
  return (
    <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }} title={tip}>
      <span className="cap" style={{ width: 92, flexShrink: 0 }}>{label}</span>
      {children}
    </label>
  )
}

function Text({ value, onChange, placeholder, mono }: { value: string | undefined; onChange: (v: string) => void; placeholder?: string; mono?: boolean }) {
  return <input value={value ?? ''} placeholder={placeholder} onChange={e => onChange(e.target.value)} style={{ ...propInput, fontFamily: mono ? 'var(--mono)' : undefined }} />
}

function Num({ value, onChange }: { value: number | undefined; onChange: (v: number | undefined) => void }) {
  return <input type="number" value={value ?? ''} onChange={e => onChange(e.target.value === '' ? undefined : Number(e.target.value))} style={propInput} />
}

function Pick<T extends string>({ value, options, onChange, empty }: { value: T | undefined; options: { value: T; label: string }[]; onChange: (v: T | undefined) => void; empty?: string }) {
  return (
    <select value={value ?? ''} onChange={e => onChange((e.target.value || undefined) as T | undefined)} style={propInput}>
      {empty !== undefined && <option value="">{empty}</option>}
      {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  )
}

function Flag({ value, onChange }: { value: boolean | undefined; onChange: (v: boolean) => void }) {
  return <input type="checkbox" checked={!!value} onChange={e => onChange(e.target.checked)} />
}

// Flows a page of *scope* may run (P_SCOPE_MISMATCH): team -> team / shipped; project -> + project.
function allowedFlows(flows: FlowListItem[], scope: PageScope): FlowListItem[] {
  return flows.filter(f => !f.shadowed && !f.legacy && (f.scope === 'team' || f.scope === 'shipped' || (scope === 'project' && f.scope === 'project')))
}

function useFlowInterface(name: string | undefined, project?: string): { inputs: InterfaceInput[]; outputs: InterfaceOutput[] } | null {
  const [iface, setIface] = useState<{ inputs: InterfaceInput[]; outputs: InterfaceOutput[] } | null>(null)
  useEffect(() => {
    if (!name) { setIface(null); return }
    let alive = true
    flowsApi.get(name, { project }).then(r => {
      const raw = r.flow.interface as unknown
      const inputs = Array.isArray(raw) ? raw as InterfaceInput[] : (r.flow.interface?.inputs ?? [])
      if (alive) setIface({ inputs, outputs: Array.isArray(raw) ? [] : (r.flow.interface?.outputs ?? []) })
    }).catch(() => { if (alive) setIface(null) })
    return () => { alive = false }
  }, [name, project])
  return iface
}

function OptionsEditor({ options, onChange }: { options: { value: string; label?: string }[]; onChange: (o: { value: string; label?: string }[]) => void }) {
  const { tr } = useTr()
  return (
    <div style={{ marginBottom: 8 }}>
      <div className="cap" style={{ marginBottom: 4 }}>{tr('Options', 'Options')}</div>
      {options.map((o, k) => (
        <div key={k} style={{ display: 'flex', gap: 4, marginBottom: 3 }}>
          <input value={o.value} placeholder={tr('valeur', 'value')} onChange={e => onChange(options.map((x, j) => j === k ? { ...x, value: e.target.value } : x))} style={{ ...propInput, fontFamily: 'var(--mono)' }} />
          <input value={o.label ?? ''} placeholder={tr('libelle', 'label')} onChange={e => onChange(options.map((x, j) => j === k ? { ...x, label: e.target.value } : x))} style={propInput} />
          <button type="button" className="btn ghost sm" onClick={() => onChange(options.filter((_, j) => j !== k))}><Trash2 size={11} /></button>
        </div>
      ))}
      <button type="button" className="btn ghost sm" onClick={() => onChange([...options, { value: `v${options.length + 1}` }])}><Plus size={11} /> {tr('Option', 'Option')}</button>
    </div>
  )
}

// -- widget -----------------------------------------------------------------------------------

// Flows whose InputsPageReader uses this widget (a linked button or field), read only.
function UsedBy({ w, uses, onOpenFlow }: { w: PageWidget; uses: PageUse[]; onOpenFlow: (flow: string) => void }) {
  const { tr } = useTr()
  const mine = uses.filter(u => (w.kind === 'button' ? u.buttons : u.fields).includes(w.id))
  return (
    <div style={{ marginBottom: 8 }}>
      <div className="cap" style={{ margin: '10px 0 4px' }}>{w.kind === 'button' ? tr('Lance', 'Starts') : tr('Lu par', 'Read by')}</div>
      {mine.length === 0
        ? <div className="tp-note" style={{ color: 'var(--ink-4)' }}>
            {w.kind === 'button'
              ? tr('Aucun flow : dans un flow, pose un InputsPageReader sur cette page et relie ce bouton.',
                   'No flow: in a flow, place an InputsPageReader on this page and link this button.')
              : tr('Aucun flow ne lit ce champ.', 'No flow reads this field.')}
          </div>
        : mine.map(u => (
          <div key={`${u.scope}/${u.flow}`} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}>
            <span className="tag">{u.label}</span>
            <span className="tp-note" style={{ color: u.active ? 'var(--ok)' : 'var(--ink-4)' }}>{u.active ? tr('actif', 'active') : tr('inactif', 'inactive')}</span>
            <span style={{ flex: 1 }} />
            <button type="button" className="btn ghost sm" onClick={() => onOpenFlow(u.flow)}><ExternalLink size={11} /> {tr('Ouvrir', 'Open')}</button>
          </div>
        ))}
    </div>
  )
}

export function WidgetProps({ doc, w, scope, project, flows, uses, onPatch, onRename, onOpenFlow }: {
  doc: PageDoc; w: PageWidget; scope: PageScope; project?: string; flows: FlowListItem[]; uses: PageUse[]
  onPatch: (patch: Partial<PageWidget>, key: string) => void
  onRename: (next: string) => void
  onOpenFlow: (flow: string) => void
}) {
  const { tr } = useTr()
  const [idDraft, setIdDraft] = useState(w.id)
  useEffect(() => setIdDraft(w.id), [w.id])
  const okFlows = useMemo(() => allowedFlows(flows, scope), [flows, scope])
  const flowOptions = okFlows.map(f => ({ value: f.name, label: `${f.label || f.name}${f.active ? '' : tr(' (inactif)', ' (inactive)')}` }))
  const iface = useFlowInterface(w.source?.flow, project)
  const spec = doc.data.find(d => d.id === w.source?.data)
  const fieldOpts = (types?: string[]) => (spec?.fields ?? []).filter(f => !types || types.includes(f.type)).map(f => ({ value: f.id, label: f.label || f.id }))
  const idBad = !ID_RE.test(idDraft)

  return (
    <div>
      <PropRow label="id" tip={tr('Les liens passent par cet id', 'Links go through this id')}>
        <input value={idDraft} onChange={e => setIdDraft(e.target.value)} onBlur={() => { if (!idBad && idDraft !== w.id) onRename(idDraft); else setIdDraft(w.id) }}
               onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
               style={{ ...propInput, fontFamily: 'var(--mono)', borderColor: idBad ? 'var(--err)' : undefined }} />
      </PropRow>
      {w.kind !== 'label' && <PropRow label={tr('Libelle', 'Label')}><Text value={w.label} onChange={v => onPatch({ label: v }, `w:${w.id}:label`)} /></PropRow>}
      <PropRow label={tr('Info-bulle', 'Tooltip')}><Text value={w.tooltip} onChange={v => onPatch({ tooltip: v }, `w:${w.id}:tooltip`)} /></PropRow>
      <PropRow label={tr('Poids', 'Weight')} tip={tr('Largeur relative dans la ligne (1 par defaut)', 'Relative width in the row (1 by default)')}>
        <Num value={w.w} onChange={v => onPatch({ w: v }, `w:${w.id}:w`)} />
      </PropRow>

      {w.kind === 'button' && <>
        <UsedBy w={w} uses={uses} onOpenFlow={onOpenFlow} />
        <PropRow label={tr('Icone', 'Icon')}><Pick value={w.icon} options={Object.keys(PAGE_ICONS).map(k => ({ value: k, label: k }))} empty="" onChange={v => onPatch({ icon: v }, `w:${w.id}:icon`)} /></PropRow>
        <PropRow label={tr('Confirmer', 'Confirm')} tip={tr('Question posee avant de lancer (vide = aucune)', 'Question asked before running (empty = none)')}>
          <Text value={w.confirm} onChange={v => onPatch({ confirm: v }, `w:${w.id}:confirm`)} />
        </PropRow>
      </>}

      {isValueKind(w.kind) && <>
        <UsedBy w={w} uses={uses} onOpenFlow={onOpenFlow} />
        <PropRow label={tr('Defaut', 'Default')}><Text value={w.default === undefined ? '' : String(w.default)} onChange={v => onPatch({ default: v === '' ? undefined : v }, `w:${w.id}:default`)} /></PropRow>
        <PropRow label={tr('Se souvenir', 'Remember')} tip={tr('Garde la derniere saisie de chaque artiste', 'Keeps the last entry of each artist')}>
          <Flag value={w.remember === 'user'} onChange={v => onPatch({ remember: v ? 'user' : undefined }, `w:${w.id}:remember`)} />
        </PropRow>
      </>}

      {(w.kind === 'float' || w.kind === 'int') && <>
        <PropRow label="min"><Num value={w.min} onChange={v => onPatch({ min: v }, `w:${w.id}:min`)} /></PropRow>
        <PropRow label="max"><Num value={w.max} onChange={v => onPatch({ max: v }, `w:${w.id}:max`)} /></PropRow>
        <PropRow label={tr('Pas', 'Step')}><Num value={w.step} onChange={v => onPatch({ step: v }, `w:${w.id}:step`)} /></PropRow>
        {w.kind === 'float' && <PropRow label={tr('Unite', 'Unit')}><Text value={w.unit} onChange={v => onPatch({ unit: v }, `w:${w.id}:unit`)} /></PropRow>}
      </>}
      {w.kind === 'text' && <>
        <PropRow label={tr('Multiligne', 'Multiline')}><Flag value={w.multiline} onChange={v => onPatch({ multiline: v || undefined }, `w:${w.id}:ml`)} /></PropRow>
        <PropRow label={tr('Exemple', 'Placeholder')}><Text value={w.placeholder} onChange={v => onPatch({ placeholder: v }, `w:${w.id}:ph`)} /></PropRow>
      </>}
      {w.kind === 'path' && <>
        <PropRow label={tr('Mode', 'Mode')}><Pick value={w.mode} options={[{ value: 'open', label: tr('ouvrir', 'open') }, { value: 'save', label: tr('enregistrer', 'save') }]} empty="" onChange={v => onPatch({ mode: v }, `w:${w.id}:mode`)} /></PropRow>
        <PropRow label={tr('Extensions', 'Extensions')}><Text value={(w.filters ?? []).join(' ')} placeholder="exr png" onChange={v => onPatch({ filters: v.trim() ? v.trim().split(/[\s,]+/) : undefined }, `w:${w.id}:filters`)} /></PropRow>
      </>}
      {w.kind === 'select' && <OptionsEditor options={w.options ?? []} onChange={o => onPatch({ options: o }, `w:${w.id}:options`)} />}
      {w.kind === 'label' && <PropRow label={tr('Texte', 'Text')}><Text value={w.text} onChange={v => onPatch({ text: v }, `w:${w.id}:text`)} /></PropRow>}

      {isDataKind(w.kind) && w.kind !== 'members' && w.kind !== 'chat' && <>
        <div className="cap" style={{ margin: '10px 0 4px' }}>{tr('Source', 'Source')}</div>
        <PropRow label={tr('Donnees', 'Data')}>
          <Pick value={w.source?.data ?? (w.source?.flow ? '__flow' : undefined)}
                options={[...doc.data.filter(d => (w.kind === 'board') === (d.kind === 'board')).map(d => ({ value: d.id, label: d.label || d.id })),
                          ...(w.kind !== 'board' ? [{ value: '__flow', label: tr('sortie d\'un flow', 'a flow output') }] : [])]}
                empty="" onChange={v => onPatch({ source: v === '__flow' ? { flow: okFlows[0]?.name ?? '', output: '' } : v ? { data: v } : undefined }, `w:${w.id}:source`)} />
        </PropRow>
        {w.source?.flow !== undefined && <>
          <PropRow label={tr('Flow', 'Flow')}><Pick value={w.source.flow || undefined} options={flowOptions} empty="" onChange={v => onPatch({ source: { flow: v ?? '', output: '' } }, `w:${w.id}:sflow`)} /></PropRow>
          <PropRow label={tr('Sortie', 'Output')}><Pick value={w.source.output || undefined} options={(iface?.outputs ?? []).map(o => ({ value: o.id, label: o.label || o.id }))} empty=""
                                                         onChange={v => onPatch({ source: { flow: w.source!.flow, output: v ?? '' } }, `w:${w.id}:sout`)} /></PropRow>
        </>}
        {w.kind === 'feed' && spec && <>
          <PropRow label={tr('Champ texte', 'Text field')}><Pick value={w.field} options={fieldOpts(['str', 'text'])} empty="text" onChange={v => onPatch({ field: v }, `w:${w.id}:field`)} /></PropRow>
          <PropRow label={tr('Canaux', 'Channels')}><Pick value={w.group_by} options={fieldOpts(['str', 'select', 'user'])} empty={tr('(aucun)', '(none)')} onChange={v => onPatch({ group_by: v }, `w:${w.id}:group`)} /></PropRow>
        </>}
        {w.kind === 'cards' && spec && <>
          <PropRow label={tr('Titre', 'Title')}><Pick value={w.title} options={fieldOpts(['str', 'text'])} empty="" onChange={v => onPatch({ title: v }, `w:${w.id}:title`)} /></PropRow>
          <PropRow label={tr('Colonnes par', 'Columns by')}><Pick value={w.group_by} options={fieldOpts(['str', 'select', 'user', 'bool'])} empty={tr('(aucune)', '(none)')} onChange={v => onPatch({ group_by: v }, `w:${w.id}:group`)} /></PropRow>
        </>}
        {w.kind === 'calendar' && spec && <>
          <PropRow label={tr('Date', 'Date')}><Pick value={w.date} options={fieldOpts(['date', 'datetime'])} empty="" onChange={v => onPatch({ date: v }, `w:${w.id}:date`)} /></PropRow>
          <PropRow label={tr('Fin', 'End')}><Pick value={w.end} options={fieldOpts(['date', 'datetime'])} empty={tr('(aucune)', '(none)')} onChange={v => onPatch({ end: v }, `w:${w.id}:end`)} /></PropRow>
          <PropRow label={tr('Titre', 'Title')}><Pick value={w.title} options={fieldOpts(['str', 'text'])} empty="" onChange={v => onPatch({ title: v }, `w:${w.id}:title`)} /></PropRow>
        </>}
        {w.kind === 'table' && spec && (
          <PropRow label={tr('Colonnes', 'Columns')}><Text value={(w.columns ?? []).join(' ')} placeholder={tr('toutes', 'all')} mono
                                                         onChange={v => onPatch({ columns: v.trim() ? v.trim().split(/[\s,]+/) : undefined }, `w:${w.id}:cols`)} /></PropRow>
        )}
        {(w.kind === 'table' || w.kind === 'cards') && <PropRow label={tr('Modifiable', 'Editable')}><Flag value={w.editable} onChange={v => onPatch({ editable: v || undefined }, `w:${w.id}:edit`)} /></PropRow>}
        {(w.kind === 'feed' || w.kind === 'board') && <PropRow label={tr('Hauteur', 'Height')}><Num value={w.height} onChange={v => onPatch({ height: v }, `w:${w.id}:height`)} /></PropRow>}
      </>}
    </div>
  )
}

// -- folder -----------------------------------------------------------------------------------

export function FolderProps({ f, onPatch, onRename }: { f: PageFolder; onPatch: (p: Partial<PageFolder>, key: string) => void; onRename: (next: string) => void }) {
  const { tr } = useTr()
  const [idDraft, setIdDraft] = useState(f.id)
  useEffect(() => setIdDraft(f.id), [f.id])
  return (
    <div>
      <PropRow label="id">
        <input value={idDraft} onChange={e => setIdDraft(e.target.value)} onBlur={() => { if (ID_RE.test(idDraft) && idDraft !== f.id) onRename(idDraft); else setIdDraft(f.id) }}
               style={{ ...propInput, fontFamily: 'var(--mono)' }} />
      </PropRow>
      <PropRow label={tr('Libelle', 'Label')}><Text value={f.label} onChange={v => onPatch({ label: v }, `f:${f.id}:label`)} /></PropRow>
      <PropRow label={tr('Mode', 'Mode')}>
        <Pick value={f.mode ?? 'plain'} onChange={v => onPatch({ mode: v ?? 'plain' }, `f:${f.id}:mode`)}
              options={[{ value: 'plain', label: tr('bloc', 'block') }, { value: 'tabs', label: tr('onglet', 'tab') }, { value: 'collapsible', label: tr('repliable', 'collapsible') }]} />
      </PropRow>
      <div className="tp-note" style={{ color: 'var(--ink-4)' }}>{tr('Des dossiers "onglet" qui se suivent forment une barre d\'onglets.', 'Consecutive "tab" folders form one tab bar.')}</div>
    </div>
  )
}

// -- data collection --------------------------------------------------------------------------

export function DataProps({ spec, scope, onPatch, onRemove }: { spec: PageDataSpec; scope: PageScope; onPatch: (p: Partial<PageDataSpec>, key: string) => void; onRemove: () => void }) {
  const { tr } = useTr()
  const fields = spec.fields ?? []
  const setFields = (next: PageDataField[], key: string) => onPatch({ fields: next }, key)
  return (
    <div>
      <PropRow label="id"><span className="tag" style={{ fontFamily: 'var(--mono)' }}>{spec.id}</span></PropRow>
      <PropRow label={tr('Libelle', 'Label')}><Text value={spec.label} onChange={v => onPatch({ label: v }, `d:${spec.id}:label`)} /></PropRow>
      {scope === 'team' && (
        <PropRow label={tr('Rangement', 'Stored')} tip={tr('Par projet : chaque projet a ses donnees. Equipe : les memes pour tous.', 'Per project: each project has its own data. Team: the same for all.')}>
          <Pick value={spec.per ?? 'project'} onChange={v => onPatch({ per: v ?? 'project' }, `d:${spec.id}:per`)}
                options={[{ value: 'project', label: tr('par projet', 'per project') }, { value: 'team', label: tr('equipe', 'team') }]} />
        </PropRow>
      )}
      <PropRow label={tr('Qui ecrit', 'Who writes')}>
        <Pick value={spec.write ?? 'all'} onChange={v => onPatch({ write: v ?? 'all' }, `d:${spec.id}:write`)}
              options={[{ value: 'all', label: tr('tous les artistes', 'every artist') }, { value: 'team_td', label: 'Team TD' }]} />
      </PropRow>
      {spec.kind === 'board'
        ? <div className="tp-note" style={{ color: 'var(--ink-4)', margin: '6px 0' }}>{tr('Board : champs fixes (cartes, liens, images).', 'Board: fixed fields (cards, links, images).')}</div>
        : <>
          <div className="cap" style={{ margin: '10px 0 4px' }}>{tr('Champs', 'Fields')}</div>
          {fields.map((f, k) => (
            <div key={k} style={{ display: 'flex', gap: 4, marginBottom: 3, alignItems: 'center' }}>
              <input value={f.id} onChange={e => setFields(fields.map((x, j) => j === k ? { ...x, id: e.target.value } : x), `d:${spec.id}:f${k}:id`)}
                     style={{ ...propInput, fontFamily: 'var(--mono)', borderColor: ID_RE.test(f.id) ? undefined : 'var(--err)' }} />
              <select value={f.type} style={{ ...propInput, flex: '0 0 82px' }}
                      onChange={e => { const type = e.target.value as PageFieldType; setFields(fields.map((x, j) => j === k ? { ...x, type, options: type === 'select' ? (x.options ?? [{ value: 'a' }]) : undefined } : x), `d:${spec.id}:f${k}:type`) }}>
                {FIELD_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
              </select>
              <input type="checkbox" title={tr('Obligatoire', 'Required')} checked={!!f.required} onChange={e => setFields(fields.map((x, j) => j === k ? { ...x, required: e.target.checked || undefined } : x), `d:${spec.id}:f${k}:req`)} />
              <button type="button" className="btn ghost sm" onClick={() => setFields(fields.filter((_, j) => j !== k), `d:${spec.id}:rm${k}`)}><Trash2 size={11} /></button>
            </div>
          ))}
          {fields.filter(f => f.type === 'select').map(f => (
            <div key={`o-${f.id}`}>
              <div className="cap" style={{ marginTop: 6 }}>{f.id}</div>
              <OptionsEditor options={f.options ?? []} onChange={o => setFields(fields.map(x => x === f ? { ...x, options: o } : x), `d:${spec.id}:${f.id}:opts`)} />
            </div>
          ))}
          <button type="button" className="btn ghost sm" onClick={() => setFields([...fields, { id: `champ_${fields.length + 1}`, type: 'str' }], `d:${spec.id}:add`)}><Plus size={11} /> {tr('Champ', 'Field')}</button>
        </>}
      <div style={{ marginTop: 14 }}>
        <button type="button" className="btn ghost sm" onClick={onRemove} style={{ color: 'var(--err)' }}><Trash2 size={11} /> {tr('Retirer la collection', 'Remove the collection')}</button>
        <div className="tp-note" style={{ color: 'var(--ink-4)', marginTop: 4 }}>{tr('Les donnees deja ecrites restent sur le disque.', 'Data already written stays on disk.')}</div>
      </div>
    </div>
  )
}
