// MachinePicker.tsx: pick farm machines by room or one by one (submit targeting, team groups, exclusions).
// Rooms come from the studio's room_pattern (studio environment), see backend features/render/farm_targets.py.

import { useMemo, useState } from 'react'
import type { RenderBlade, RenderBladeState } from '../../api/client'
import { BLADE_COLOR, Toggle, bladeStateLabel, btn, hint, input, roomLabel, useTr } from './renderUi'

type StateFilter = 'all' | RenderBladeState

export function MachinePicker({ blades, selected, onChange, hideOffline = true, readOnly = false }: {
  blades: RenderBlade[]; selected: string[]; onChange: (names: string[]) => void; hideOffline?: boolean; readOnly?: boolean
}) {
  const { tr } = useTr()
  const [query, setQuery] = useState('')
  const [room, setRoom] = useState('')
  const [state, setState] = useState<StateFilter>('all')
  const picked = useMemo(() => new Set(selected), [selected])

  const rooms = useMemo(() => {
    const out: Record<string, { total: number; free: number }> = {}
    for (const b of blades) {
      if ((hideOffline && b.state === 'offline') || !b.room) continue
      const r = (out[b.room] ??= { total: 0, free: 0 })
      r.total += 1
      if (b.state === 'free') r.free += 1
    }
    return Object.entries(out).sort((a, b) => a[0].localeCompare(b[0]))
  }, [blades, hideOffline])

  const shown = useMemo(() => {
    const q = query.trim().toUpperCase()
    return blades.filter(b => (!hideOffline || b.state !== 'offline' || picked.has(b.name))
      && (!room || b.room === room) && (state === 'all' || b.state === state)
      && (!q || b.name.toUpperCase().includes(q)))
  }, [blades, query, room, state, hideOffline, picked])

  const toggle = (name: string) => onChange(picked.has(name) ? selected.filter(n => n !== name) : [...selected, name].sort())
  const setMany = (names: string[], on: boolean) => {
    const next = new Set(selected)
    names.forEach(n => (on ? next.add(n) : next.delete(n)))
    onChange([...next].sort())
  }
  const states: StateFilter[] = ['all', 'free', 'busy', 'nimby', 'offline']

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
        {rooms.length > 0 && <button type="button" style={{ ...btn(), background: !room ? 'var(--accent-soft)' : 'var(--paper-2)' }} onClick={() => setRoom('')}>
          {tr('Toutes les salles', 'All rooms')}
        </button>}
        {rooms.map(([r, c]) => (
          <button key={r} type="button" title={tr(`${c.free} libres sur ${c.total}`, `${c.free} free of ${c.total}`)}
            style={{ ...btn(), background: room === r ? 'var(--accent-soft)' : 'var(--paper-2)' }} onClick={() => setRoom(r)}>
            {roomLabel(r, tr)} <span style={{ color: 'var(--ink-3)' }}>{c.free}/{c.total}</span>
          </button>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        <input style={{ ...input, width: 160 }} value={query} placeholder={tr('Chercher un PC', 'Find a PC')} onChange={e => setQuery(e.target.value)} />
        <Toggle value={state} onChange={id => setState(id as StateFilter)}
          options={states.map(s => ({ id: s, label: s === 'all' ? tr('Tous', 'All') : bladeStateLabel(s, tr) }))} />
        {readOnly ? <span style={hint}>{shown.length}</span> : <>
          <button type="button" style={btn()} onClick={() => setMany(shown.map(b => b.name), true)}>
            {tr(`Cocher ces ${shown.length}`, `Check these ${shown.length}`)}
          </button>
          <button type="button" style={btn()} onClick={() => setMany(shown.map(b => b.name), false)}>{tr('Decocher', 'Uncheck')}</button>
          <span style={hint}>{tr(`${selected.length} choisi(s)`, `${selected.length} picked`)}</span>
        </>}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(118px, 1fr))', gap: 4, maxHeight: 220, overflowY: 'auto' }}>
        {shown.map(b => (
          <label key={b.name} title={`${bladeStateLabel(b.state, tr)}${b.project ? ` (${b.project}, job ${b.job})` : ''}`}
            style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '3px 6px', fontSize: 11, borderRadius: 5, cursor: 'pointer',
              border: `1px solid ${picked.has(b.name) ? 'var(--rule-3)' : 'var(--rule-2)'}`,
              background: picked.has(b.name) ? 'var(--accent-soft)' : 'var(--paper)' }}>
            {!readOnly && <input type="checkbox" checked={picked.has(b.name)} onChange={() => toggle(b.name)} style={{ margin: 0 }} />}
            <span style={{ width: 7, height: 7, borderRadius: 4, background: BLADE_COLOR[b.state], flexShrink: 0 }} />
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--ink)' }}>{b.name}</span>
          </label>
        ))}
        {shown.length === 0 && <div style={hint}>{tr('Aucune machine.', 'No machine.')}</div>}
      </div>
    </div>
  )
}
