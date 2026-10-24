// ParamsPane.tsx — right panel (03_EDITEUR §1): the parameters of the selected node only
// (2026-10-22: doc and infos moved to the node hover toolbar). Nothing selected: the flow.
// P4: editable through the store (one undo entry per field, typing coalesced): label,
// bypass, every input / param of the spec with a ParamWidget by port type. A linked input
// shows its source, read-only. Nodes without a spec (legacy v1, unknown type) stay read-only.
// The flow part (interface, variables) is FlowSettings (FlowParams.tsx).
// 2026-10-23: the pane is resizable (drag its left edge, width remembered per viewer in
// localStorage); a param with choices is a menu in catalogue order (data.value type falls
// back to a local list until the catalogue sends choices); constant params (wirable false,
// node.constants) are listed with the inputs in spec order; a param with tokens is a
// TokenField (project token menu + free text). R1: params hidden by the node's mode (Port.when,
// visibility.ts) are left out; a linked one stays, greyed.
// ADR 0068: an InputsPageReader offers the TOOL pages as its page menu and copies the
// buttons and fields of the chosen page into its ports.

import { useCallback, useEffect, useRef, useState, type PointerEvent, type ReactNode } from 'react'
import { toast } from 'sonner'
import { flowsApi } from '../../api/flows'
import { ParamWidget, type ParamKind } from '../../components/shared/ParamWidget'
import { useProject } from '../../ProjectContext'
import { FAMILY_INFO } from './families'
import { Tooltip, TooltipContent, TooltipTrigger } from '../../components/shared/ui'
import { PortHelp } from './nodes/PortTooltip'
import { portColor } from './portTypes'
import { TokenField, tokenKeys, useProjectTokens, type ProjectTokens } from './TokenField'
import { portVisible } from './visibility'
import type { FlowViewNode, InterfaceInput, PageDoc, PageWidget, PageWidgetKind, PortSpec } from './types'
import { formatValue, useTr } from './useTr'

export const PARAMS_W = 320          // default width; the viewer can drag it
const PARAMS_MIN = 260
const PARAMS_MAX = 900
const WIDTH_KEY = 'flux.flows.paramsWidth'

const maxWidth = () => Math.max(PARAMS_MIN, Math.min(PARAMS_MAX, Math.round(window.innerWidth * 0.7)))
const clampWidth = (w: number) => Math.min(maxWidth(), Math.max(PARAMS_MIN, Math.round(w)))

function readWidth(): number {
  try {
    const n = Number(localStorage.getItem(WIDTH_KEY))
    return Number.isFinite(n) && n > 0 ? clampWidth(n) : PARAMS_W
  } catch { return PARAMS_W }
}

// Choices sent by an older catalogue that does not have them yet (backend VALUE_TYPES).
const FALLBACK_CHOICES: Record<string, Record<string, unknown[]>> = {
  'data.value': { type: ['str', 'int', 'float', 'bool', 'list', 'dict', 'pattern'] },
}

export function kindOf(type: string): ParamKind {
  if (type === 'bool' || type === 'int' || type === 'float' || type === 'path' || type === 'dir') return type
  if (type.startsWith('list[')) return 'list'
  if (type === 'dict') return 'text'
  return 'str'
}

// Widget value -> stored value: numbers parsed, empty = unset (the default applies).
export function storedValue(type: string, raw: unknown): unknown {
  if (raw === '' || (Array.isArray(raw) && raw.length === 0)) return undefined
  if ((type === 'int' || type === 'float') && typeof raw === 'string') {
    const n = Number(raw)
    return Number.isFinite(n) ? (type === 'int' ? Math.trunc(n) : n) : raw
  }
  if (type === 'dict' && typeof raw === 'string') {
    try { return JSON.parse(raw) } catch { return raw }
  }
  return raw
}

// Hovering a label shows what the param is for (registry doc, values, default, example; R1).
function Label({ p }: { p: PortSpec }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11.5, color: 'var(--ink-2)', minWidth: 0, cursor: 'help' }}>
          <span style={{ width: 7, height: 7, borderRadius: 2, background: portColor(p.type), flexShrink: 0 }} />
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', borderBottom: '1px dotted var(--rule-3)' }}>{p.name}</span>
          {p.required && <span style={{ color: 'var(--accent)' }}>*</span>}
        </span>
      </TooltipTrigger>
      <TooltipContent side="left" style={{ maxWidth: 320 }}><PortHelp port={p} /></TooltipContent>
    </Tooltip>
  )
}

