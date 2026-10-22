// previewEdit.ts — what the Timeline shows for a shot, and its auto edit.
//
// A shot's preview is the LAST media of a /ref zone of one of its tasks (what was
// dropped / published in Production). Candidates go from the least to the most
// advanced stage: storyboard, animatic, then the shot departments in their
// Production order (layout, anim, ..., comp), then any other task of the shot.
// "Auto" shows the most advanced stage that has something; a department shows
// only that one; "Tout" shows them all. The auto edit puts every shot of the edit
// in order with its picked media; a shot without media keeps its duration as a
// gap so the timing of the edit stays true.

import type { ProductionShot, ProductionState } from '../../types'
import { effectiveTasks, trackingDepartments } from './tracking'

export interface PreviewMedia {
  task: string; rel_path: string; file: string; ext: string; kind: string
  version: string; version_file: string; version_count: number; abs_path: string
  source?: 'ref' | 'publish'
  versions?: Array<{ version: string; file: string }>     // newest first
}
export interface PreviewCandidate { token: string; group: string; label: string }
export type PreviewSource = 'auto' | 'all' | string      // string = group id

export const EARLY_STAGES: PreviewCandidate[] = [
  { token: 'STORYBOARD', group: 'storyboard', label: 'Storyboard' },
  { token: 'SB',         group: 'storyboard', label: 'Storyboard' },
  { token: 'ANIMATIC',   group: 'animatic',   label: 'Animatique' },
]

/** Every task token worth looking at for this shot, least advanced first. */
export function previewCandidates(state: ProductionState, shot: ProductionShot): PreviewCandidate[] {
  const out: PreviewCandidate[] = [...EARLY_STAGES]
  const seen = new Set(out.map(c => c.token))
  const push = (token: string, group: string, label: string) => {
    const t = token.trim().toUpperCase()
    if (!t || seen.has(t)) return
    seen.add(t); out.push({ token: t, group, label })
  }
  const deps = trackingDepartments(state, 'shot')
  for (const dep of deps) for (const tok of dep.task_tokens) push(tok, dep.id, dep.name)
  for (const task of effectiveTasks(state, shot)) {
    const toks = [task.name, ...task.type_tokens]
    const dep = deps.find(d => toks.some(t => d.task_tokens.map(x => x.toUpperCase()).includes(t.toUpperCase())))
    for (const t of toks) push(t, dep?.id ?? `task:${task.name.toUpperCase()}`, dep?.name ?? task.name)
  }
  return out
}

/** Source choices of the preview selector: Auto, Tout, then each stage once.
 *  With `media`, only the stages that hold something are offered (no empty
 *  Storyboard / Animatique entries when nothing was ever published there). */
export function previewSources(candidates: PreviewCandidate[], media?: PreviewMedia[]): Array<{ id: PreviewSource; label: string }> {
  const present = media ? new Set(media.map(m => m.task.toUpperCase())) : null
  const groups: Array<{ id: string; label: string }> = []
  for (const c of candidates) {
    if (present && !present.has(c.token)) continue
    if (!groups.some(g => g.id === c.group)) groups.push({ id: c.group, label: c.label })
  }
  return [{ id: 'auto', label: 'Auto' }, { id: 'all', label: 'Tout' }, ...groups]
}

/** Stages that hold media for these shots, in stage order (shared across shots). */
export function mediaGroups(state: ProductionState, shots: ProductionShot[], previews: Record<string, PreviewMedia[]>): Array<{ id: string; label: string }> {
  const out: Array<{ id: string; label: string }> = []
  for (const shot of shots) {
    for (const o of previewSources(previewCandidates(state, shot), previews[shot.id] ?? []).slice(2)) {
      if (!out.some(g => g.id === o.id)) out.push(o)
    }
  }
  return out
}

/** The media a shot shows in the edit: its own department choice (shared in the
 *  project, `shot.preview_source`) when that stage holds something, else the
 *  global source ("Tout" has no single media: Auto). */
