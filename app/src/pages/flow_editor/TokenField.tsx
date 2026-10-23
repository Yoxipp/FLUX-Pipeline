// TokenField.tsx — Params pane widget of a param with `tokens` (catalogue CatalogPort.tokens,
// e.g. the TokenPath node): a text field (free typing: {shot}, ${var}) plus a menu filled
// with the keys of that token section of the current project (GET /folder/projects/{p}/tokens,
// cached per project for the session). No project selected: plain text field.
// NAME is filtered by the CLASS chosen on the same node (NAME path under the CLASS path,
// like Publisher's PublishComposer). Also: which TokenPath params matter for its mode.

import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import { paramInputStyle } from '../../components/shared/ParamWidget'
import { useTr } from './useTr'

export type ProjectTokens = Record<string, Record<string, string>>

const cache = new Map<string, Promise<ProjectTokens>>()

function loadTokens(project: string): Promise<ProjectTokens> {
  let p = cache.get(project)
  if (!p) {
    p = api.getTokens(project).then(r => r.tokens ?? {})
    p.catch(() => cache.delete(project))   // a failed load is retried next time
    cache.set(project, p)
  }
  return p
}

export function useProjectTokens(project: string | null | undefined): ProjectTokens | null {
  const [tokens, setTokens] = useState<ProjectTokens | null>(null)
  useEffect(() => {
    setTokens(null)
    if (!project) return
    let ok = true
    loadTokens(project).then(t => { if (ok) setTokens(t) }).catch(() => { if (ok) setTokens(null) })
    return () => { ok = false }
  }, [project])
  return tokens
}

const norm = (p: string) => p.replace(/\\/g, '/')
const isExpr = (v: unknown) => typeof v === 'string' && /[{}$]/.test(v)

// Keys of a section, in tokens.json order. NAME narrowed to the CLASS when one is set.
export function tokenKeys(tokens: ProjectTokens | null, section: string, cls?: unknown): string[] {
  const sec = tokens?.[section]
  if (!sec) return []
  const keys = Object.keys(sec)
  if (section === 'NAME' && typeof cls === 'string' && cls && !isExpr(cls)) {
    const classPath = norm(tokens?.CLASS?.[cls] ?? '')
    if (classPath) {
      const under = keys.filter(k => norm(sec[k] ?? '').startsWith(classPath + '/'))
      if (under.length) return under
    }
  }
  return keys
}

// TokenPath (data.token_path): params used by each mode. Others are shown greyed.
const TOKEN_PATH_MODES: Record<string, string[]> = {
  asset: ['class', 'name', 'type', 'instance'],
  shot:  ['seq', 'shot', 'task', 'instance'],
}
const TOKEN_PATH_PARAMS = new Set(Object.values(TOKEN_PATH_MODES).flat())

// false = the param does not apply to the node's current mode.
export function paramRelevant(nodeType: string, param: string, mode: unknown): boolean {
  if (nodeType !== 'data.token_path' || !TOKEN_PATH_PARAMS.has(param)) return true
  const used = TOKEN_PATH_MODES[String(mode ?? '')]
  return !used || used.includes(param)
}

export function TokenField({ value, options, onChange, tip, placeholder, section }: {
  value: unknown
  options: string[]            // empty = no project or no key: plain text field
  onChange: (value: string) => void
  tip?: string
  placeholder?: string
  section: string
}) {
  const { tr } = useTr()
  const text = value === null || value === undefined ? '' : String(value)
  return (
    <div style={{ display: 'flex', gap: 4, flex: 1, minWidth: 0 }}>
      <input value={text} title={tip} placeholder={placeholder} onChange={e => onChange(e.target.value)}
             style={{ ...paramInputStyle, fontFamily: 'var(--mono)' }} />
      {options.length > 0 && (
        <select value={options.includes(text) ? text : ''} onChange={e => { if (e.target.value) onChange(e.target.value) }}
                title={tr(`Choisir un token ${section} du projet`, `Pick a ${section} token of the project`)}
                style={{ ...paramInputStyle, flex: '0 0 auto', width: 70, padding: '0 4px', cursor: 'pointer', color: 'var(--ink-3)' }}>
          <option value="">{section}</option>
          {options.map(o => <option key={o} value={o}>{o}</option>)}
        </select>
      )}
    </div>
  )
}
