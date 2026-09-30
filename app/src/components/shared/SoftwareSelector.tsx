import { Pill } from './ui'

// Supported DCCs + most recent supported version (detection itself is version-agnostic:
// the real source is DCC_EXE_PATTERNS glob wildcards in backend/core/constants.py).
const SW_DCC = [
  { name: 'Maya',      v: '2026' },
  { name: 'Houdini',   v: '22.0' },
  { name: 'Nuke',      v: '16.0' },
  { name: 'Marvelous', v: '2025' },
  { name: 'Painter',   v: '2024' },
  { name: 'Designer',  v: '2024' },
  { name: 'Mari',      v: '7.0' },
  { name: 'ZBrush',    v: '2026' },
  { name: 'Photoshop', v: '2025' },
]

interface Props {
  active?: string
  onChange?: (name: string) => void
  // Publisher shows "Fichier local" as a standalone source; the Importer hides it
  // and exposes local-file import as a per-software action instead.
  showLocal?: boolean
}

export function SoftwareSelector({ active = 'Maya', onChange, showLocal = true }: Props) {
  return (
    <div style={{
      minHeight: 34, borderBottom: '1px solid var(--rule)',
      padding: '4px 16px', display: 'flex', alignItems: 'center', gap: 8,
      background: 'var(--paper)', flexShrink: 0,
    }}>
      <div className="cap">LOGICIEL</div>
      <div style={{ width: 1, height: 12, background: 'var(--rule-2)' }} />
      <div style={{ display: 'flex', gap: 4, overflowX: 'auto', alignItems: 'center', paddingTop: 2, paddingBottom: 2 }}>
        {SW_DCC.map(s => (
          <Pill key={s.name} active={s.name === active} onClick={() => onChange?.(s.name)} style={{ cursor: 'pointer', whiteSpace: 'nowrap' }}>
            {s.name}<span style={{ marginLeft: 5, fontSize: 8, opacity: 0.55, fontFamily: 'var(--mono)' }}>{s.v}</span>
          </Pill>
        ))}
        {showLocal && (
          <>
            <div style={{ width: 1, height: 12, background: 'var(--rule-2)', margin: '0 4px', flexShrink: 0 }} />
            <Pill active={'Fichier local' === active} onClick={() => onChange?.('Fichier local')} style={{ cursor: 'pointer', whiteSpace: 'nowrap' }}>
              Fichier local
            </Pill>
          </>
        )}
      </div>
    </div>
  )
}
