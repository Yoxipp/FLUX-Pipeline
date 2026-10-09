// Tokens offered by the Calendar "Link" field (2026-10-09): the link is picked from
// project tokens, never typed freely, so Production can match it back to a shot / asset.
// Format kept for the parsers (Production/shotCalendar.ts calendarLinksShot,
// Production/taskPriority.ts entityDeadline): "SEQ SHOT TASK" for a shot,
// "CLASS ASSET TASK" for an asset, tokens separated by spaces.
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { ProductionState } from '../types'

export interface CalendarLinkTokens {
  loaded: boolean
  production: ProductionState | null
  taskTypes: string[]          // TYPE token keys of the project, upper case
}

const EMPTY: CalendarLinkTokens = { loaded: false, production: null, taskTypes: [] }

export function useCalendarLinkTokens(project: string): CalendarLinkTokens {
  const [data, setData] = useState<CalendarLinkTokens>(EMPTY)
  useEffect(() => {
    if (!project) { setData(EMPTY); return }
    let alive = true
    setData(EMPTY)
    Promise.all([
      api.getProduction(project).then(r => r.production).catch(() => null),
      api.getTokens(project).then(r => Object.keys(r.tokens?.TYPE ?? {})).catch(() => [] as string[]),
    ]).then(([production, types]) => {
      if (!alive) return
      setData({ loaded: true, production, taskTypes: [...new Set(types.map(t => t.toUpperCase()))].sort() })
    })
    return () => { alive = false }
  }, [project])
  return data
}

export type LinkKind = 'none' | 'shot' | 'asset'
export interface LinkSlots { kind: LinkKind; seqId: string; shotId: string; assetId: string; task: string }
export const EMPTY_SLOTS: LinkSlots = { kind: 'none', seqId: '', shotId: '', assetId: '', task: '' }

const up = (s: string) => s.trim().toUpperCase()

/** Builds the link text, in the order the Production parsers expect. */
export function composeLink(state: ProductionState | null, s: LinkSlots): string {
  if (!state || s.kind === 'none') return s.task
  if (s.kind === 'shot') {
    const seq = state.sequences.find(q => q.id === s.seqId)?.name ?? ''
    const shot = state.shots.find(q => q.id === s.shotId && q.seq_id === s.seqId)?.name ?? ''
    return [seq, shot, s.task].filter(Boolean).join(' ')
  }
  const asset = state.assets.find(a => a.id === s.assetId)
  return [asset?.class ?? '', asset?.name ?? '', s.task].filter(Boolean).join(' ')
}

/** Tries to read a link text back into slots. null when it does not match the project. */
export function parseLink(state: ProductionState | null, taskTypes: string[], link: string): LinkSlots | null {
  const words = link.split(/\s+/).filter(Boolean)
  if (!words.length) return { ...EMPTY_SLOTS }
  if (!state) return null
  const rest = (n: number) => words.slice(n).join(' ')
  const taskOk = (t: string) => !t || !t.includes(' ')
  const seq = state.sequences.find(q => up(q.name) === up(words[0]))
  if (seq) {
    const shot = words[1] ? state.shots.find(q => q.seq_id === seq.id && up(q.name) === up(words[1])) : undefined
    if (words[1] && !shot) return null
    const task = shot ? rest(2) : ''
    if (!taskOk(task)) return null
    return { ...EMPTY_SLOTS, kind: 'shot', seqId: seq.id, shotId: shot?.id ?? '', task: up(task) }
  }
  const asset = state.assets.find(a => up(a.class) === up(words[0]) && up(a.name) === up(words[1] ?? ''))
    ?? state.assets.find(a => up(a.name) === up(words[0]))
  if (asset) {
    const task = rest(up(asset.name) === up(words[0]) ? 1 : 2)
    if (!taskOk(task)) return null
    return { ...EMPTY_SLOTS, kind: 'asset', assetId: asset.id, task: up(task) }
  }
  if (words.length === 1 && taskTypes.includes(up(words[0]))) return { ...EMPTY_SLOTS, task: up(words[0]) }
  return null
}

/** Task tokens for the picked entity: project TYPE tokens + the entity's own tasks. */
export function taskOptions(state: ProductionState | null, taskTypes: string[], s: LinkSlots): string[] {
  const out = new Set(taskTypes)
  if (state) {
    const seq = state.sequences.find(q => q.id === s.seqId)
    const shot = state.shots.find(q => q.id === s.shotId)
    const asset = state.assets.find(a => a.id === s.assetId)
    const tasks = s.kind === 'shot' ? [...(shot?.tasks ?? []), ...(!shot || shot.inherit_tasks ? seq?.tasks ?? [] : [])]
      : s.kind === 'asset' ? asset?.tasks ?? [] : []
    for (const t of tasks) {
      const tok = up(t.type_tokens?.[0] ?? t.name)
      if (tok && !tok.includes(' ')) out.add(tok)
    }
  }
  return [...out].sort()
}