export function pickShotMedia(state: ProductionState, shot: ProductionShot, previews: Record<string, PreviewMedia[]>, source: PreviewSource, origin: PreviewOrigin = 'auto') {
  const media = previews[shot.id] ?? []
  const candidates = previewCandidates(state, shot)
  const eff = shotOrigin(shot, origin)
  const finish = <T extends PreviewMedia>(m: T | undefined): T | null => (m ? applyVersion(m, shot.preview_version) : null)
  if (shot.preview_source) {
    const own = pickMedia(media, candidates, shot.preview_source, eff)[0]
    if (own) return finish(own)
  }
  return finish(pickMedia(media, candidates, source === 'all' ? 'auto' : source, eff)[0])
}

/** Where the preview media comes from: Auto (ref if present, else publish), Ref, Publish. */
export type PreviewOrigin = 'auto' | 'ref' | 'publish'
export const isOrigin = (v: unknown): v is PreviewOrigin => v === 'auto' || v === 'ref' || v === 'publish'

/** Origin of a shot: its own override (`preview_origin`) else the global one. */
export function shotOrigin(shot: ProductionShot, global: PreviewOrigin): PreviewOrigin {
  return isOrigin(shot.preview_origin) ? shot.preview_origin : global
}

/** Same media pointing at version `version` (vNNN) instead of LAST. Unknown or
 *  missing version: the media unchanged (LAST). */
export function applyVersion<T extends PreviewMedia>(m: T, version?: string): T {
  if (!version) return m
  const v = (m.versions ?? []).find(x => x.version === version)
  if (!v) return m
  const abs = m.abs_path.endsWith(m.file) ? m.abs_path.slice(0, m.abs_path.length - m.file.length) + v.file : m.abs_path
  return { ...m, file: v.file, version: v.version, version_file: v.file, abs_path: abs }
}

/** Media of a shot for a source, in stage order (Auto: the most advanced one).
 *  A task can hold a ref entry and a publish entry: `origin` keeps one per task
 *  (auto: ref first, else publish). */
export function pickMedia(media: PreviewMedia[], candidates: PreviewCandidate[], source: PreviewSource, origin: PreviewOrigin = 'auto'): Array<PreviewMedia & { group: string; label: string }> {
  const rank = new Map(candidates.map((c, i) => [c.token, i]))
  const byTask = new Map<string, PreviewMedia>()
  for (const m of media) {
    const key = m.task.toUpperCase()
    const kind = m.source ?? 'ref'
    if (origin !== 'auto' && kind !== origin) continue
    const cur = byTask.get(key)
    if (!cur || (origin === 'auto' && kind === 'ref' && (cur.source ?? 'ref') !== 'ref')) byTask.set(key, m)
  }
  const tagged = [...byTask.values()]
    .filter(m => rank.has(m.task.toUpperCase()))
    .map(m => { const c = candidates[rank.get(m.task.toUpperCase())!]; return { ...m, group: c.group, label: c.label } })
    .sort((a, b) => rank.get(a.task.toUpperCase())! - rank.get(b.task.toUpperCase())!)
  if (source === 'all') return tagged
  if (source === 'auto') return tagged.length ? [tagged[tagged.length - 1]] : []
  return tagged.filter(m => m.group === source).slice(-1)
}

export interface MontageClip {
  shotId: string; seq: string; shot: string
  frames: number; seconds: number
  media: (PreviewMedia & { group: string; label: string }) | null
}

/** Shots of the edit in order (sequence order, then shot order), each with its media. */
export function buildMontage(state: ProductionState, previews: Record<string, PreviewMedia[]>, source: PreviewSource,
  fps: number, framesOf: (shot: ProductionShot) => number, onlySeqId?: string, origin: PreviewOrigin = 'auto'): MontageClip[] {
  const seqs = [...state.sequences].sort((a, b) => a.order - b.order).filter(s => !onlySeqId || s.id === onlySeqId)
  const out: MontageClip[] = []
  for (const seq of seqs) {
    const shots = state.shots.filter(s => s.seq_id === seq.id).sort((a, b) => a.order - b.order)
    for (const shot of shots) {
      const frames = framesOf(shot)
      out.push({ shotId: shot.id, seq: seq.name, shot: shot.name, frames, seconds: frames / (fps > 0 ? fps : 24),
        media: pickShotMedia(state, shot, previews, source, origin) })
    }
  }
  return out
}
