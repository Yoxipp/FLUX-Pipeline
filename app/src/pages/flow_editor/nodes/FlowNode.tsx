// FlowNode.tsx — a node of the Flows editor (03_EDITEUR §3): name band in the family colour
// (2026-10-22), icon, DCC prefix badge, exec row on top, one 20 px row per data port
// (port names only, 2026-10-23). Hover shows a small toolbar like Houdini: bypass, info.
// P2: run state of the node (03_EDITEUR §7): running = accent border + spinning loader, ok =
// check + count, error = --err border + message (values received in the tooltip),
// error_handled = --warn border, skipped / cancelled = dashed border.
// P4: issue badge (count, --err or --warn) in the header, red ring on the faulty ports,
// one blink when zoomed from the Problems panel.
// (i) opens the info card (the maintainer R1 2026-10-24): it stays open until a click outside or Escape;
// values first (inputs, outputs: value of the last run or dry run, else the set value, else
// "no value yet"), coloured by port type, family and run state; then the node's section of
// docs/flows/03_INDEX_NODES.md (nodeDoc.tsx, else the registry doc) folded in "Hints".
// P6a: a DCC node shipped as a locked subflow shows a lock (shipped) or a team tag (its team
// copy); double click enters it (NetworkPane), like a Houdini HDA (03_EDITEUR §8).

import { forwardRef, memo, useEffect, useRef, useState } from 'react'
import { NodeToolbar, Position, type Node, type NodeProps } from '@xyflow/react'
import { Ban, CircleCheck, CircleX, Info, LoaderCircle, Lock, Users, X } from 'lucide-react'
import { FAMILY_INFO } from '../families'
import { NodeDocText, nodeDocSection } from '../nodeDoc'
import { iconFor } from '../icons'
import { portColor } from '../portTypes'
import type { FlowViewNode, NodeRunInfo, PortSpec } from '../types'
import { formatValue, useTr } from '../useTr'
import { PortHandle, handleId } from './PortHandle'
import { usePortTooltip } from './PortTooltip'
import { portVisible } from '../visibility'
import '../flow_editor.css'

export const NODE_W = 240
const HEADER_H = 28
const ROW_H = 20
const VALUE_MAX = 160
const HIDE_MS = 250   // time to reach the toolbar before it hides

export interface NodeIssues { errors: number; warnings: number; ports: string[] }
// Run values per port (RunRecord.links / link_value, else NodeRunInfo.values), for the info card.
export interface PortRunValues { in: Record<string, string>; out: Record<string, string> }
export type FlowNodeData = { node: FlowViewNode; linked: string[]; dim: boolean; run?: NodeRunInfo; issues?: NodeIssues; flash?: number; io?: PortRunValues }
export type FlowRfNode = Node<FlowNodeData, 'flow'>

const EXEC_IN: PortSpec = { name: 'exec', type: 'exec' }
const EXEC_OUT: PortSpec = { name: 'then', type: 'exec' }