export function Row({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '110px 1fr', columnGap: 8, alignItems: 'center', padding: '4px 0', borderBottom: '1px solid var(--rule)' }}>
      {label}
      <div style={{ display: 'flex', minWidth: 0 }}>{children}</div>
    </div>
  )
}

function ParamRow({ p, editable, raw, onChange, choices, tokens, tokenOptions, muted }: {
  p: PortSpec; editable: boolean; raw: unknown; onChange: (v: unknown) => void
  choices?: unknown[]            // menu, in this order
  tokens: ProjectTokens | null   // project tokens, null = no project (or not loaded)
  tokenOptions: string[]         // keys offered for p.tokens
  muted: boolean                 // unused by the node's current mode
}) {
  const { tr, lang } = useTr()
  const doc = lang === 'en' ? p.doc_en || p.doc_fr : p.doc_fr || p.doc_en
  const tip = muted ? `${doc ?? ''}${doc ? ' ' : ''}${tr('(inutilise dans ce mode)', '(unused in this mode)')}` : doc
  const row = (child: ReactNode) => (
    <div style={muted ? { opacity: 0.45 } : undefined}><Row label={<Label p={p} />}>{child}</Row></div>
  )
  if (p.wiredFrom || !editable) {
    const value = p.wiredFrom ? `<- ${p.wiredFrom}` : formatValue(p.value, 400)
    return row(
      <span style={{
        flex: 1, fontSize: 11.5, padding: '3px 6px', borderRadius: 4, minHeight: 22, wordBreak: 'break-all',
        background: p.wiredFrom ? 'transparent' : 'var(--paper-2)', border: '1px solid var(--rule-2)',
        color: p.wiredFrom ? 'var(--ink-4)' : 'var(--ink)',
      }}>
        {value || <span style={{ color: 'var(--ink-4)' }}>{tr('(vide)', '(empty)')}</span>}
      </span>,
    )
  }
  const placeholder = p.example ?? (raw === undefined && p.value !== undefined ? formatValue(p.value, 60) : undefined)
  if (choices && choices.length) {
    // Menu in the given order; a value outside the list stays shown as an extra option.
    const cur = raw !== undefined ? raw : p.value
    return row(
      <ParamWidget kind="select" value={cur === undefined || cur === null ? '' : String(cur)} tip={tip}
                   options={choices.map(String)} disabledOptions={p.reserved}
                   optionLabels={p.choiceLabels && Object.fromEntries(Object.entries(p.choiceLabels).map(([k, l]) => [k, lang === 'en' ? l.en : l.fr]))}
                   onChange={v => onChange(v === '' ? undefined : choices.find(c => String(c) === v) ?? v)} />,
    )
  }
  if (p.tokens) {
    return row(
      <TokenField value={raw} section={p.tokens} options={tokens ? tokenOptions : []} tip={tip} placeholder={placeholder}
                  onChange={v => onChange(storedValue(p.type, v))} />,
    )
  }
  const kind = kindOf(p.type)
  const shown = p.type === 'dict' && raw !== undefined && typeof raw !== 'string' ? JSON.stringify(raw) : raw
  return row(
    <ParamWidget kind={kind} value={shown} tip={tip} placeholder={placeholder}
                 onChange={v => onChange(storedValue(p.type, v))} />,
  )
}

// Inputs (ports) and constants (wirable false), in spec order when the node has a spec.
function paramPorts(node: FlowViewNode): PortSpec[] {
  const all = [...node.inputs, ...(node.constants ?? [])].filter(p => p.type !== 'exec')
  if (!node.spec || !node.constants?.length) return all
  const order = [...node.spec.inputs, ...node.spec.params].map(p => p.name)
  const rank = (n: string) => { const i = order.indexOf(n); return i < 0 ? order.length : i }
  return all.sort((a, b) => rank(a.name) - rank(b.name))
}

export interface NodeEdits {
  onParam: (id: string, name: string, value: unknown) => void
  onFields: (id: string, patch: { label?: string; bypass?: boolean }) => void
}

// ADR 0068: an InputsPageReader reads its page into params.ports (one exec output per button,
// one data output per field), like a FlowCall reads the called flow. The ports follow the page
// as soon as the node is selected; a link to a port the page lost stays, W_PAGE_LINK_BROKEN.
type PagePortsParam = { outputs: Record<string, string>; labels: Record<string, string> }

