// ActionForm.tsx — render a form from an action's parameters, not per feature.
//
// The backend action engine describes each input as an ActionField (type,
// label, tooltip, ask_user...). This component turns that list into widgets,
// picking one per declared type. Adding a parameter to a YAML action makes a
// field appear here with no extra front code. Style mirrors the backend: flat,
// no glow, theme variables only.

import type { CSSProperties } from 'react'
import { FolderOpen } from 'lucide-react'
import type { ActionField } from '../../types'
import { Btn, Check } from './ui'

// A field is addressed unambiguously by its (step, command, name) path.
export function fieldKey(f: Pick<ActionField, 'step' | 'command' | 'name'>): string {
  return `${f.step}.${f.command}.${f.name}`
}

const inputStyle: CSSProperties = {
  flex: 1,
  minWidth: 0,
  height: 26,
  padding: '0 8px',
  border: '1px solid var(--rule-2)',
  background: 'var(--bg-deep)',
  borderRadius: 5,
  fontSize: 12,
  color: 'var(--ink)',
}

interface FieldRowProps {
  field: ActionField
  value: unknown
  onChange: (value: unknown) => void
  onPickPath?: () => void   // native file picker, when the host provides one
}

function FieldRow({ field, value, onChange, onPickPath }: FieldRowProps) {
  const label = field.label || field.name
  const tip = field.tooltip ?? undefined

  let widget
  switch (field.type) {
    case 'bool':
      widget = (
        <div onClick={() => onChange(!value)} style={{ cursor: 'pointer' }} title={tip}>
          <Check on={Boolean(value)} />
        </div>
      )
      break

    case 'int':
    case 'float':
      widget = (
        <input
          type="number"
          value={value === null || value === undefined ? '' : String(value)}
          title={tip}
          onChange={e => onChange(e.target.value)}
          style={inputStyle}
        />
      )
      break

    case 'text':
      widget = (
        <textarea
          value={value === null || value === undefined ? '' : String(value)}
          title={tip}
          onChange={e => onChange(e.target.value)}
          style={{ ...inputStyle, height: 54, padding: '6px 8px', resize: 'vertical' }}
        />
      )
      break

    case 'path':
      widget = (
        <div style={{ display: 'flex', gap: 6, flex: 1, minWidth: 0 }}>
          <input
            value={value === null || value === undefined ? '' : String(value)}
            title={tip}
            placeholder="chemin du fichier"
            onChange={e => onChange(e.target.value)}
            style={inputStyle}
          />
          {onPickPath && (
            <Btn sm ghost onClick={onPickPath} title="Parcourir">
              <FolderOpen size={13} />
            </Btn>
          )}
        </div>
      )
      break

    default: // str, select and any unknown type fall back to a text input
      widget = (
        <input
          value={value === null || value === undefined ? '' : String(value)}
          title={tip}
          onChange={e => onChange(e.target.value)}
          style={inputStyle}
        />
      )
  }

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 0' }}>
      <div className="cap" style={{ width: 130, flexShrink: 0 }} title={tip}>
        {label}
        {field.ask_user && <span style={{ color: 'var(--accent)', marginLeft: 3 }}>*</span>}
      </div>
      {widget}
    </div>
  )
}

interface ActionFormProps {
  fields: ActionField[]
  values: Record<string, unknown>
  onChange: (key: string, value: unknown) => void
  onPickPath?: (key: string) => void
}

export function ActionForm({ fields, values, onChange, onPickPath }: ActionFormProps) {
  return (
    <div>
      {fields.map(f => {
        const key = fieldKey(f)
        return (
          <FieldRow
            key={key}
            field={f}
            value={values[key]}
            onChange={v => onChange(key, v)}
            onPickPath={onPickPath ? () => onPickPath(key) : undefined}
          />
        )
      })}
    </div>
  )
}
