import { Pill } from './ui'

const SW_DCC = [
  { name: 'Maya',         v: '2025.3' },
  { name: 'Houdini',      v: '20.5' },
  { name: 'Nuke',         v: '15.0' },
  { name: 'Substance P.', v: '10.1' },
  { name: 'ZBrush',       v: '2024' },
  { name: 'Marvelous',    v: '12.2' },
  { name: 'Photoshop',    v: '2025' },
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
            {s.name}
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
