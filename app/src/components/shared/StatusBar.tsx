import type { DccStatusMap } from '../../types'

interface Props {
  dccStatus: DccStatusMap
}

export function StatusBar({ dccStatus }: Props) {
  const items = Object.entries(dccStatus)
    .filter(([, entry]) => entry?.connected)
    .map(([key]) => ({ key, label: key }))

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
          <span className="dot ok" style={{ width: 5, height: 5 }} />
          <span style={{ color: 'var(--ink-2)' }}>{it.label}</span>
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
