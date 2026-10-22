// TopBar.tsx — top bar of the Flows editor (03_EDITEUR §1, 44 px): flow choice, badges,
// search, frame, and the way to the old editor (kept until P8, the v1 publish is edited there).

import { History, Maximize } from 'lucide-react'
import { Btn } from '../../components/shared/ui'
import { useTr } from './useTr'

export function TopBar({ flows, current, origin, search, onSearch, onChoose, onFrame, onLegacy }: {
  flows: string[]
  current: string
  origin?: string
  search: string
  onSearch: (s: string) => void
  onChoose: (name: string) => void
  onFrame: () => void
  onLegacy: () => void
}) {
  const { tr } = useTr()
  const field: React.CSSProperties = {
    fontSize: 12, padding: '4px 8px', background: 'var(--paper-2)', border: '1px solid var(--rule-2)',
    borderRadius: 5, color: 'var(--ink)', outline: 'none', fontFamily: 'var(--sans)',
  }
  return (
    <div style={{ height: 44, flexShrink: 0, display: 'flex', alignItems: 'center', gap: 8, padding: '0 10px', borderBottom: '1px solid var(--rule)', background: 'var(--paper)' }}>
      <span style={{ fontSize: 11, color: 'var(--ink-4)' }}>Flow</span>
      <select value={current} onChange={e => onChoose(e.target.value)} style={{ ...field, minWidth: 200 }}>
        {!flows.includes(current) && <option value={current}>{current || '…'}</option>}
        {flows.map(f => <option key={f} value={f}>{f}</option>)}
      </select>
      <span className="tag">v1</span>
      {origin === 'equipe' && <span className="tag">{tr('equipe', 'team')}</span>}
      <span className="tag" title={tr('Edition des flows en phase P4', 'Flow editing comes in phase P4')}>{tr('lecture seule', 'read-only')}</span>
      <div style={{ flex: 1 }} />
      <input
        value={search} onChange={e => onSearch(e.target.value)}
        placeholder={tr('Chercher dans le flow', 'Search in the flow')}
        style={{ ...field, width: 200 }}
      />
      <Btn sm ghost onClick={onFrame} title={tr('Cadrer tout (F)', 'Frame all (F)')}>
        <Maximize size={11} strokeWidth={2} /> {tr('Cadrer', 'Frame')}
      </Btn>
      <Btn sm ghost onClick={onLegacy} title={tr('Ancien editeur des actions YAML (edition du publish v1)', 'Old YAML action editor (v1 publish editing)')}>
        <History size={11} strokeWidth={2} /> {tr('Ancien editeur', 'Old editor')}
      </Btn>
    </div>
  )
}
