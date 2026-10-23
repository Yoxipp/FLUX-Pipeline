// ParamWidget.tsx — one input widget per parameter kind, shared by ActionForm (Publisher,
// v1 actions), the Flows editor Params pane and the page renderer (03_EDITEUR §9).
// Extracted from ActionForm's FieldRow (P4): the kinds ActionForm used (bool, int, float,
// text, path, str) render exactly as before; dir, list and select are new (Flows).
// Flat, no glow, theme variables only.

import type { CSSProperties } from 'react'
import { FolderOpen } from 'lucide-react'
import { Btn, Check } from './ui'

export type ParamKind = 'bool' | 'int' | 'float' | 'text' | 'path' | 'dir' | 'list' | 'select' | 'str'

export const paramInputStyle: CSSProperties = {
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

const text = (value: unknown) => value === null || value === undefined ? '' : String(value)

export interface ParamWidgetProps {
  kind: ParamKind
  value: unknown
  onChange: (value: unknown) => void
  tip?: string
  placeholder?: string
  options?: string[]          // select
  disabled?: boolean
  onPickPath?: () => void     // native file / folder picker, when the host provides one
}

export function ParamWidget({ kind, value, onChange, tip, placeholder, options, disabled, onPickPath }: ParamWidgetProps) {
  switch (kind) {
    case 'bool':
      return (
        <div onClick={() => { if (!disabled) onChange(!value) }} style={{ cursor: disabled ? 'default' : 'pointer' }} title={tip}>
          <Check on={Boolean(value)} />
        </div>
      )

    case 'int':
    case 'float':
      return (
        <input type="number" value={text(value)} title={tip} disabled={disabled}
               onChange={e => onChange(e.target.value)} style={paramInputStyle} />
      )

    case 'text':
      return (
        <textarea value={text(value)} title={tip} disabled={disabled}
                  onChange={e => onChange(e.target.value)}
                  style={{ ...paramInputStyle, height: 54, padding: '6px 8px', resize: 'vertical' }} />
      )

    case 'list':
      // One item per line; the value stays a list.
      return (
        <textarea value={Array.isArray(value) ? value.map(text).join('\n') : text(value)} title={tip} disabled={disabled}
                  placeholder={placeholder}
                  onChange={e => onChange(e.target.value === '' ? [] : e.target.value.split('\n'))}
                  style={{ ...paramInputStyle, height: 54, padding: '6px 8px', resize: 'vertical' }} />
      )

    case 'select':
      return (
        <select value={text(value)} title={tip} disabled={disabled} onChange={e => onChange(e.target.value)} style={paramInputStyle}>
          {!(options ?? []).includes(text(value)) && <option value={text(value)}>{text(value)}</option>}
          {(options ?? []).map(o => <option key={o} value={o}>{o}</option>)}
        </select>
      )

    case 'path':
    case 'dir':
      return (
        <div style={{ display: 'flex', gap: 6, flex: 1, minWidth: 0 }}>
          <input value={text(value)} title={tip} disabled={disabled}
                 placeholder={placeholder ?? (kind === 'dir' ? 'chemin du dossier' : 'chemin du fichier')}
                 onChange={e => onChange(e.target.value)} style={paramInputStyle} />
          {onPickPath && !disabled && (
            <Btn sm ghost onClick={onPickPath} title="Parcourir">
              <FolderOpen size={13} />
            </Btn>
          )}
        </div>
      )

    default: // str and any unknown kind fall back to a text input
      return (
        <input value={text(value)} title={tip} disabled={disabled} placeholder={placeholder}
               onChange={e => onChange(e.target.value)} style={paramInputStyle} />
      )
  }
}
