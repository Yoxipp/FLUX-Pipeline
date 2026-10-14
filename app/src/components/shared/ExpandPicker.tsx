// ExpandPicker.tsx - one button that shows the current choice; a click slides the other
// choices out to its right, picking one closes the strip (ADR 0044). Replaces rows of
// always-visible pills (software, format, asset/shot, scope...).

import { useState, type ReactNode } from 'react'
import * as PopoverPrimitive from '@radix-ui/react-popover'
import { ChevronRight } from 'lucide-react'

export interface PickOption {
  value: string
  label: string
  icon?: ReactNode
  title?: string     // native tooltip (long explanation lives here, not on screen)
  muted?: boolean    // e.g. a software not enabled in the user settings
}

export function ExpandPicker({ value, options, onChange, placeholder = '-', iconOnly = false, mono = false, title, minWidth }: {
  value: string
  options: PickOption[]
  onChange: (value: string) => void
  placeholder?: string
  iconOnly?: boolean       // trigger + strip show icons only (label in the tooltip)
  mono?: boolean           // monospace labels (formats, tokens)
  title?: string
  minWidth?: number
}) {
  const [open, setOpen] = useState(false)
  const current = options.find(o => o.value === value)
  const others = options.filter(o => o.value !== value)
  const single = others.length === 0

  return (
    <PopoverPrimitive.Root open={open && !single} onOpenChange={setOpen}>
      <PopoverPrimitive.Trigger asChild>
        <button
          type="button"
          className={`xpick${open ? ' open' : ''}${mono ? ' mono' : ''}${current ? '' : ' empty'}`}
          title={title ?? current?.title ?? current?.label}
          style={minWidth ? { minWidth } : undefined}
          disabled={single && !!current}
        >
          {current?.icon}
          {(!iconOnly || !current?.icon) && <span className="xpick-label">{current?.label ?? placeholder}</span>}
          {!single && <ChevronRight size={11} strokeWidth={2.2} className="xpick-chev" />}
        </button>
      </PopoverPrimitive.Trigger>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content side="right" align="center" sideOffset={4} collisionPadding={8}
          className="xpick-strip" onOpenAutoFocus={e => e.preventDefault()}>
          {others.map((o, i) => (
            <button
              key={o.value}
              type="button"
              className={`xpick-opt${mono ? ' mono' : ''}${o.muted ? ' muted' : ''}`}
              style={{ animationDelay: `${Math.min(i, 8) * 18}ms` }}
              title={o.title ?? o.label}
              onClick={() => { onChange(o.value); setOpen(false) }}
            >
              {o.icon}
              {(!iconOnly || !o.icon) && <span>{o.label}</span>}
            </button>
          ))}
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  )
}
