// TimelinePreview — the panel under the Production Timeline (Tom retakes, after 09).
//
// Click on a shot: its preview (storyboard, animatic, anim ... or everything,
// see previewEdit.ts). Click on a sequence or "Montage": the auto edit of the
// sequence / of the whole edit, played here shot after shot (each shot keeps its
// duration; a shot without media is a gap). "Keyframe" sends the same edit to
// Keyframe Pro as one timeline (licensed API; otherwise the first video only).

import { useEffect, useMemo, useRef, useState } from 'react'
import { Clapperboard, Film, Pause, Play, SkipBack, SkipForward, X } from 'lucide-react'
import { api } from '../../api/client'
import { openInKeyframe } from '../../lib/keyframe'
import type { ProductionShot, ProductionState } from '../../types'
import type { Selection } from './Production'
import './tracking.css'
import {
  buildMontage, pickMedia, previewCandidates, previewSources,
  type MontageClip, type PreviewMedia, type PreviewSource,
} from './previewEdit'

const PLAYABLE = ['mp4', 'webm', 'ogv', 'ogg', 'm4v', 'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'avif', 'svg']
const playable = (file: string) => PLAYABLE.includes(file.split('.').pop()?.toLowerCase() ?? '')

export function TimelinePreview({ project, state, selection, previews, loading, source, setSource, fps, framesOf, montage, setMontage, onPlayingShot }: {
  project:   string
  state:     ProductionState
  selection: Selection
  previews:  Record<string, PreviewMedia[]>
  loading:   boolean
  source:    PreviewSource
  setSource: (s: PreviewSource) => void
  fps:       number
  framesOf:  (shot: ProductionShot) => number
  montage:   { seqId?: string } | null          // null = shot preview
  setMontage: (m: { seqId?: string } | null) => void
  onPlayingShot: (id: string | null) => void
}) {
  const shot = selection.kind === 'shot' ? state.shots.find(s => s.id === selection.id) : undefined
  const seq = selection.kind === 'seq' ? state.sequences.find(s => s.id === selection.id) : undefined
  const shotSeq = shot ? state.sequences.find(s => s.id === shot.seq_id) : undefined

  // Source choices: the stages of the selected shot, else of the whole edit.
  const sources = useMemo(() => {
    const shots = shot ? [shot] : state.shots
    const all = shots.flatMap(s => previewCandidates(state, s))
    const seen = new Set<string>()
    return previewSources(all).filter(o => !seen.has(o.id) && !!seen.add(o.id))
  }, [state, shot])

  const clips = useMemo(
    () => (montage ? buildMontage(state, previews, source, fps, framesOf, montage.seqId) : []),
    [montage, state, previews, source, fps, framesOf],
  )

  const sendToKeyframe = (list: MontageClip[], title: string) => {
    const withMedia = list.filter(c => c.media)
    if (withMedia.length === 0) { void openInKeyframe(project, []); return }
    void openInKeyframe(project, withMedia.map(c => ({
      path: c.media!.abs_path, label: `${c.seq} ${c.shot} · ${c.media!.label} · ${c.media!.version || 'LAST'}`,
    })), { title, siblings: false, fallbackPath: withMedia[0].media!.abs_path })
  }
  const keyframeScope = () => {
    const seqId = montage?.seqId ?? seq?.id
    const list = buildMontage(state, previews, source, fps, framesOf, seqId)
    const name = seqId ? state.sequences.find(s => s.id === seqId)?.name ?? 'Montage' : `${project} montage`
    sendToKeyframe(list, name)
  }

  return (
    <div className="timeline-preview">
      <div className="timeline-preview-head">
        <span className="timeline-preview-title">
          {montage ? `Montage · ${montage.seqId ? state.sequences.find(s => s.id === montage.seqId)?.name ?? '' : 'tout le film'}`
            : shot ? `${shotSeq?.name ?? ''} ${shot.name}` : seq ? seq.name : 'Aperçu'}
        </span>
        <label className="timeline-preview-source">
          <span>Source</span>
          <select value={source} onChange={e => setSource(e.target.value)} aria-label="Source de l’aperçu">
            {sources.map(o => <option key={o.id} value={o.id}>{o.label}</option>)}
          </select>
        </label>
        <span style={{ flex: 1 }} />
        {montage
          ? <button className="timeline-preview-btn" onClick={() => setMontage(null)}><X size={11} /> Fermer le montage</button>
          : <button className="timeline-preview-btn" disabled={state.shots.length === 0}
              onClick={() => setMontage({ seqId: seq?.id ?? shotSeq?.id })}
              title={seq || shotSeq ? `Lire les shots de ${(seq ?? shotSeq)!.name} à la suite` : 'Lire tous les shots à la suite'}>
              <Play size={11} /> Montage{seq || shotSeq ? ` ${(seq ?? shotSeq)!.name}` : ''}
            </button>}
        {!montage && (
          <button className="timeline-preview-btn" disabled={state.shots.length === 0} onClick={() => setMontage({})} title="Lire tous les shots du film à la suite">
            <Play size={11} /> Tout le film
          </button>
        )}
        <button className="timeline-preview-btn" disabled={state.shots.length === 0} onClick={keyframeScope}
          title="Ouvrir le montage dans Keyframe Pro (une timeline, shots dans l’ordre)">
          <Clapperboard size={11} /> Keyframe
        </button>
      </div>

      {montage ? (
        <MontagePlayer project={project} clips={clips} loading={loading} onPlayingShot={onPlayingShot} />
      ) : shot ? (
        <ShotPreview project={project} label={`${shotSeq?.name ?? ''} ${shot.name}`} loading={loading}
          media={pickMedia(previews[shot.id] ?? [], previewCandidates(state, shot), source)}
          empty={source === 'auto' || source === 'all' ? 'Rien de publié en Production pour ce shot'
            : `Rien de publié en ${sources.find(o => o.id === source)?.label ?? source} pour ce shot`} />
      ) : (
        <div className="timeline-preview-empty">{seq ? `${seq.name} : lancez son montage ou choisissez un shot.` : 'Choisissez un shot pour voir son aperçu.'}</div>
      )}
    </div>
  )
}

function ShotPreview({ project, label, media, loading, empty }: {
  project: string; label: string; loading: boolean; empty: string
  media: Array<PreviewMedia & { group: string; label: string }>
}) {
  if (media.length === 0) return <div className="timeline-preview-empty">{loading ? 'Chargement…' : empty}</div>
  return (
    <div className="timeline-preview-grid" data-count={media.length}>
      {media.map(m => (
        <figure key={m.task} className="timeline-preview-card">
          <div className="timeline-preview-media">
            {!playable(m.file)
              ? <div className="timeline-preview-gap"><Film size={16} /> Format non lisible dans FLUX</div>
              : m.kind === 'video'
                ? <video key={m.rel_path + m.version} src={api.refFileUrl(project, m.rel_path, m.file, m.source)} controls muted playsInline preload="metadata" />
                : <img src={api.refFileUrl(project, m.rel_path, m.file, m.source)} alt={`${label} ${m.label}`} />}
          </div>
          <figcaption>
            <strong>{m.label}</strong>
            <span>{m.version || 'LAST'}{m.version_count > 1 ? ` · ${m.version_count} versions` : ''}</span>
            <span style={{ flex: 1 }} />
            {m.kind === 'video' && (
              <button className="timeline-preview-btn" title="Ouvrir dans Keyframe Pro, avec les autres versions"
                onClick={() => void openInKeyframe(project, [{ path: m.abs_path, label: `${label} · ${m.label} · ${m.version || 'LAST'}` }], { title: label, fallbackPath: m.abs_path })}>
                <Clapperboard size={10} /> Keyframe
              </button>
            )}
          </figcaption>
        </figure>
      ))}
    </div>
  )
}

// Shots one after the other. A video plays up to the shot duration (cut if longer);
// an image, a gap or an unreadable file holds for the shot duration.
function MontagePlayer({ project, clips, loading, onPlayingShot }: {
  project: string; clips: MontageClip[]; loading: boolean; onPlayingShot: (id: string | null) => void
}) {
  const [index, setIndex] = useState(0)
  const [playing, setPlaying] = useState(true)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const clip = clips[Math.min(index, clips.length - 1)]
  const isVideo = !!clip?.media && clip.media.kind === 'video' && playable(clip.media.file)
  const next = () => { if (index + 1 < clips.length) setIndex(index + 1); else setPlaying(false) }

  useEffect(() => { onPlayingShot(clip?.shotId ?? null) }, [clip?.shotId])   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => onPlayingShot(null), [])                            // eslint-disable-line react-hooks/exhaustive-deps
  // Image, gap or unreadable: hold for the shot duration.
  useEffect(() => {
    if (!clip || isVideo || !playing) return
    const t = window.setTimeout(next, Math.max(200, clip.seconds * 1000))
    return () => window.clearTimeout(t)
  }, [clip, isVideo, playing])   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const v = videoRef.current
    if (!v) return
    if (playing) void v.play().catch(() => {}); else v.pause()
  }, [playing, index])

  if (clips.length === 0) return <div className="timeline-preview-empty">{loading ? 'Chargement…' : 'Aucun shot dans ce montage'}</div>
  const total = clips.reduce((a, c) => a + c.frames, 0)
  const missing = clips.filter(c => !c.media).length
  return (
    <div className="timeline-montage">
      <div className="timeline-preview-media montage">
        {isVideo ? (
          <video ref={videoRef} key={clip.shotId} src={api.refFileUrl(project, clip.media!.rel_path, clip.media!.file, clip.media!.source)}
            autoPlay={playing} muted playsInline
            onTimeUpdate={e => { if (e.currentTarget.currentTime >= clip.seconds) next() }}
            onEnded={next} onError={next} />
        ) : clip.media && playable(clip.media.file) ? (
          <img key={clip.shotId} src={api.refFileUrl(project, clip.media.rel_path, clip.media.file, clip.media.source)} alt={clip.shot} />
        ) : (
          <div className="timeline-preview-gap">{clip.media ? 'Format non lisible dans FLUX' : 'Rien de publié'}</div>
        )}
      </div>
      <div className="timeline-montage-bar">
        <button className="timeline-preview-btn" aria-label="Shot précédent" onClick={() => setIndex(i => Math.max(0, i - 1))}><SkipBack size={11} /></button>
        <button className="timeline-preview-btn" aria-label={playing ? 'Pause' : 'Lecture'} onClick={() => { if (!playing && index >= clips.length - 1) setIndex(0); setPlaying(p => !p) }}>{playing ? <Pause size={11} /> : <Play size={11} />}</button>
        <button className="timeline-preview-btn" aria-label="Shot suivant" onClick={() => setIndex(i => Math.min(clips.length - 1, i + 1))}><SkipForward size={11} /></button>
        <span className="timeline-montage-label">
          <strong>{clip.seq} {clip.shot}</strong> {clip.media ? `· ${clip.media.label} · ${clip.media.version || 'LAST'}` : ''} · {index + 1}/{clips.length}
        </span>
        {missing > 0 && <span className="timeline-montage-missing">{missing} shot{missing > 1 ? 's' : ''} sans média</span>}
      </div>
      {/* Edit strip: one segment per shot, width = duration. Click = jump there. */}
      <div className="timeline-montage-strip" role="list">
        {clips.map((c, i) => (
          <button key={c.shotId} role="listitem" title={`${c.seq} ${c.shot}${c.media ? ` · ${c.media.label}` : ' · rien de publié'}`}
            className={`${i === index ? 'current' : ''}${c.media ? '' : ' gap'}`}
            style={{ flexGrow: c.frames / Math.max(1, total) }}
            onClick={() => { setIndex(i); setPlaying(true) }} />
        ))}
      </div>
    </div>
  )
}
