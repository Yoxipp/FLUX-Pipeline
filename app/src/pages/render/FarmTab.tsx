// FarmTab.tsx: who uses the farm right now. Blade states, team cap, usage per team (Tractor project)
// and per room. Source: running commands on the engine (backend /render/farm), polled every 30 s.

import { useMemo, useState } from 'react'
import type { RenderBladeState, RenderFarm } from '../../api/client'
import { Activity, Clock, Layers, Users } from 'lucide-react'
import { MachinePicker } from './MachinePicker'
import { BLADE_COLOR, Bar, Section, bladeStateLabel, card, hint, roomLabel, useTr, warnText } from './renderUi'

const STATES: RenderBladeState[] = ['free', 'busy', 'nimby', 'offline']

export function FarmTab({ farm }: { farm: RenderFarm | null }) {
  const { tr } = useTr()
  const [showList, setShowList] = useState(false)

  const byRoom = useMemo(() => {
    const out: Record<string, Record<RenderBladeState, number>> = {}
    for (const b of farm?.blades ?? []) {
      if (b.state === 'offline') continue
      const r = (out[b.room] ??= { free: 0, busy: 0, nimby: 0, offline: 0 })
      r[b.state] += 1
    }
    return Object.entries(out).sort((a, b) => a[0].localeCompare(b[0]))
  }, [farm])

  if (!farm) return <div style={hint}>{tr('Chargement...', 'Loading...')}</div>
  if (farm.dry_run && farm.blades.length === 0) {
    return <div style={hint}>{tr('Mode simulation : pont Tractor non configure.', 'Simulation mode: Tractor bridge not configured.')}</div>
  }
  const c = farm.counts
  const teams = Object.entries(farm.active_by_project).sort((a, b) => b[1] - a[1])
  const maxTeam = Math.max(1, ...teams.map(t => t[1]))
  const cap = farm.team_cap

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 8 }}>
        {[{ k: 'alive', label: tr('Allumes', 'Alive'), color: 'var(--ink)' },
          ...STATES.map(s => ({ k: s, label: bladeStateLabel(s, tr), color: BLADE_COLOR[s] }))].map(t => (
          <div key={t.k} style={{ ...card, padding: '8px 10px' }}>
            <div style={{ fontSize: 18, fontWeight: 700, color: t.color }}>{c[t.k as keyof typeof c] ?? 0}</div>
            <div style={hint}>{t.label}</div>
          </div>
        ))}
      </div>

      <Section title={tr('Mon equipe', 'My team')}>
        <div style={{ fontSize: 11.5, color: 'var(--ink-2)', display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}><Users size={12} /><b>{farm.tractor_project}</b></span>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }} title={tr('Blades en cours', 'Blades running')}>
            <Activity size={12} />{farm.active_by_project[farm.tractor_project] ?? 0}
          </span>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, color: 'var(--ink-3)' }} title={tr('Horaires', 'Hours')}>
            <Clock size={12} />{farm.schedule.enabled ? `${farm.schedule.start}-${farm.schedule.end}` : '24/24'}
          </span>
        </div>
        {cap.enabled ? (
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 11.5 }}>
              <span style={{ width: 140, color: 'var(--ink-2)', display: 'inline-flex', alignItems: 'center', gap: 4 }}><Layers size={12} />{tr('Plafond', 'Cap')}</span>
              <Bar value={cap.used} max={cap.slots} color={cap.used > cap.slots ? 'var(--warn)' : 'var(--accent)'} />
              <span style={{ color: 'var(--ink-3)', minWidth: 50, textAlign: 'right' }}>{cap.used} / {cap.slots}</span>
            </div>
            {Object.keys(cap.targets).length > 0 && (
              <div style={hint}>{Object.entries(cap.targets).map(([j, n]) => `#${j} : ${n}`).join('   ')}</div>
            )}            {cap.errors.map((e, i) => <div key={i} style={warnText}>{e}</div>)}
          </>
        ) : (
          <div style={hint}>{tr('Pas de plafond', 'No cap')}</div>
        )}
      </Section>

      <Section title={tr('Par equipe (projet Tractor)', 'Per team (Tractor project)')}>
        {teams.length === 0 && <div style={hint}>{tr('La farm est libre.', 'The farm is idle.')}</div>}
        {teams.map(([name, n]) => {
          const own = name === farm.tractor_project
          return (
            <div key={name} style={{ display: 'grid', gridTemplateColumns: '140px 1fr 80px', gap: 10, alignItems: 'center', fontSize: 11.5 }}>
              <div style={{ color: own ? 'var(--accent-hi)' : 'var(--ink-2)', fontWeight: own ? 700 : undefined }}>{name}</div>
              <Bar value={n} max={maxTeam} color={own ? 'var(--accent)' : 'var(--ink-4)'} />
              <div style={{ color: 'var(--ink-3)', textAlign: 'right' }}>{n} ({c.alive ? Math.round((n / c.alive) * 100) : 0} %)</div>
            </div>
          )
        })}
      </Section>

      <Section title={tr('Par salle', 'Per room')}>
        {byRoom.map(([room, n]) => {
          const total = n.free + n.busy + n.nimby
          return (
            <div key={room} style={{ display: 'grid', gridTemplateColumns: '90px 1fr 120px', gap: 10, alignItems: 'center', fontSize: 11.5 }}>
              <div style={{ color: 'var(--ink-2)' }}>{roomLabel(room, tr)}</div>
              <div style={{ display: 'flex', height: 8, borderRadius: 4, overflow: 'hidden', background: 'var(--rule-2)' }}>
                {(['busy', 'nimby', 'free'] as const).map(s => (
                  <div key={s} style={{ width: `${total ? (n[s] / total) * 100 : 0}%`, background: BLADE_COLOR[s] }} />
                ))}
              </div>
              <div style={{ color: 'var(--ink-3)', textAlign: 'right' }}>{tr(`${n.free} libres / ${total}`, `${n.free} free / ${total}`)}</div>
            </div>
          )
        })}
        <button type="button" onClick={() => setShowList(s => !s)}
          style={{ width: '100%', textAlign: 'left', background: 'none', border: 'none', padding: '2px 0', cursor: 'pointer', color: 'var(--accent-hi)', fontSize: 11.5 }}>
          {showList ? tr('Masquer les machines', 'Hide machines') : tr('Voir les machines', 'Show machines')}
        </button>
        {showList && <MachinePicker blades={farm.blades} selected={[]} onChange={() => undefined} hideOffline={false} readOnly />}
      </Section>
    </div>
  )
}
