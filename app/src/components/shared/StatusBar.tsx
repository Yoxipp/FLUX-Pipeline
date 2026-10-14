import { useEffect, useState } from 'react'
import type { DccStatusMap } from '../../types'
import { useEnabledDccs } from '../../hooks/useEnabledDccs'
import { DCC_FRONTEND_KEYS, SOFTWARE } from '../../lib/dccs'
import { DccLogo } from './DccLogo'

interface Props {
  dccStatus: DccStatusMap
}

// Connected software, their mark only (ADR 0044): the name is the tooltip. The FLUX
// version (x.x.xxx, package.json fluxVersion via electron main) sits bottom-right.
export function StatusBar({ dccStatus }: Props) {
  const { isEnabled } = useEnabledDccs()
  const [version, setVersion] = useState('')
  useEffect(() => {
    window.electronAPI?.getAppVersion().then(setVersion).catch(() => {})
  }, [])

  const items = Object.entries(dccStatus)
    .filter(([key, entry]) => entry?.connected && isEnabled(DCC_FRONTEND_KEYS[key] ?? key))
    .map(([key]) => {
      const front = DCC_FRONTEND_KEYS[key] ?? key
      return { key, front, label: SOFTWARE.find(x => x.key === front)?.name ?? key }
    })

  return (
    <div style={{
      height: 24, padding: '0 14px',
      borderTop: '1px solid var(--rule)',
      background: 'var(--bg-deep)',
      display: 'flex', alignItems: 'center', gap: 12,
      flexShrink: 0,
    }}>
      {items.map(it => (
        <span key={it.key} title={`${it.label} connecté`} style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
          <DccLogo dcc={it.front} size={12} />
          <span className="dot ok" style={{ width: 4, height: 4, position: 'absolute', right: -3, bottom: -1 }} />
        </span>
      ))}
      {version && (
        <span
          title={`FLUX ${version}`}
          style={{ marginLeft: 'auto', fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-3)', userSelect: 'text' }}
        >
          v{version}
        </span>
      )}
    </div>
  )
}
