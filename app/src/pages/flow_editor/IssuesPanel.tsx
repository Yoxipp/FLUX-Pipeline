// IssuesPanel.tsx — Problems dock (03_EDITEUR §5): the issues of POST /flows/validate (the
// backend is the reference), errors then warnings: CircleX / TriangleAlert, message,
// reason in grey, code on hover, node label. "Verification..." during a call; backend
// unreachable: "Verification indisponible". A click on a line zooms on the node (the
// editor frames it, selects it, its border blinks once). "Corriger" applies the fix.

import { CircleX, TriangleAlert, Wrench, X } from 'lucide-react'
import type { Issue } from './types'
import { useTr } from './useTr'

export type CheckState = 'idle' | 'checking' | 'ok' | 'down'

export function IssuesPanel({ issues, state, labels, canFix, onZoom, onFix, onClose }: {
  issues: Issue[]
  state: CheckState
  labels: Record<string, string>              // node id -> label shown
  canFix: (i: Issue) => boolean               // a fix exists and applies here
  onZoom: (i: Issue) => void
  onFix: (i: Issue) => void
  onClose: () => void
}) {
  const { tr, lang } = useTr()
  const sorted = [...issues].sort((a, b) => Number(a.level !== 'error') - Number(b.level !== 'error'))
  const errors = issues.filter(i => i.level === 'error').length
  const warnings = issues.length - errors
  return (
    <div style={{ height: 200, flexShrink: 0, display: 'flex', flexDirection: 'column', borderTop: '1px solid var(--rule)', background: 'var(--paper)', fontSize: 11.5 }}>
      <div style={{ display: 'flex', alignItems: 'center', padding: '6px 10px', gap: 8, color: 'var(--ink-3)' }}>
        <span style={{ fontWeight: 600, color: 'var(--ink)' }}>{tr('Problemes', 'Problems')}</span>
        <span>{tr(`${errors} erreur(s), ${warnings} avertissement(s)`, `${errors} error(s), ${warnings} warning(s)`)}</span>
        {state === 'checking' && <span>{tr('Verification...', 'Checking...')}</span>}
        {state === 'down' && <span style={{ color: 'var(--err)' }}>{tr('Verification indisponible', 'Check unavailable')}</span>}
        <span style={{ flex: 1 }} />
        <button type="button" className="flow-tool" onClick={onClose} title={tr('Fermer', 'Close')}><X size={12} /></button>
      </div>
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {state !== 'down' && issues.length === 0 && (
          <div style={{ padding: '4px 10px', color: 'var(--ink-4)' }}>{tr('Aucun probleme.', 'No problem.')}</div>
        )}
        {sorted.map((i, k) => {
          const err = i.level === 'error'
          const Icon = err ? CircleX : TriangleAlert
          return (
            <div key={`${i.code}:${i.node}:${i.port}:${k}`} className="flow-issue" onClick={() => onZoom(i)} title={i.code}>
              <Icon size={13} strokeWidth={2} color={err ? 'var(--err)' : 'var(--warn)'} style={{ flexShrink: 0, marginTop: 1 }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ color: 'var(--ink)' }}>
                  {i.node && !(lang === 'en' ? i.message_en : i.message_fr).startsWith(labels[i.node] ?? i.node) && (
                    <span style={{ color: 'var(--ink-2)', fontWeight: 600 }}>{labels[i.node] ?? i.node} </span>
                  )}
                  {lang === 'en' ? i.message_en : i.message_fr}
                </div>
                <div style={{ color: 'var(--ink-4)' }}>{lang === 'en' ? i.why_en : i.why_fr}</div>
              </div>
              {canFix(i) && (
                <button type="button" className="flow-tool" onClick={e => { e.stopPropagation(); onFix(i) }} title={tr('Correction en un clic (annulable)', 'One click fix (undoable)')}>
                  <Wrench size={12} /> {tr('Corriger', 'Fix')}
                </button>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
