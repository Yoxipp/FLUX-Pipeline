import { Pill } from './ui'

const SW = [
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
}

export function SoftwareSelector({ active = 'Maya', onChange }: Props) {
  return (
    <div style={{
      height: 34, borderBottom: '1px solid var(--rule)',
      padding: '0 16px', display: 'flex', alignItems: 'center', gap: 8,
      background: 'var(--paper)', flexShrink: 0,
    }}>
      <div className="cap">LOGICIEL</div>
      <div style={{ width: 1, height: 12, background: 'var(--rule-2)' }} />
      <div style={{ display: 'flex', gap: 4, overflowX: 'auto' }}>
        {SW.map(s => (
          <Pill
            key={s.name}
            active={s.name === active}
            style={{ cursor: 'pointer' }}
          >
            <span onClick={() => onChange?.(s.name)}>{s.name}</span>
          </Pill>
        ))}
      </div>
    </div>
  )
}
