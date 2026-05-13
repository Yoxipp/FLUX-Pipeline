import type { DccStatusMap } from '../../types'

interface Props {
  dccStatus: DccStatusMap
}

const STATUS_ITEMS = [
  { key: 'Maya',      label: 'Maya 2025' },
  { key: 'Houdini',   label: 'Houdini 20.5' },
  { key: 'Nuke',      label: 'Nuke 15.0' },
  { key: 'Substance', label: 'Substance 10.1' },
]

export function StatusBar({ dccStatus }: Props) {
  const items = STATUS_ITEMS
    .map(it => {
      const entry = dccStatus[it.key]
      const dot = entry ? (entry.connected ? 'ok' : 'warn') : ''
      return { ...it, dot }
    })
    .filter(it => it.dot)

  return (
    <div style={{
      height: 24, padding: '0 14px',
      borderTop: '1px solid var(--rule)',
      background: 'var(--bg-deep)',
      display: 'flex', alignItems: 'center', gap: 14,
      fontFamily: 'var(--mono)', fontSize: 9.5, color: 'var(--ink-3)',
      flexShrink: 0,
    }}>
      {items.map((it, i) => (
        <span key={it.key} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {i > 0 && <span style={{ width: 1, height: 12, background: 'var(--rule-2)', display: 'inline-block', marginRight: 8 }} />}
          <span className={`dot ${it.dot}`} style={{ width: 5, height: 5 }} />
          <span style={{ color: it.dot === 'ok' ? 'var(--ink-2)' : 'var(--ink-3)' }}>{it.label}</span>
        </span>
      ))}
      <span style={{ flex: 1 }} />
      <span style={{
        border: '1px solid var(--rule-2)', borderRadius: 999,
        padding: '1px 7px', fontSize: 9, color: 'var(--ink-3)',
      }}>v1.1</span>
    </div>
  )
}
