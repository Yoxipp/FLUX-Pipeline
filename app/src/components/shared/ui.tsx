import React, { type CSSProperties } from 'react'
import { Check as CheckIcon, ChevronDown } from 'lucide-react'
import * as TooltipPrimitive from '@radix-ui/react-tooltip'
import * as PopoverPrimitive from '@radix-ui/react-popover'
import * as SelectPrimitive from '@radix-ui/react-select'

export const Avatar = ({ ch, size = 20 }: { ch: string; size?: number }) => (
  <div style={{
    width: size, height: size, borderRadius: '50%',
    background: 'var(--accent-soft)',
    border: '1px solid var(--accent)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    fontFamily: 'var(--mono)', fontSize: Math.round(size * 0.52), fontWeight: 600,
    color: 'var(--accent-hi)', flexShrink: 0,
    boxShadow: 'var(--shadow-xs)',
  }}>{ch}</div>
)

export const Cap = ({ children, style }: { children: React.ReactNode; style?: CSSProperties }) => (
  <div className="cap" style={style}>{children}</div>
)

export const SecTitle = ({ children, right }: { children: React.ReactNode; right?: React.ReactNode }) => (
  <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '10px 0 7px' }}>
    <div className="cap" style={{ whiteSpace: 'nowrap' }}>{children}</div>
    <div style={{ flex: 1, height: 1, background: 'var(--rule)' }} />
    {right}
  </div>
)

export const Pill = ({ children, active, disabled, dot, style }: {
  children: React.ReactNode; active?: boolean; disabled?: boolean; dot?: string; style?: CSSProperties
}) => (
  <div className={`pill${active ? ' active' : ''}${disabled ? ' disabled' : ''}`} style={style}>
    {dot && <span className={`dot ${dot}`} />}
    {children}
  </div>
)

export const Btn = ({ children, primary, ghost, sm, kbd, disabled, style, onClick }: {
  children: React.ReactNode; primary?: boolean; ghost?: boolean; sm?: boolean; kbd?: boolean
  disabled?: boolean; style?: CSSProperties; onClick?: () => void
}) => (
  <div
    className={`btn${primary ? ' primary' : ''}${ghost ? ' ghost' : ''}${sm ? ' sm' : ''}${kbd ? ' kbd' : ''}${disabled ? ' disabled' : ''}`}
    style={disabled ? { opacity: 0.45, pointerEvents: 'none', ...style } : style}
    onClick={disabled ? undefined : onClick}
  >{children}</div>
)

export const Field = ({ value, placeholder, w = 240, tinted, glyph, suffix, style }: {
  value?: string; placeholder?: string; w?: number | string; tinted?: boolean
  glyph?: React.ReactNode; suffix?: React.ReactNode; style?: CSSProperties
}) => (
  <div className={`field${tinted ? ' tinted' : ''}`} style={{ width: w, ...style }}>
    {glyph}
    <span className={value ? '' : 'placeholder'} style={{ flex: 1 }}>{value || placeholder}</span>
    {suffix}
  </div>
)

export const Tag = ({ children, kind = '' }: { children: React.ReactNode; kind?: string }) => (
  <span className={`tag${kind ? ' ' + kind : ''}`}>{children}</span>
)

export const Toggle = ({ on }: { on: boolean }) => (
  <div style={{
    width: 32, height: 18, borderRadius: 999,
    border: '1px solid ' + (on ? 'var(--accent)' : 'var(--rule-2)'),
    background: on ? 'var(--accent-soft)' : 'var(--bg-deep)',
    position: 'relative', display: 'inline-block',
    boxShadow: on ? 'var(--shadow-xs), 0 0 6px color-mix(in oklch, var(--accent) 20%, transparent)' : 'var(--shadow-inset)',
    transition: 'background 0.18s, border-color 0.18s, box-shadow 0.18s',
  }}>
    <div style={{
      position: 'absolute', top: 3, left: on ? 15 : 2,
      width: 10, height: 10, borderRadius: '50%',
      background: on ? 'var(--accent-hi)' : 'var(--ink-4)',
      boxShadow: 'var(--shadow-xs)',
      transition: 'left 0.18s, background 0.18s',
    }} />
  </div>
)

export const Check = ({ on }: { on: boolean }) => (
  <div style={{
    width: 14, height: 14,
    border: '1px solid ' + (on ? 'var(--accent)' : 'var(--rule-2)'),
    display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
    background: on ? 'var(--accent-soft)' : 'var(--bg-deep)',
    borderRadius: 4,
    color: 'var(--accent-hi)', flexShrink: 0,
    boxShadow: on ? 'var(--shadow-xs)' : 'var(--shadow-inset)',
    transition: 'background 0.12s, border-color 0.12s',
  }}>
    {on && <CheckIcon size={9} strokeWidth={2.5} />}
  </div>
)

export const FolderIcon = ({ size = 12, color = 'currentColor' }: { size?: number; color?: string }) => (
  <svg width={size} height={size * 0.85} viewBox="0 0 14 12" fill="none" stroke={color} strokeWidth="1.2" strokeLinejoin="round">
    <path d="M0.6 2.8h4.8l1.4 1.4h6.6v6.4H0.6z" />
  </svg>
)

// ── Select ───────────────────────────────────────────────────────────────────

export function Select(props: React.ComponentProps<typeof SelectPrimitive.Root>) {
  return <SelectPrimitive.Root {...props} />
}

