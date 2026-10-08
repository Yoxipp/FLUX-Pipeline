// ConnectionPill.tsx - the only connection indicator a page shows (ADR 0044): a dot and
// one word. Versions, ports and setup steps live in the popover opened by a click, and
// only when there is something to do.

import type { ReactNode } from 'react'
import { Popover, PopoverTrigger, PopoverContent } from './ui'

export type ConnState = 'ok' | 'off' | 'checking' | 'warn'

const LABEL: Record<ConnState, string> = {
  ok: 'Connecté', off: 'Non connecté', checking: 'Vérification', warn: 'En attente',
}

export function ConnectionPill({ state, label, detail, help }: {
  state: ConnState
  label?: string          // overrides the default word
  detail?: string         // tooltip (version, port...)
  help?: ReactNode        // popover content shown on click (setup steps)
}) {
  const pill = (
    <button type="button" className={`conn-pill ${state}`} title={detail}>
      <span className="conn-dot" />
      {label ?? LABEL[state]}
    </button>
  )
  if (!help) return pill
  return (
    <Popover>
      <PopoverTrigger asChild>{pill}</PopoverTrigger>
      <PopoverContent side="bottom" align="start" style={{ width: 340, fontSize: 11, color: 'var(--ink-2)', lineHeight: 1.5 }}>
        {help}
      </PopoverContent>
    </Popover>
  )
}
