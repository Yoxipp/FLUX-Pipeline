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
export function pickShotMedia(state: ProductionState, shot: ProductionShot, previews: Record<string, PreviewMedia[]>, source: PreviewSource) {
  const media = previews[shot.id] ?? []
  const candidates = previewCandidates(state, shot)
  if (shot.preview_source) {
    const own = pickMedia(media, candidates, shot.preview_source)[0]
    if (own) return own
  }
  return pickMedia(media, candidates, source === 'all' ? 'auto' : source)[0] ?? null
}

/** Media of a shot for a source, in stage order (Auto: the most advanced one). */
export function pickMedia(media: PreviewMedia[], candidates: PreviewCandidate[], source: PreviewSource): Array<PreviewMedia & { group: string; label: string }> {
  const rank = new Map(candidates.map((c, i) => [c.token, i]))
  const tagged = media
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
  fps: number, framesOf: (shot: ProductionShot) => number, onlySeqId?: string): MontageClip[] {
  const seqs = [...state.sequences].sort((a, b) => a.order - b.order).filter(s => !onlySeqId || s.id === onlySeqId)
  const out: MontageClip[] = []
  for (const seq of seqs) {
    const shots = state.shots.filter(s => s.seq_id === seq.id).sort((a, b) => a.order - b.order)
    for (const shot of shots) {
      const frames = framesOf(shot)
      out.push({ shotId: shot.id, seq: seq.name, shot: shot.name, frames, seconds: frames / (fps > 0 ? fps : 24),
        media: pickShotMedia(state, shot, previews, source) })
    }
  }
  return out
}
