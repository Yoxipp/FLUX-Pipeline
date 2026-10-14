import React, { type CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { effectiveZoom, tooltipPosition, viewportRect } from './tooltipPosition'
import { Check as CheckIcon, ChevronDown } from 'lucide-react'
import * as TooltipPrimitive from '@radix-ui/react-tooltip'
import * as PopoverPrimitive from '@radix-ui/react-popover'
import * as SelectPrimitive from '@radix-ui/react-select'

export const Avatar = ({ ch, size = 20 }: { ch: string; size?: number }) => (
  <div style={{
    width: size, height: size, borderRadius: '50%',
    background: 'var(--accent-soft)',
    border: '1px solid var(--rule-3)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    fontFamily: 'var(--mono)', fontSize: Math.round(size * 0.52), fontWeight: 600,
    color: 'var(--accent-hi)', flexShrink: 0,
    boxShadow: 'var(--shadow-xs)',
  }}>{ch}</div>
)

export const SecTitle = ({ children, right }: { children: React.ReactNode; right?: React.ReactNode }) => (
  <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '10px 0 7px' }}>
    <div className="cap" style={{ whiteSpace: 'nowrap' }}>{children}</div>
    <div style={{ flex: 1, height: 1, background: 'var(--rule)' }} />
    {right}
  </div>
)

export const Pill = ({ children, active, disabled, dot, style, onClick }: {
  children: React.ReactNode; active?: boolean; disabled?: boolean; dot?: string; style?: CSSProperties; onClick?: () => void
}) => (
  <div
    className={`pill${active ? ' active' : ''}${disabled ? ' disabled' : ''}`}
    style={style}
    onClick={disabled ? undefined : onClick}
  >
    {dot && <span className={`dot ${dot}`} />}
    {children}
  </div>
)

