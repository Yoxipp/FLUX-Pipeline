// PortTooltip.tsx — one shared tooltip for every port (03_EDITEUR §3): a single portal
// instead of a Radix Tooltip per port (hundreds of ports). 300 ms delay like ui.tsx.
// Content: name + type, expected type, description, example, current value (inputs only).

import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { portColor } from '../portTypes'
import type { PortSpec } from '../types'
import { formatValue, useTr } from '../useTr'

export interface PortHover { port: PortSpec; side: 'in' | 'out'; rect: DOMRect }

interface Ctx { show: (h: PortHover) => void; hide: () => void }
const PortTooltipCtx = createContext<Ctx>({ show: () => {}, hide: () => {} })
export const usePortTooltip = () => useContext(PortTooltipCtx)

const DELAY_MS = 300

export function PortTooltipProvider({ children }: { children: React.ReactNode }) {
  const [hover, setHover] = useState<PortHover | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout>>()
  const show = useCallback((h: PortHover) => {
    clearTimeout(timer.current)
    timer.current = setTimeout(() => setHover(h), DELAY_MS)
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
  const { tr, lang } = useTr()
  const { port, side, rect } = hover
  const doc = lang === 'en' ? port.doc_en || port.doc_fr : port.doc_fr || port.doc_en
  const isExec = port.type === 'exec'
  const current = port.wiredFrom ? `<- ${port.wiredFrom}` : formatValue(port.value, 80)
  // Right of an output, left of an input; kept inside the window.
  const W = 320
  const left = side === 'out' ? rect.right + 8 : Math.max(8, rect.left - W - 8)
  const top = Math.min(rect.top - 6, window.innerHeight - 160)
  const label: React.CSSProperties = { color: 'var(--ink-4)', fontSize: 10.5, marginTop: 6 }
  return (
    <div className="tooltip-content" style={{ position: 'fixed', left, top, maxWidth: W, width: 'max-content', pointerEvents: 'none' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{ width: 8, height: 8, borderRadius: 2, background: portColor(port.type), flexShrink: 0 }} />
        <span style={{ fontWeight: 600 }}>{port.name}</span>
        <span style={{ color: 'var(--ink-3)' }}>{port.type}</span>
      </div>
      <div style={label}>{tr('Attendu', 'Expected')}</div>
      <div>
        {isExec
          ? tr('Ordre d\'execution : relie a un autre port d\'execution.', 'Execution order: links to another execution port.')
          : port.type === 'any'
            ? tr('Type inconnu (any) : accepte tout.', 'Unknown type (any): accepts anything.')
            : port.type}
      </div>
      {doc && <><div style={label}>{tr('Description', 'Description')}</div><div>{doc}</div></>}
      {port.example && <><div style={label}>{tr('Exemple', 'Example')}</div><div>{port.example}</div></>}
      {side === 'in' && !isExec && (
        <>
          <div style={label}>{tr('Valeur courante', 'Current value')}</div>
          <div style={{ color: current ? 'var(--ink)' : 'var(--ink-4)' }}>
            {current || (port.required ? tr('(vide, obligatoire)', '(empty, required)') : tr('(vide)', '(empty)'))}
          </div>
        </>
      )}
    </div>
  )
}
