// ProdButtons — solid/ghost/big rounded-rectangle buttons, matching the
// "Add a Preset" look of TemplateEditor (colored fill, no stroke fight).

import type { CSSProperties, MouseEventHandler, ReactNode } from 'react'

interface Common {
  onClick?:  MouseEventHandler<HTMLButtonElement>
  disabled?: boolean
  title?:    string
  children?: ReactNode
  style?:    CSSProperties
  full?:     boolean          // stretch to container width
}

interface ProdBtnProps extends Common {
  variant?: 'solid' | 'ghost' | 'danger'
  size?:    'sm' | 'md' | 'lg'
  color?:   string             // override the accent fill (used by category buttons)
}

export function ProdBtn({
  variant = 'solid', size = 'md', color, full = false,
  onClick, disabled, title, children, style,
}: ProdBtnProps) {
  const pad = size === 'lg' ? '10px 16px' : size === 'sm' ? '4px 9px' : '6px 12px'
  const fs  = size === 'lg' ? 12 : size === 'sm' ? 10 : 11

  let bg: string, fg: string, bd: string
  if (variant === 'danger') {
    bg = 'color-mix(in oklch, var(--err) 14%, var(--paper-2))'
    fg = 'var(--err)'
    bd = 'color-mix(in oklch, var(--err) 55%, var(--rule-2))'
  } else if (variant === 'ghost') {
    bg = 'var(--paper-2)'
    fg = 'var(--ink-2)'
    bd = 'var(--rule-2)'
  } else {
    const c = color ?? 'var(--accent)'
    bg = c
    fg = 'var(--paper)'
    bd = c
  }

  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      style={{
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 6,
        font: 'inherit', fontSize: fs, fontWeight: variant === 'solid' ? 600 : 500,
        color: fg, background: bg,
        border: `1px solid ${bd}`,
        borderRadius: 6, padding: pad,
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.55 : 1,
        boxShadow: variant === 'solid' ? '0 1px 3px rgba(0,0,0,0.35)' : undefined,
        transition: 'transform 0.12s, filter 0.12s',
        width: full ? '100%' : undefined,
        ...style,
      }}
      onMouseEnter={e => { if (!disabled) { e.currentTarget.style.transform = 'scale(1.03)'; e.currentTarget.style.filter = 'brightness(1.08)' } }}
      onMouseLeave={e => { e.currentTarget.style.transform = 'scale(1)'; e.currentTarget.style.filter = 'brightness(1)' }}
    >
      {children}
    </button>
  )
}

// A large, category-coloured tile used at the root of the Asset grid.
export function CategoryTile({
  label, count, color, onClick,
}: {
  label:    string
  count:    number
  color:    string
  onClick:  () => void
}) {
  return (
    <button
      onClick={onClick}
      style={{
        display: 'flex', flexDirection: 'column', alignItems: 'flex-start', justifyContent: 'space-between',
        gap: 12, padding: '18px 20px',
        minWidth: 200, minHeight: 120,
        color: 'var(--paper)',
        background: color,
        border: `1px solid ${color}`, borderRadius: 10,
        cursor: 'pointer',
        boxShadow: '0 3px 10px rgba(0,0,0,0.35), inset 0 1px 0 rgba(255,255,255,0.15)',
        transition: 'transform 0.18s, filter 0.18s',
        fontFamily: 'var(--sans)',
      }}
      onMouseEnter={e => { e.currentTarget.style.transform = 'scale(1.04)'; e.currentTarget.style.filter = 'brightness(1.08)' }}
      onMouseLeave={e => { e.currentTarget.style.transform = 'scale(1)'; e.currentTarget.style.filter = 'brightness(1)' }}
    >
      <div style={{ fontSize: 16, fontWeight: 700, letterSpacing: '0.02em' }}>{label}</div>
      <div style={{ fontFamily: 'var(--mono)', fontSize: 10, opacity: 0.85 }}>
        {count === 0 ? '—' : `${count} asset${count > 1 ? 's' : ''}`}
      </div>
    </button>
  )
}