function usePageIds(active: boolean, project: string | null | undefined): string[] {
  const [ids, setIds] = useState<string[]>([])
  useEffect(() => {
    if (!active) return
    let alive = true
    flowsApi.listPages(project || undefined)
      .then(l => { if (alive) setIds([...new Set(l.pages.filter(p => !p.error).map(p => p.id))]) })
      .catch(() => { if (alive) setIds([]) })
    return () => { alive = false }
  }, [active, project])
  return ids
}

// Interface type -> page widget kind (same table as the generated Publisher panel, 04 §7).
const KIND_FOR_TYPE: Record<string, PageWidgetKind> = {
  float: 'float', int: 'int', bool: 'toggle', str: 'text', pattern: 'text', path: 'path', dir: 'dir', select: 'select', 'list[str]': 'list',
}

// "Creer une page pour ce flow": a page named like the flow, one field per interface input
// (its values also fill those inputs on a click, ADR 0068 n°4) and a Lancer button. Team TD.
async function createFlowPage(flowName: string, project: string | null | undefined): Promise<string> {
  const read = await flowsApi.get(flowName, { project: project || undefined })
  const raw = read.flow.interface as unknown
  const inputs = (Array.isArray(raw) ? raw : (read.flow.interface?.inputs ?? [])) as InterfaceInput[]
  const fields: PageWidget[] = inputs.filter(i => KIND_FOR_TYPE[i.type] && i.id !== 'lancer').map(i => ({
    id: i.id, kind: KIND_FOR_TYPE[i.type], label: i.label || i.id,
    ...(i.default !== undefined && i.default !== null ? { default: i.default } : {}),
    ...(i.type === 'select' ? { options: (i.options ?? []).map(o => ({ value: String(o), label: String(o) })) } : {}),
  }))
  const page: PageDoc = {
    page: 1, id: flowName, label: read.flow.label || flowName, icon: 'wrench', data: [],
    layout: [...fields.map(w => ({ row: [w] })), { row: [{ id: 'lancer', kind: 'button', label: 'Lancer' }] }],
  }
  await flowsApi.savePage(page, read.scope === 'project' ? 'project' : 'team', { project: project || undefined, base_rev: null })
  return flowName
}

function PageInputsPorts({ params, editable, flowName, onPage, onPorts }: {
  params: Record<string, unknown>; editable: boolean; flowName?: string
  onPage: (page: string) => void; onPorts: (p: PagePortsParam) => void
}) {
  const { tr } = useTr()
  const { project } = useProject()
  const page = String(params.page ?? '')
  const [found, setFound] = useState<PagePortsParam | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    if (!page) { setFound(null); setError(''); return }
    let alive = true
    flowsApi.pagePorts(page, project || undefined)
      .then(r => { if (alive) { setFound({ outputs: r.outputs, labels: r.labels }); setError('') } })
      .catch(e => { if (alive) { setFound(null); setError(String(e?.message ?? e)) } })
    return () => { alive = false }
  }, [page, project])
  const stored = (params.ports ?? { outputs: {}, labels: {} }) as PagePortsParam
  const same = !!found && JSON.stringify(found) === JSON.stringify({ outputs: stored.outputs ?? {}, labels: stored.labels ?? {} })
  useEffect(() => { if (found && !same && editable) onPorts(found) }, [found, same, editable, onPorts])
  const make = () => {
    if (!flowName) return
    createFlowPage(flowName, project)
      .then(id => { onPage(id); toast.success(tr(`Page ${id} creee : relie son bouton Lancer`, `Page ${id} created: link its Lancer button`)) })
      .catch(e => toast.error(String((e as Error)?.message ?? e)))
  }
  if (!page) return (
    <div style={{ fontSize: 11, color: 'var(--ink-4)', margin: '6px 0' }}>
      {tr('Choisis la page : ses boutons et ses champs deviendront les sorties du node.', 'Pick the page: its buttons and fields become the outputs of the node.')}
      {editable && flowName && (
        <button type="button" className="flow-tool" onClick={make} style={{ width: 'auto', padding: '0 6px', marginTop: 6, fontSize: 11, display: 'block' }}
                title={tr('Une page du nom du flow : un champ par entree du flow enregistre, un bouton Lancer (case Team TD)',
                          'A page named like the flow: one field per input of the saved flow, a Lancer button (Team TD box)')}>
          {tr('Creer une page pour ce flow', 'Create a page for this flow')}
        </button>
      )}
    </div>
  )
  const shown = found ?? stored
  const names = (exec: boolean) => Object.entries(shown.outputs ?? {}).filter(([, ty]) => (ty === 'exec') === exec)
    .map(([id]) => shown.labels?.[id] ?? id).join(', ') || tr('aucun', 'none')
  return (
    <div style={{ fontSize: 11, margin: '6px 0 8px', color: 'var(--ink-3)', lineHeight: 1.45 }}>
      {error && <div style={{ color: 'var(--warn)' }}>{tr(`Page ${page} illisible : ${error}`, `Cannot read page ${page}: ${error}`)}</div>}
      <div>{tr('Boutons', 'Buttons')} : {names(true)}</div>
      <div>{tr('Champs', 'Fields')} : {names(false)}</div>
      <div style={{ color: 'var(--ink-4)', marginTop: 4 }}>
        {tr('Chaque bouton est une sortie exec (triangle) : relie-la a l\'exec du node a lancer. Les champs sont des valeurs a brancher seulement si un node en a besoin. Le flow doit etre actif pour qu\'un clic le lance ; lance autrement, les champs donnent les valeurs par defaut de la page.',
            'Each button is an exec output (triangle): link it to the exec of the node to start. Fields are values, to link only when a node needs them. The flow must be active for a click to start it; started another way, the fields give the page defaults.')}
      </div>
    </div>
  )
}