export function SelectTrigger({
  className, style, ...props
}: React.ComponentProps<typeof SelectPrimitive.Trigger>) {
  return (
    <SelectPrimitive.Trigger
      className={['select-trigger', className].filter(Boolean).join(' ')}
      style={style}
      {...props}
    >
      <SelectPrimitive.Value />
      <SelectPrimitive.Icon style={{ position: 'absolute', right: 7, pointerEvents: 'none', display: 'flex' }}>
        <ChevronDown size={11} strokeWidth={2} color="var(--ink-3)" />
      </SelectPrimitive.Icon>
    </SelectPrimitive.Trigger>
  )
}

export function SelectContent({
  children, ...props
}: React.ComponentProps<typeof SelectPrimitive.Content>) {
  return (
    <SelectPrimitive.Portal>
      <SelectPrimitive.Content
        className="select-content"
        position="popper"
        sideOffset={4}
        {...props}
      >
        <SelectPrimitive.Viewport>{children}</SelectPrimitive.Viewport>
      </SelectPrimitive.Content>
    </SelectPrimitive.Portal>
  )
}

export function SelectItem({
  children, value, ...props
}: React.ComponentProps<typeof SelectPrimitive.Item>) {
  return (
    <SelectPrimitive.Item value={value} className="select-item" {...props}>
      <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
    </SelectPrimitive.Item>
  )
}

// ── Popover ──────────────────────────────────────────────────────────────────

export function Popover(props: React.ComponentProps<typeof PopoverPrimitive.Root>) {
  return <PopoverPrimitive.Root {...props} />
}

export function PopoverTrigger(props: React.ComponentProps<typeof PopoverPrimitive.Trigger>) {
  return <PopoverPrimitive.Trigger {...props} />
}

export function PopoverContent({
  className, sideOffset = 6, align = 'end' as const, children, ...props
}: React.ComponentProps<typeof PopoverPrimitive.Content>) {
  return (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Content
        sideOffset={sideOffset}
        align={align}
        className={['popover-content', className].filter(Boolean).join(' ')}
        {...props}
      >
        {children}
      </PopoverPrimitive.Content>
    </PopoverPrimitive.Portal>
  )
}

export function PopoverClose(props: React.ComponentProps<typeof PopoverPrimitive.Close>) {
  return <PopoverPrimitive.Close {...props} />
}

// ── Tooltip ──────────────────────────────────────────────────────────────────

function TooltipProvider({
  delayDuration = 300,
  ...props
}: React.ComponentProps<typeof TooltipPrimitive.Provider>) {
  return <TooltipPrimitive.Provider delayDuration={delayDuration} {...props} />
}

export function Tooltip(props: React.ComponentProps<typeof TooltipPrimitive.Root>) {
  return <TooltipProvider><TooltipPrimitive.Root {...props} /></TooltipProvider>
}

export function TooltipTrigger(props: React.ComponentProps<typeof TooltipPrimitive.Trigger>) {
  return <TooltipPrimitive.Trigger {...props} />
}

export function TooltipContent({
  className,
  sideOffset = 6,
  children,
  ...props
}: React.ComponentProps<typeof TooltipPrimitive.Content>) {
  return (
    <TooltipPrimitive.Portal>
      <TooltipPrimitive.Content
        sideOffset={sideOffset}
        className={['tooltip-content', className].filter(Boolean).join(' ')}
        {...props}
      >
        {children}
        <TooltipPrimitive.Arrow asChild>
          <span><TooltipArrow /></span>
        </TooltipPrimitive.Arrow>
      </TooltipPrimitive.Content>
    </TooltipPrimitive.Portal>
  )
}

const TooltipArrow = () => (
  <svg width="20" height="10" viewBox="0 0 20 10" fill="none"
    style={{ marginLeft: 1, marginTop: -1 }}
    xmlns="http://www.w3.org/2000/svg"
  >
    <path
      d="M10.3356 7.39793L15.1924 3.02682C15.9269 2.36577 16.8801 2 17.8683 2H20V0H0V2H1.4651C2.4532 2 3.4064 2.36577 4.1409 3.02682L8.9977 7.39793C9.378 7.7402 9.9553 7.74021 10.3356 7.39793Z"
      fill="var(--paper-2)"
    />
    <path
      d="M11.1363 8.14124C10.3757 8.82575 9.22111 8.82578 8.46041 8.14122L3.60361 3.77011C3.05281 3.27432 2.33791 2.99999 1.59681 2.99999L4.24171 3L9.12941 7.39793C9.50971 7.7402 10.087 7.7402 10.4674 7.39793L15.3544 3L18 2.99999C17.2589 2.99999 16.544 3.27432 15.9931 3.77011L11.1363 8.14124Z"
      fill="var(--bg-deep)"
    />
    <path
      d="M9.6667 6.65461L14.5235 2.28352C15.4416 1.45721 16.6331 1 17.8683 1H20V2H17.8683C16.8801 2 15.9269 2.36577 15.1924 3.02682L10.3356 7.39793C9.9553 7.74021 9.378 7.7402 8.9977 7.39793L4.1409 3.02682C3.4064 2.36577 2.4532 2 1.4651 2H0V1H1.4651C2.7002 1 3.8917 1.45722 4.8099 2.28352L9.6667 6.65461Z"
      fill="var(--rule-2)"
    />
  </svg>
)
