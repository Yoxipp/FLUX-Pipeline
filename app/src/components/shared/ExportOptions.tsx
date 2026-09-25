// ExportOptions.tsx — generic renderer for a per-format export option schema.
// Shows the "common" options inline and tucks the rest behind an "Avancé"
// expander. Fully data-driven: give it a schema + value map + onChange and it
// renders bool (checkbox), enum (select) and int/float (number field) controls.

import { useState } from 'react'
import { ChevronRight } from 'lucide-react'
import { Check, Select, SelectTrigger, SelectContent, SelectItem } from './ui'
import type { ExportOption } from '../../lib/mayaExportOptions'

type Values = Record<string, unknown>

// Stand-in for an empty choice value inside the Radix Select (see the enum branch).
const EMPTY = '__flux_empty__'

interface Props {
  schema: ExportOption[]
  values: Values
  onChange: (key: string, value: unknown) => void
}

const numInputStyle: React.CSSProperties = {
  width: 60, height: 24, padding: '0 6px', borderRadius: 5,
  border: '1px solid var(--rule-2)', background: 'var(--bg-deep)',
  color: 'var(--ink-2)', fontFamily: 'var(--mono)', fontSize: 10,
  outline: 'none', boxShadow: 'var(--shadow-inset)', textAlign: 'center',
}

function Row({ opt, values, onChange }: { opt: ExportOption; values: Values; onChange: Props['onChange'] }) {
  const disabled = !!opt.dependsOn && !values[opt.dependsOn]
  const wrap: React.CSSProperties = {
    display: 'flex', alignItems: 'center', gap: 8, minWidth: 0,
    opacity: disabled ? 0.4 : 1, pointerEvents: disabled ? 'none' : undefined,
  }

  if (opt.type === 'bool') {
    const on = !!values[opt.key]
    return (
      <div style={{ ...wrap, cursor: 'pointer' }} onClick={() => onChange(opt.key, !on)}>
        <Check on={on} />
        <span style={{ fontSize: 11, color: 'var(--ink-2)' }}>{opt.label}</span>
      </div>
    )
  }

  if (opt.type === 'enum') {
    // Radix Select throws on an empty-string item value (the whole page went grey when
    // Painter was picked: its "Taille" choice '' = size of the texture set). '' travels
    // as EMPTY inside the Select only; the stored value stays ''.
    const toSel = (v: string) => (v === '' ? EMPTY : v)
    const val = toSel(String(values[opt.key] ?? opt.default))
    // Full-width row so long labels + the select never overflow the column.
    return (
      <div style={{ ...wrap, gridColumn: '1 / -1' }}>
        <span style={{ fontSize: 11, color: 'var(--ink-3)', whiteSpace: 'nowrap', flexShrink: 0 }}>{opt.label}</span>
        <div style={{ flex: 1, minWidth: 0, display: 'flex', justifyContent: 'flex-end' }}>
          <Select value={val} onValueChange={v => onChange(opt.key, v === EMPTY ? '' : v)}>
            <SelectTrigger style={{ height: 24, width: '100%', maxWidth: 200, fontSize: 10 }} />
            <SelectContent>
              {(opt.choices ?? []).map(c => <SelectItem key={c.value} value={toSel(c.value)}>{c.label}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
      </div>
    )
  }

  if (opt.type === 'string') {
    const val = values[opt.key]
    return (
      <div style={wrap}>
        <span style={{ fontSize: 11, color: 'var(--ink-3)', whiteSpace: 'nowrap' }}>{opt.label}</span>
        <input
          type="text"
          value={val === undefined || val === null ? '' : String(val)}
          onChange={e => onChange(opt.key, e.target.value)}
          style={{ ...numInputStyle, width: 120, textAlign: 'left', fontFamily: 'var(--mono)' }}
        />
      </div>
    )
  }

  // int / float
  const raw = values[opt.key]
  return (
    <div style={wrap}>
      <span style={{ fontSize: 11, color: 'var(--ink-3)', whiteSpace: 'nowrap' }}>{opt.label}</span>
      <input
        type="number"
        value={raw === undefined || raw === null ? '' : String(raw)}
        onChange={e => {
          const n = opt.type === 'int' ? parseInt(e.target.value, 10) : parseFloat(e.target.value)
          onChange(opt.key, Number.isNaN(n) ? 0 : n)
        }}
        style={numInputStyle}
      />
    </div>
  )
}

export function ExportOptions({ schema, values, onChange }: Props) {
  const [showAdvanced, setShowAdvanced] = useState(false)
  if (schema.length === 0) return null

  const common = schema.filter(o => o.tier === 'common')
  const advanced = schema.filter(o => o.tier === 'advanced')

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: '8px 16px' }}>
        {common.map(o => <Row key={o.key} opt={o} values={values} onChange={onChange} />)}
      </div>

      {advanced.length > 0 && (
        <div>
          <div
            onClick={() => setShowAdvanced(s => !s)}
            style={{ display: 'flex', alignItems: 'center', gap: 5, cursor: 'pointer', userSelect: 'none', padding: '2px 0' }}
          >
            <ChevronRight
              size={12} strokeWidth={2} color="var(--ink-4)"
              style={{ transform: showAdvanced ? 'rotate(90deg)' : 'none', transition: 'transform 0.12s' }}
            />
            <span className="cap">Avancé</span>
            <span style={{ fontSize: 9, color: 'var(--ink-4)', fontFamily: 'var(--mono)' }}>({advanced.length})</span>
          </div>
          {showAdvanced && (
            <div style={{
              display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: '8px 16px',
              marginTop: 8, padding: '10px 12px', borderRadius: 6,
              background: 'var(--paper-2)', border: '1px solid var(--rule-2)',
            }}>
              {advanced.map(o => <Row key={o.key} opt={o} values={values} onChange={onChange} />)}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
