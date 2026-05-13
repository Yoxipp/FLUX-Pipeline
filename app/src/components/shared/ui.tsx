import React, { type CSSProperties } from 'react'
import { Check as CheckIcon } from 'lucide-react'

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

export const Btn = ({ children, primary, ghost, sm, kbd, style, onClick }: {
  children: React.ReactNode; primary?: boolean; ghost?: boolean; sm?: boolean; kbd?: boolean
  style?: CSSProperties; onClick?: () => void
}) => (
  <div
    className={`btn${primary ? ' primary' : ''}${ghost ? ' ghost' : ''}${sm ? ' sm' : ''}${kbd ? ' kbd' : ''}`}
    style={style}
    onClick={onClick}
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
