// PortTooltip.tsx — one shared tooltip for every port (03_EDITEUR §3): a single portal
// instead of a Radix Tooltip per port (hundreds of ports). 300 ms delay like ui.tsx.
// Content (PortHelp, also used by the Params labels, R1): name + type, description, expected
// type, possible values, default, example, current value (inputs only).
// P4: while a link is dragged over an incompatible port, the reason in red, shown at once.

import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { portColor, type Connection } from '../portTypes'
import type { PortSpec } from '../types'
import { formatValue, useTr } from '../useTr'

export interface PortHover { port: PortSpec; side: 'in' | 'out'; rect: DOMRect; refusal?: Connection | null }

interface Ctx { show: (h: PortHover) => void; hide: () => void }
const PortTooltipCtx = createContext<Ctx>({ show: () => {}, hide: () => {} })
export const usePortTooltip = () => useContext(PortTooltipCtx)

const DELAY_MS = 300

export function PortTooltipProvider({ children }: { children: React.ReactNode }) {
  const [hover, setHover] = useState<PortHover | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout>>()
  const show = useCallback((h: PortHover) => {
    clearTimeout(timer.current)
    timer.current = setTimeout(() => setHover(h), h.refusal ? 0 : DELAY_MS)
  }, [])
  const hide = useCallback(() => { clearTimeout(timer.current); setHover(null) }, [])
  useEffect(() => () => clearTimeout(timer.current), [])
  return (
    <PortTooltipCtx.Provider value={{ show, hide }}>
      {children}
      {hover && createPortal(<TooltipBox hover={hover} />, document.body)}
    </PortTooltipCtx.Provider>
  )
}

function TooltipBox({ hover }: { hover: PortHover }) {
  const { lang } = useTr()
  const { port, side, rect } = hover
  // Right of an output, left of an input; kept inside the window.
  const W = 320
  const left = side === 'out' ? rect.right + 8 : Math.max(8, rect.left - W - 8)
  const top = Math.min(rect.top - 6, window.innerHeight - 200)
  if (hover.refusal) {
    return (
      <div className="tooltip-content" style={{ position: 'fixed', left, top, maxWidth: W, width: 'max-content', pointerEvents: 'none', color: 'var(--err)' }}>
        {lang === 'en' ? hover.refusal.reason_en : hover.refusal.reason_fr}
      </div>
    )
  }
  return (
    <div className="tooltip-content" style={{ position: 'fixed', left, top, maxWidth: W, width: 'max-content', pointerEvents: 'none' }}>
      <PortHelp port={port} current={side === 'in'} />
    </div>
  )
}

// What a port or param is for, from the registry (R1 retake 6): name + type, description,
// possible values (menu labels, reserved ones marked), default, example, required / constant,
// and the current value when asked. Shared by the port tooltip and the Params labels.
export function PortHelp({ port, current }: { port: PortSpec; current?: boolean }) {
  const { tr, lang } = useTr()
  const doc = lang === 'en' ? port.doc_en || port.doc_fr : port.doc_fr || port.doc_en
  const isExec = port.type === 'exec'
  const value = port.wiredFrom ? `<- ${port.wiredFrom}` : formatValue(port.value, 80)
  const label: React.CSSProperties = { color: 'var(--ink-4)', fontSize: 10.5, marginTop: 6 }
  const choiceText = (c: unknown) => {
    const l = port.choiceLabels?.[String(c)]
    const shown = l ? `${lang === 'en' ? l.en : l.fr} (${String(c)})` : String(c)
    return port.reserved?.includes(String(c)) ? `${shown}, ${tr('indisponible', 'unavailable')}` : shown
  }
  const def = formatValue(port.default, 80)
  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{ width: 8, height: 8, borderRadius: 2, background: portColor(port.type), flexShrink: 0 }} />
        <span style={{ fontWeight: 600 }}>{port.name}</span>
        <span style={{ color: 'var(--ink-3)' }}>{port.type}</span>
        {port.required && <span style={{ color: 'var(--accent)' }}>{tr('obligatoire', 'required')}</span>}
      </div>
      {doc && <div style={{ marginTop: 4 }}>{doc}</div>}
      <div style={label}>{tr('Attendu', 'Expected')}</div>
      <div>
        {isExec
          ? tr("Ordre d'execution : relie a un autre port d'execution.", 'Execution order: links to another execution port.')
          : port.type === 'any'
            ? tr('Type inconnu (any) : accepte tout.', 'Unknown type (any): accepts anything.')
            : typeHint(port.type, tr)}
      </div>
      {port.choices && port.choices.length > 0 && (
        <>
          <div style={label}>{tr('Valeurs possibles', 'Possible values')}</div>
          {port.choices.map(c => <div key={String(c)}>{choiceText(c)}</div>)}
        </>
      )}
      {def && <><div style={label}>{tr('Defaut', 'Default')}</div><div>{def}</div></>}
      {port.example && <><div style={label}>{tr('Exemple', 'Example')}</div><div>{port.example}</div></>}
      {port.wirable === false && (
        <div style={{ ...label, color: 'var(--ink-3)' }}>{tr('Reglage fixe : se regle ici, ne se relie pas.', 'Fixed setting: set here, cannot be linked.')}</div>
      )}
      {current && !isExec && (
        <>
          <div style={label}>{tr('Valeur courante', 'Current value')}</div>
          <div style={{ color: value ? 'var(--ink)' : 'var(--ink-4)' }}>
            {value || (port.required ? tr('(vide, obligatoire)', '(empty, required)') : tr('(vide)', '(empty)'))}
          </div>
        </>
      )}
    </>
  )
}

// One sentence per port type, for the tooltip (the registry doc says the role).
function typeHint(type: string, tr: (fr: string, en: string) => string): string {
  if (type.startsWith('list[')) return tr(`Une liste (${type}) : relie une liste, ou une valeur par ligne.`, `A list (${type}): link a list, or one value per line.`)
  if (type.startsWith('session[')) return tr(`Une session de logiciel (${type}) : relie la sortie session d'un node Instance.`, `A software session (${type}): link the session output of an Instance node.`)
  const hints: Record<string, [string, string]> = {
    str: ['Du texte.', 'Text.'],
    int: ['Un nombre entier.', 'A whole number.'],
    float: ['Un nombre (decimales acceptees).', 'A number (decimals accepted).'],
    bool: ['Vrai ou faux (case a cocher).', 'True or false (checkbox).'],
    path: ['Un chemin de fichier ($FLUX/... accepte).', 'A file path ($FLUX/... accepted).'],
    dir: ['Un chemin de dossier ($FLUX/... accepte).', 'A folder path ($FLUX/... accepted).'],
    dict: ['Un dictionnaire de valeurs (JSON).', 'A dictionary of values (JSON).'],
    pattern: ['Un motif facon Houdini : *.png ^*_old*, vide = tout.', 'A Houdini style pattern: *.png ^*_old*, empty = all.'],
    publish: ['Un publish (FindPublishes, OnPublish, PublishFile).', 'A publish (FindPublishes, OnPublish, PublishFile).'],
    dcc_node: ['Un node de logiciel (Maya, Houdini...).', 'A software node (Maya, Houdini...).'],
  }
  const h = hints[type]
  return h ? `${tr(h[0], h[1])} (${type})` : type
}
