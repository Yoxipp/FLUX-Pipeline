// ActionForm.tsx — render a form from an action's parameters, not per feature.
//
// The backend action engine describes each input as an ActionField (type,
// label, tooltip, ask_user...). This component turns that list into widgets,
// picking one per declared type. Adding a parameter to a YAML action makes a
// field appear here with no extra front code. Style mirrors the backend: flat,
// no glow, theme variables only. The widgets live in ParamWidget.tsx (shared
// with the Flows editor, P4).

import type { ActionField } from '../../types'
import { ParamWidget, type ParamKind } from './ParamWidget'

// A field is addressed unambiguously by its (step, command, name) path.
export function fieldKey(f: Pick<ActionField, 'step' | 'command' | 'name'>): string {
  return `${f.step}.${f.command}.${f.name}`
}

// ActionField type -> widget kind. str, select and any unknown type stay a text input.
const KINDS: Record<string, ParamKind> = { bool: 'bool', int: 'int', float: 'float', text: 'text', path: 'path' }

interface FieldRowProps {
  field: ActionField
  value: unknown
  onChange: (value: unknown) => void
  onPickPath?: () => void   // native file picker, when the host provides one
}

function FieldRow({ field, value, onChange, onPickPath }: FieldRowProps) {
  const label = field.label || field.name
  const tip = field.tooltip ?? undefined
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 0' }}>
      <div className="cap" style={{ width: 130, flexShrink: 0 }} title={tip}>
        {label}
        {field.ask_user && <span style={{ color: 'var(--accent)', marginLeft: 3 }}>*</span>}
      </div>
      <ParamWidget kind={KINDS[field.type] ?? 'str'} value={value} onChange={onChange} tip={tip} onPickPath={onPickPath} />
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