// R1 retake 9: a FlowCall reads the interface of the called flow and stores it in
// params.ports (its dynamic ports, also read by validate.py). Empty ports are filled at once;
// a changed interface offers an update.
type CallPorts = { inputs: Record<string, string>; outputs: Record<string, string> }

function FlowCallPorts({ params, editable, onPorts }: {
  params: Record<string, unknown>; editable: boolean; onPorts: (p: CallPorts) => void
}) {
  const { tr } = useTr()
  const { project } = useProject()
  const name = String(params.flow ?? '')
  const [found, setFound] = useState<CallPorts | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    if (!name) { setFound(null); setError(''); return }
    let alive = true
    flowsApi.get(name, { project: project || undefined }).then(r => {
      if (!alive) return
      const iface = r.flow.interface ?? { inputs: [], outputs: [] }
      setFound({
        inputs: Object.fromEntries((iface.inputs ?? []).map(i => [i.id, i.type === 'select' ? 'str' : i.type])),
        outputs: Object.fromEntries((iface.outputs ?? []).map(o => [o.id, o.type])),
      })
      setError('')
    }).catch(e => { if (alive) { setFound(null); setError(String(e?.message ?? e)) } })
    return () => { alive = false }
  }, [name, project])
  const stored = (params.ports ?? { inputs: {}, outputs: {} }) as CallPorts
  const same = found && JSON.stringify(found) === JSON.stringify({ inputs: stored.inputs ?? {}, outputs: stored.outputs ?? {} })
  const empty = !Object.keys(stored.inputs ?? {}).length && !Object.keys(stored.outputs ?? {}).length
  useEffect(() => {
    if (found && empty && editable && (Object.keys(found.inputs).length || Object.keys(found.outputs).length)) onPorts(found)
  }, [found, empty, editable, onPorts])
  if (!name) return <div style={{ fontSize: 11, color: 'var(--ink-4)', margin: '6px 0' }}>{tr('Choisis le flow appele : ses entrees et sorties deviendront les ports du node.', 'Pick the called flow: its inputs and outputs become the ports of the node.')}</div>
  const list = (rec: Record<string, string>) => Object.entries(rec).map(([k, t]) => `${k} (${t})`).join(', ') || tr('aucune', 'none')
  return (
    <div style={{ fontSize: 11, margin: '6px 0 8px', color: 'var(--ink-3)', lineHeight: 1.45 }}>
      {error && <div style={{ color: 'var(--warn)' }}>{tr(`Flow ${name} illisible : ${error}`, `Cannot read flow ${name}: ${error}`)}</div>}
      <div>{tr('Entrees du flow appele', 'Inputs of the called flow')} : {list(stored.inputs ?? {})}</div>
      <div>{tr('Sorties du flow appele', 'Outputs of the called flow')} : {list(stored.outputs ?? {})}</div>
      {found && !same && (
        <button type="button" className="flow-tool" disabled={!editable} onClick={() => onPorts(found)}
                style={{ width: 'auto', padding: '0 6px', marginTop: 4, fontSize: 11 }}>
          {tr(`Mettre a jour les ports (${Object.keys(found.inputs).length} entrees, ${Object.keys(found.outputs).length} sorties)`,
              `Update the ports (${Object.keys(found.inputs).length} inputs, ${Object.keys(found.outputs).length} outputs)`)}
        </button>
      )}
    </div>
  )
}