function Row({ left, right, linked, faulty }: { left?: PortSpec; right?: PortSpec; linked: Set<string>; faulty: Set<string> }) {
  // The port names show the same tooltip as their dot (R1 retake 6).
  const { show, hide } = usePortTooltip()
  const hover = (port: PortSpec, side: 'in' | 'out') => (e: React.MouseEvent<HTMLSpanElement>) =>
    show({ port, side, rect: e.currentTarget.getBoundingClientRect() })
  return (
    <div style={{ position: 'relative', height: ROW_H, display: 'flex', alignItems: 'center', gap: 6, padding: '0 10px', fontSize: 11 }}>
      {left && <PortHandle port={left} side="in" linked={linked.has(handleId('in', left.name))} faulty={faulty.has(left.name)} />}
      {left && <span onMouseEnter={hover(left, 'in')} onMouseLeave={hide} style={{ color: 'var(--ink-2)', minWidth: 0, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{left.name}</span>}
      {!left && <span style={{ flex: 1 }} />}
      {right && <span onMouseEnter={hover(right, 'out')} onMouseLeave={hide} style={{ color: 'var(--ink-2)', whiteSpace: 'nowrap' }}>{right.name}</span>}
      {right && <PortHandle port={right} side="out" linked={linked.has(handleId('out', right.name))} faulty={faulty.has(right.name)} />}
    </div>
  )
}

const STATE_INFO: Record<string, { fr: string; en: string; color: string }> = {
  running:       { fr: 'en cours', en: 'running', color: 'var(--accent)' },
  ok:            { fr: 'OK', en: 'OK', color: 'var(--ok, var(--accent))' },
  error:         { fr: 'erreur', en: 'error', color: 'var(--err)' },
  error_handled: { fr: 'erreur geree', en: 'handled error', color: 'var(--warn)' },
  skipped:       { fr: 'saute', en: 'skipped', color: 'var(--ink-4)' },
  cancelled:     { fr: 'annule', en: 'cancelled', color: 'var(--ink-4)' },
}

function Chip({ text, color }: { text: string; color: string }) {
  return (
    <span style={{ fontSize: 10, fontWeight: 600, padding: '1px 6px', borderRadius: 4, whiteSpace: 'nowrap',
                   background: `color-mix(in oklch, ${color} 16%, transparent)`, color }}>
      {text}
    </span>
  )
}

// One port of the info card: type colour, name, then the value (run value first, else the
// set value, else "no value yet"). Long values are cut, with a Copy button for the full text.
function ValueLine({ port, set, run }: { port: PortSpec; set?: string; run?: string }) {
  const { tr } = useTr()
  const [copied, setCopied] = useState(false)
  const hasRun = run !== undefined && run !== ''
  const main = hasRun ? run : set
  const long = !!main && main.length > VALUE_MAX
  const copy = () => {
    if (!main) return
    void navigator.clipboard.writeText(main).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1200) }, () => {})
  }
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '10px 96px 1fr', columnGap: 6, alignItems: 'start', fontSize: 11, padding: '3px 0' }}>
      <span style={{ width: 8, height: 8, borderRadius: 2, marginTop: 3, background: portColor(port.type) }} />
      <span style={{ minWidth: 0 }}>
        <span style={{ display: 'block', color: 'var(--ink)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={port.name}>{port.label ?? port.name}</span>
        <span style={{ display: 'block', color: 'var(--ink-4)', fontSize: 10 }}>{port.type}</span>
      </span>
      <span style={{ minWidth: 0, wordBreak: 'break-all', whiteSpace: 'pre-wrap' }}>
        {main
          ? <span style={{ color: 'var(--ink)', fontFamily: 'var(--mono)', fontSize: 10.5 }} title={long ? main : undefined}>{long ? formatValue(main, VALUE_MAX) : main}</span>
          : <span style={{ color: 'var(--ink-4)' }}>{port.required ? tr('pas encore de valeur (obligatoire)', 'no value yet (required)') : tr('pas encore de valeur', 'no value yet')}</span>}
        {hasRun && set && set !== run && (
          <span style={{ display: 'block', color: 'var(--ink-4)', fontSize: 10 }}>{tr('regle', 'set')} : {formatValue(set, VALUE_MAX)}</span>
        )}
        {long && (
          <button type="button" className="flow-info-copy" onClick={copy}>{copied ? tr('copie', 'copied') : tr('copier', 'copy')}</button>
        )}
      </span>
    </div>
  )
}