export const Btn = ({ children, primary, ghost, sm, disabled, style, onClick, title }: {
  children: React.ReactNode; primary?: boolean; ghost?: boolean; sm?: boolean
  disabled?: boolean; style?: CSSProperties; onClick?: () => void; title?: string
}) => (
  <div
    className={`btn${primary ? ' primary' : ''}${ghost ? ' ghost' : ''}${sm ? ' sm' : ''}${disabled ? ' disabled' : ''}`}
    style={disabled ? { opacity: 0.45, pointerEvents: 'none', ...style } : style}
    onClick={disabled ? undefined : onClick}
    title={title}
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

export const Check = ({ on }: { on: boolean }) => (
  <div style={{
    width: 14, height: 14,
    border: '1px solid ' + (on ? 'var(--rule-3)' : 'var(--rule-2)'),
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

const TooltipZoomContext = React.createContext({
  zoom: 1,
  triggerRef: { current: null } as React.MutableRefObject<HTMLButtonElement | null>,
  screenPositioned: false,
  open: false,
  contentId: '',
})

export function Tooltip({ scale, ...props }: React.ComponentProps<typeof TooltipPrimitive.Root> & { scale?: number }) {
  const triggerRef = React.useRef<HTMLButtonElement | null>(null)
  const [zoom, setZoom] = React.useState(1)
  const [open, setOpen] = React.useState(props.defaultOpen ?? false)
  const isOpen = props.open ?? open
  const contentId = React.useId()
  const screenPositioned = scale != null || zoom !== 1

  React.useEffect(() => {
    if (!isOpen || !screenPositioned) return
    const close = () => { setOpen(false); props.onOpenChange?.(false) }
    const dismiss = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close()
    }
    const outsideClick = (event: PointerEvent) => {
      if (!triggerRef.current?.contains(event.target as Node)) close()
    }
    document.addEventListener('keydown', dismiss)
    document.addEventListener('tooltip.open', close)
    document.addEventListener('pointerdown', outsideClick)
    document.addEventListener('scroll', close, true)
    window.addEventListener('blur', close)
    return () => {
      document.removeEventListener('keydown', dismiss)
      document.removeEventListener('tooltip.open', close)
      document.removeEventListener('pointerdown', outsideClick)
      document.removeEventListener('scroll', close, true)
      window.removeEventListener('blur', close)
    }
  }, [isOpen, screenPositioned, props.onOpenChange])

  React.useLayoutEffect(() => {
    if (scale != null || !isOpen || !triggerRef.current) return
    // Body/html already scale the portal. Only recover zoom below its host.
    const ancestors: HTMLElement[] = []
    for (let element: HTMLElement | null = triggerRef.current;
      element && element !== document.body; element = element.parentElement) {
      ancestors.push(element)
    }
    const trigger = triggerRef.current
    const updateZoom = () => setZoom(effectiveZoom(trigger))
    updateZoom()
    const observer = new MutationObserver(updateZoom)
    ancestors.forEach(element => observer.observe(element, {
      attributes: true, attributeFilter: ['style', 'class'],
    }))
    return () => observer.disconnect()
  }, [isOpen, scale])

  return (
    <TooltipZoomContext.Provider value={{ zoom: scale ?? zoom, triggerRef, screenPositioned, open: isOpen, contentId }}>
      <TooltipProvider>
        <TooltipPrimitive.Root {...props} open={isOpen}
          disableHoverableContent={screenPositioned || props.disableHoverableContent} onOpenChange={nextOpen => {
          setOpen(nextOpen)
          props.onOpenChange?.(nextOpen)
        }} />
      </TooltipProvider>
    </TooltipZoomContext.Provider>
  )
}

export function TooltipTrigger(props: React.ComponentProps<typeof TooltipPrimitive.Trigger>) {
  const { triggerRef, screenPositioned, open, contentId } = React.useContext(TooltipZoomContext)
  return <TooltipPrimitive.Trigger {...props} ref={triggerRef} aria-describedby={screenPositioned ? open ? contentId : undefined : props['aria-describedby']} />
}

function ScreenTooltip({ children, className, style, side = 'top', align = 'center', sideOffset = 6 }: {
  children: React.ReactNode; className?: string; style?: CSSProperties
  side?: 'top' | 'bottom' | 'left' | 'right'; align?: 'start' | 'center' | 'end'; sideOffset?: number
}) {
  const { zoom, triggerRef, contentId } = React.useContext(TooltipZoomContext)
  const popup = React.useRef<HTMLDivElement>(null)
  const [position, setPosition] = React.useState<ReturnType<typeof tooltipPosition> | null>(null)
  React.useLayoutEffect(() => {
    let frame = 0
    const update = () => {
      const trigger = triggerRef.current, content = popup.current
      if (trigger && content) {
        const dimensions = content.getBoundingClientRect()
        const next = tooltipPosition(viewportRect(trigger), dimensions.width, dimensions.height,
          window.innerWidth, window.innerHeight, (sideOffset + 8) * zoom, side, align)
        setPosition(prev => prev && prev.left === next.left && prev.top === next.top && prev.side === next.side && prev.arrow === next.arrow ? prev : next)
      }
    }
    const follow = () => { update(); frame = requestAnimationFrame(follow) }
    update()
    frame = requestAnimationFrame(follow)
    return () => cancelAnimationFrame(frame)
  }, [zoom, triggerRef, sideOffset, side, align])
  const arrowStyle: CSSProperties = position?.side === 'bottom'
    ? { left: position.arrow, top: 0, transform: 'translate(-50%, -100%) rotate(180deg)' }
    : position?.side === 'left'
      ? { left: '100%', top: position.arrow, transform: 'translate(-25%, -50%) rotate(-90deg)' }
      : position?.side === 'right'
        ? { left: 0, top: position.arrow, transform: 'translate(-75%, -50%) rotate(90deg)' }
        : { left: position?.arrow ?? 0, top: '100%', transform: 'translateX(-50%)' }
  return createPortal(<div ref={popup} id={contentId} role="tooltip" className={['tooltip-content', className].filter(Boolean).join(' ')}
    style={{ ...style, '--tooltip-scale': zoom, position: 'fixed', left: position?.left ?? 0, top: position?.top ?? 0,
      visibility: position ? 'visible' : 'hidden', pointerEvents: 'none', animation: 'none' } as CSSProperties}>
    {children}
    <span aria-hidden style={{ position: 'absolute', width: 20 * zoom, height: 10 * zoom, ...arrowStyle }}>
      <span style={{ display: 'block', transform: `scale(${zoom})`, transformOrigin: 'top left', width: 20, height: 10 }}><TooltipArrow /></span>
    </span>
  </div>, document.body)
}

export function TooltipContent({
  className,
  sideOffset = 6,
  children,
  style,
  ...props
}: React.ComponentProps<typeof TooltipPrimitive.Content>) {
  const { zoom, screenPositioned, open } = React.useContext(TooltipZoomContext)
  if (screenPositioned) return open ? <ScreenTooltip className={className} style={style} side={props.side} align={props.align} sideOffset={sideOffset}>{children}</ScreenTooltip> : null
  return (
    <TooltipPrimitive.Portal>
      <TooltipPrimitive.Content
        sideOffset={sideOffset * zoom}
        className={['tooltip-content', className].filter(Boolean).join(' ')}
        style={{ ...style, '--tooltip-scale': zoom } as CSSProperties}
        {...props}
      >
        {children}
        <TooltipPrimitive.Arrow asChild>
          <span style={{ display: 'block', width: 20 * zoom, height: 10 * zoom }}>
            <span style={{ display: 'block', width: 20, height: 10, transform: `scale(${zoom})`, transformOrigin: 'top left' }}><TooltipArrow /></span>
          </span>
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