// R1 retake 8: what a FlowInput / FlowOutput is tied to, under its params.
function InterfaceNote({ node }: { node: FlowViewNode }) {
  const { tr } = useTr()
  const text = node.type === 'data.flow_input'
    ? tr('Cette entree est remplie avant le lancement : formulaire du Run, champ d\'une page TOOL qui lance ce flow, ou valeur passee par un FlowCall. Liste des entrees : panneau du flow (clic dans le vide).',
         'This input is filled in before the start: Run form, field of a TOOL page that starts this flow, or value passed by a FlowCall. List of inputs: flow panel (click on empty space).')
    : tr('Cette valeur sort sur le port du meme nom du FlowCall qui appelle ce flow. Liste des sorties : panneau du flow (clic dans le vide).',
         'This value comes out on the port of the same name of the FlowCall that calls this flow. List of outputs: flow panel (click on empty space).')
  return <div style={{ fontSize: 11, margin: '6px 0 8px', color: 'var(--ink-3)', lineHeight: 1.45 }}>{text}</div>
}

function NodeParams({ node, params, editable, edits, flowName, iface }: { node: FlowViewNode; params: Record<string, unknown>; editable: boolean; edits: NodeEdits; flowName?: string; iface?: { inputs: string[]; outputs: string[] } }) {
  const { tr } = useTr()
  const fam = FAMILY_INFO[node.family]
  const canEdit = editable && !!node.spec
  const { project } = useProject()
  // Params hidden by the node's mode are left out, unless linked (then greyed, W_PORT_HIDDEN).
  const ports = paramPorts(node).filter(p => portVisible(node, p) || p.wiredFrom)
  const needsTokens = ports.some(p => p.tokens)
  const tokens = useProjectTokens(needsTokens ? project : null)
  const valueOf = (name: string) => {
    const p = ports.find(x => x.name === name)
    return params[name] !== undefined ? params[name] : p?.value
  }
  const isPageReader = node.type === 'event.page_inputs'
  const pageIds = usePageIds(isPageReader, project)
  const pageChoices = (name: string): unknown[] | undefined =>
    isPageReader && name === 'page' && pageIds.length ? pageIds : undefined
  // FlowInput / FlowOutput: the ids declared in the flow interface (R1 retake 8).
  const ifaceChoices = (name: string): unknown[] | undefined => {
    if (name !== 'id' || !iface) return undefined
    const ids = node.type === 'data.flow_input' ? iface.inputs : node.type === 'subflow.flow_output' ? iface.outputs : undefined
    return ids && ids.length ? ids : undefined
  }
  const isInterface = node.type === 'data.flow_input' || node.type === 'subflow.flow_output'
  const onParam = edits.onParam
  const onPorts = useCallback((p: CallPorts | PagePortsParam) => onParam(node.id, 'ports', p), [onParam, node.id])
  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span style={{ width: 10, height: 10, borderRadius: 3, background: fam.color }} />
        <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)' }}>{node.spec?.label ?? node.label}</span>
        <span className="tag">{node.id}</span>
      </div>
      {canEdit && (
        <>
          <Row label={<span style={{ fontSize: 11.5, color: 'var(--ink-3)' }}>{tr('Libelle', 'Label')}</span>}>
            <ParamWidget kind="str" value={node.meta?.step ?? ''} placeholder={node.spec?.label}
                         onChange={v => edits.onFields(node.id, { label: String(v) })} />
          </Row>
          <Row label={<span style={{ fontSize: 11.5, color: 'var(--ink-3)' }}>Bypass</span>}>
            <ParamWidget kind="bool" value={node.meta?.bypass === 'true'} tip={tr('Le node est saute au run', 'The node is skipped at run time')}
                         onChange={v => edits.onFields(node.id, { bypass: Boolean(v) })} />
          </Row>
        </>
      )}
      {!node.spec && (
        <div style={{ fontSize: 11, color: 'var(--ink-4)', margin: '4px 0 8px' }}>
          {tr('Node sans entree au catalogue (v1 migre ou type inconnu) : lecture seule.', 'Node without a catalogue entry (migrated v1 or unknown type): read-only.')}
        </div>
      )}
      {ports.length === 0
        ? <div style={{ fontSize: 11, color: 'var(--ink-4)', marginTop: 6 }}>{tr('Ce node n\'a pas de parametre.', 'This node has no parameter.')}</div>
        : ports.map(p => (
            <ParamRow key={p.name} p={p} editable={canEdit} raw={params[p.name]}
                      choices={p.choices ?? pageChoices(p.name) ?? ifaceChoices(p.name) ?? FALLBACK_CHOICES[node.type]?.[p.name]}
                      tokens={tokens} tokenOptions={p.tokens ? tokenKeys(tokens, p.tokens, valueOf('class')) : []}
                      muted={!portVisible(node, p)}
                      onChange={v => edits.onParam(node.id, p.name, v)} />
          ))}
      {isPageReader && <PageInputsPorts params={params} editable={canEdit} flowName={flowName} onPorts={onPorts}
                                        onPage={id => onParam(node.id, 'page', id)} />}
      {isInterface && <InterfaceNote node={node} />}
      {node.type === 'subflow.flow_call' && (
        <FlowCallPorts params={params} editable={canEdit} onPorts={onPorts} />
      )}
    </>
  )
}