// The (i) card (the maintainer R1 2026-10-24): values first (inputs then outputs, value of the last run
// or dry run, else the set value), then the run error, then the doc folded in "Hints".
const InfoCard = forwardRef<HTMLDivElement, { node: FlowViewNode; io?: PortRunValues; run?: NodeRunInfo; onClose: () => void }>(
  function InfoCard({ node, io, run, onClose }, ref) {
    const { tr, lang } = useTr()
    const fam = FAMILY_INFO[node.family]
    const section = nodeDocSection(node.type)
    const doc = lang === 'en' ? node.doc_en || node.doc_fr : node.doc_fr || node.doc_en
    const ins = [...node.inputs, ...(node.constants ?? [])].filter(p => p.type !== 'exec')
    const outs = node.outputs.filter(p => p.type !== 'exec')
    const state = run && run.state !== 'idle' ? STATE_INFO[run.state] : undefined
    const head: React.CSSProperties = { fontSize: 10.5, fontWeight: 600, color: 'var(--ink-4)', textTransform: 'uppercase', letterSpacing: 0.4,
                                        marginTop: 8, paddingTop: 6, borderTop: '1px solid var(--rule)' }
    const noRun = !run || run.state === 'idle'
    return (
      <div ref={ref} className="nowheel nodrag" style={{
        width: 360, maxHeight: 560, overflowY: 'auto', marginTop: 4, padding: '8px 10px', background: 'var(--paper)', border: '1px solid var(--rule-2)',
        borderTop: `3px solid ${fam.color}`, borderRadius: 6, boxShadow: 'var(--shadow)', fontSize: 11.5, color: 'var(--ink-2)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontWeight: 600, color: 'var(--ink)', flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{node.label}</span>
          <Chip text={lang === 'en' ? fam.en : fam.fr} color={fam.color} />
          {state && <Chip text={lang === 'en' ? state.en : state.fr} color={state.color} />}
          <button type="button" className="flow-info-close" title={tr('Fermer (Echap)', 'Close (Esc)')} onClick={onClose}><X size={12} /></button>
        </div>
        <div style={{ fontSize: 10.5, color: 'var(--ink-4)', marginBottom: 2 }}>{node.type}</div>
        {noRun && (ins.length > 0 || outs.length > 0) && (
          <div style={{ fontSize: 10.5, color: 'var(--ink-4)' }}>
            {tr('Valeurs du dernier run ou essai a blanc : lance Run ou Essai pour les voir.', 'Values of the last run or dry run: use Run or Dry run to see them.')}
          </div>
        )}
        {ins.length > 0 && <div style={head}>{tr('Entrees', 'Inputs')}</div>}
        {ins.map(p => (
          <ValueLine key={p.name} port={p}
                     set={p.wiredFrom ? `<- ${p.wiredFrom}` : formatValue(p.value, 4000)}
                     run={io?.in[p.name] ?? run?.values?.[p.name]} />
        ))}
        {outs.length > 0 && <div style={head}>{tr('Sorties', 'Outputs')}</div>}
        {outs.map(p => <ValueLine key={p.name} port={p} run={io?.out[p.name]} />)}
        {run?.error && (
          <div style={{ marginTop: 8, padding: '4px 6px', borderRadius: 4, fontSize: 11, wordBreak: 'break-word',
                        background: `color-mix(in oklch, ${run.state === 'error' ? 'var(--err)' : 'var(--warn)'} 12%, transparent)`,
                        color: run.state === 'error' ? 'var(--err)' : 'var(--warn)' }}>
            {run.error}
          </div>
        )}
        {Object.entries(node.meta ?? {}).filter(([k]) => k !== 'type').map(([k, v]) => (
          <div key={k} style={{ display: 'flex', gap: 6, fontSize: 11, marginTop: 3 }}>
            <span style={{ color: 'var(--ink-4)', width: 56, flexShrink: 0 }}>{k}</span>
            <span style={{ wordBreak: 'break-all', whiteSpace: 'pre-wrap' }}>{v}</span>
          </div>
        ))}
        <details className="flow-info-hints">
          <summary>Hints</summary>
          <div style={{ marginTop: 6 }}>
            {section
              ? <NodeDocText text={section} />
              : <div style={{ whiteSpace: 'pre-wrap' }}>{doc || tr('Pas de documentation.', 'No documentation.')}</div>}
          </div>
        </details>
      </div>
    )
  })

function runBorder(run: NodeRunInfo | undefined, selected: boolean): { color: string; style: string } {
  switch (run?.state) {
    case 'running':       return { color: 'var(--accent)', style: 'solid' }
    case 'error':         return { color: 'var(--err)', style: 'solid' }
    case 'error_handled': return { color: 'var(--warn)', style: 'solid' }
    case 'skipped':
    case 'cancelled':     return { color: 'var(--ink-4)', style: 'dashed' }
    default:              return { color: selected ? 'var(--ink-3)' : 'var(--rule-2)', style: 'solid' }
  }
}

function RunBadge({ run }: { run?: NodeRunInfo }) {
  if (!run || run.state === 'idle') return null
  const count = run.count && run.count > 1 ? <span style={{ fontSize: 10 }}>x{run.count}</span> : null
  if (run.state === 'running') return <LoaderCircle size={13} strokeWidth={2} style={{ animation: 'spin 1s linear infinite', flexShrink: 0 }} />
  if (run.state === 'ok') return <>{count}<CircleCheck size={13} strokeWidth={2} style={{ flexShrink: 0 }} /></>
  if (run.state === 'error' || run.state === 'error_handled') return <>{count}<CircleX size={13} strokeWidth={2} style={{ flexShrink: 0 }} /></>
  return null
}

function FlowNodeView({ data, selected }: NodeProps<FlowRfNode>) {
  const { tr } = useTr()
  const { node, dim, run, issues } = data
  const faulty = new Set(issues?.ports ?? [])
  const border = runBorder(run, !!selected)
  const failed = run && (run.state === 'error' || run.state === 'error_handled') && run.error
  const received = run?.values && Object.keys(run.values).length
    ? Object.entries(run.values).map(([k, v]) => `${k} = ${v}`).join('\n') : undefined
  const [hover, setHover] = useState(false)
  const [info, setInfo] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout>>()
  const enter = () => { clearTimeout(timer.current); setHover(true) }
  const leave = () => { timer.current = setTimeout(() => setHover(false), HIDE_MS) }
  // The info card stays open until a click outside it (or its button) or Escape (the maintainer R1).
  const cardRef = useRef<HTMLDivElement>(null)
  const barRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!info) return
    const onDown = (e: PointerEvent) => {
      const t = e.target as globalThis.Node | null
      if (t && (cardRef.current?.contains(t) || barRef.current?.contains(t))) return
      setInfo(false)
    }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setInfo(false) }
    document.addEventListener('pointerdown', onDown, true)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('pointerdown', onDown, true); document.removeEventListener('keydown', onKey) }
  }, [info])

  const linked = new Set(data.linked)
  const fam = FAMILY_INFO[node.family]
  const Icon = iconFor(node.icon, node.family)
  // Ports hidden by the node's mode are not drawn, unless linked (R1 retake 2).
  const shownIn = node.inputs.filter(p => portVisible(node, p) || linked.has(handleId('in', p.name)))
  const left = [...(node.hasExec ? [EXEC_IN] : []), ...shownIn]
  const right = [...(node.hasExec ? [EXEC_OUT] : []), ...node.outputs]
  const rows = Math.max(left.length, right.length)
  const isEvent = node.family === 'event'
  const radius = isEvent ? '12px 6px 6px 12px' : '6px'
  return (
    <div onMouseEnter={enter} onMouseLeave={leave} key={data.flash} className={data.flash ? 'flow-flash' : undefined}>
      <NodeToolbar isVisible={hover || info} position={Position.Top} align="start" offset={6}>
        <div ref={barRef} onMouseEnter={enter} onMouseLeave={leave}>
          <div className="flow-node-toolbar">
            <button type="button" disabled title={tr('Bypass : case dans Params', 'Bypass: box in Params')}>
              <Ban size={13} strokeWidth={1.75} />
            </button>
            <button type="button" className={info ? 'on' : ''} title={tr('Infos du node', 'Node info')} onClick={() => setInfo(v => !v)}>
              <Info size={13} strokeWidth={1.75} />
            </button>
          </div>
        </div>
      </NodeToolbar>
      <NodeToolbar isVisible={info} position={Position.Bottom} align="start" offset={4}>
        <InfoCard ref={cardRef} node={node} io={data.io} run={run} onClose={() => setInfo(false)} />
      </NodeToolbar>
      <div style={{
        width: NODE_W, background: 'var(--paper-2)',
        border: `1px ${border.style} ${border.color}`,
        borderRadius: radius,
        boxShadow: selected
          ? '0 0 0 3px color-mix(in oklch, var(--accent) 22%, transparent), var(--shadow-sm)'
          : 'var(--shadow-sm)',
        opacity: dim ? 0.35 : node.meta?.bypass === 'true' ? 0.55 : 1,
        paddingBottom: 4,
      }}>
        <div style={{
          height: HEADER_H, display: 'flex', alignItems: 'center', gap: 6, padding: '0 8px',
          background: fam.color, color: 'var(--on-accent)',
          borderRadius: isEvent ? '11px 5px 0 0' : '5px 5px 0 0',
        }}>
          <Icon size={14} strokeWidth={2} style={{ flexShrink: 0 }} />
          <span style={{ fontSize: 12, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
            {node.label}
          </span>
          {node.prefix && (
            <span style={{ fontSize: 10, fontWeight: 600, padding: '1px 5px', borderRadius: 4, background: 'color-mix(in oklch, var(--on-accent) 18%, transparent)' }}>
              {node.prefix}
            </span>
          )}
          {node.spec?.subflow && (
            <span title={node.spec.subflow.scope === 'shipped'
                    ? tr('Node livre verrouille : double clic pour voir dedans', 'Locked shipped node: double click to look inside')
                    : tr('Copie d\'equipe du node livre : double clic pour l\'editer', 'Team copy of the shipped node: double click to edit it')}
                  style={{ display: 'inline-flex', flexShrink: 0 }}>
              {node.spec.subflow.scope === 'shipped' ? <Lock size={12} /> : <Users size={12} />}
            </span>
          )}
          {node.destructive && (
            <span title={tr('Node destructif : efface, ecrase ou deplace des fichiers (validation au curseur a l\'enregistrement)', 'Destructive node: erases, overwrites or moves files (slider confirmation on save)')}
                  className="flow-issue-badge" style={{ background: 'var(--err)' }}>!</span>
          )}
          <RunBadge run={run} />
          {issues && issues.errors + issues.warnings > 0 && (
            <span className="flow-issue-badge" style={{ background: issues.errors ? 'var(--err)' : 'var(--warn)' }}
                  title={tr(`${issues.errors} erreur(s), ${issues.warnings} avertissement(s)`, `${issues.errors} error(s), ${issues.warnings} warning(s)`)}>
              {issues.errors + issues.warnings}
            </span>
          )}
        </div>
        {node.type === 'event.page_inputs' && (
          <div title={tr('Page TOOL lue : chaque bouton est une sortie exec (triangle) a relier a l\'exec du node a lancer',
                         'TOOL page read: each button is an exec output (triangle) to link to the exec of the node to start')}
               style={{ padding: '4px 10px', fontSize: 13, fontWeight: 600, fontFamily: 'var(--mono)', color: 'var(--ink)',
                        borderBottom: '1px solid var(--rule)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {String((node.constants ?? []).find(p => p.name === 'page')?.value ?? '') || tr('(choisis une page)', '(pick a page)')}
          </div>
        )}
        {(node.type === 'data.flow_input' || node.type === 'subflow.flow_output') && (
          <div title={node.type === 'data.flow_input'
                 ? tr('Entree du flow lue ici (interface du flow)', 'Flow input read here (flow interface)')
                 : tr('Sortie du flow remplie ici (interface du flow)', 'Flow output filled here (flow interface)')}
               style={{ padding: '4px 10px', fontSize: 13, fontWeight: 600, fontFamily: 'var(--mono)', color: 'var(--ink)',
                        borderBottom: '1px solid var(--rule)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {String([...node.inputs, ...(node.constants ?? [])].find(p => p.name === 'id')?.value ?? '') || tr('(choisis un id)', '(pick an id)')}
          </div>
        )}
        {failed && (
          <div
            title={received ? tr(`Valeurs recues :\n${received}`, `Values received:\n${received}`) : undefined}
            style={{ padding: '4px 10px', fontSize: 11, lineHeight: 1.35, color: run?.state === 'error' ? 'var(--err)' : 'var(--warn)', borderBottom: '1px solid var(--rule)', wordBreak: 'break-word' }}
          >
            {run?.error}
          </div>
        )}
        {Array.from({ length: rows }, (_, i) => (
          <Row key={i} left={left[i]} right={right[i]} linked={linked} faulty={faulty} />
        ))}
      </div>
    </div>
  )
}

export const FlowNode = memo(FlowNodeView)