export function ParamsPane({ selected, params, editable, edits, flowPart, flowName, iface }: {
  flowName?: string                        // name of the open flow (InputsPageReader: create its page)
  selected: FlowViewNode | null
  iface?: { inputs: string[]; outputs: string[] }   // interface ids (FlowInput / FlowOutput id menus)
  params: Record<string, unknown>          // params of the selected node in the document
  editable: boolean
  edits: NodeEdits
  flowPart: ReactNode                      // shown when no node is selected
}) {
  const { tr } = useTr()
  const [width, setWidth] = useState(readWidth)
  const [dragging, setDragging] = useState(false)
  const drag = useRef<{ x: number; w: number; last: number } | null>(null)

  // Keep the width inside the window when it shrinks.
  useEffect(() => {
    const onResize = () => setWidth(w => clampWidth(w))
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  const onPointerDown = useCallback((e: PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return
    e.preventDefault()
    e.currentTarget.setPointerCapture(e.pointerId)
    drag.current = { x: e.clientX, w: width, last: width }
    setDragging(true)
  }, [width])
  const onPointerMove = useCallback((e: PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return
    drag.current.last = clampWidth(drag.current.w + drag.current.x - e.clientX)   // dragging left widens
    setWidth(drag.current.last)
  }, [])
  const onPointerUp = useCallback((e: PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return
    const w = drag.current.last
    drag.current = null
    setDragging(false)
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId)
    try { localStorage.setItem(WIDTH_KEY, String(w)) } catch { /* storage blocked: width kept for the session */ }
  }, [])
  const onDoubleClick = useCallback(() => {
    setWidth(PARAMS_W)
    try { localStorage.removeItem(WIDTH_KEY) } catch { /* ignore */ }
  }, [])

  return (
    <aside style={{ width, flexShrink: 0, position: 'relative', borderLeft: '1px solid var(--rule)', background: 'var(--paper)', display: 'flex', minHeight: 0 }}>
      <div role="separator" aria-orientation="vertical" title={tr('Glisser pour redimensionner (double clic : largeur par defaut)', 'Drag to resize (double click: default width)')}
           onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerUp}
           onDoubleClick={onDoubleClick}
           style={{ position: 'absolute', left: -3, top: 0, bottom: 0, width: 6, cursor: 'col-resize', zIndex: 5,
                    background: dragging ? 'var(--accent)' : 'transparent', opacity: dragging ? 0.5 : 1, touchAction: 'none' }} />
      <div style={{ flex: 1, minWidth: 0, overflowY: 'auto', padding: '10px 12px' }}>
        {selected ? <NodeParams node={selected} params={params} editable={editable} edits={edits} flowName={flowName} iface={iface} /> : flowPart}
      </div>
    </aside>
  )
}
