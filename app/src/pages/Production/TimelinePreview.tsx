// TimelinePreview — the panel under the Production Timeline (Tom retakes, after 09).
//
// Click on a shot: its preview (storyboard, animatic, anim ... or everything,
// see previewEdit.ts). Click on a sequence or "Montage": the auto edit of the
// sequence / of the whole edit, played here shot after shot (each shot keeps its
// duration; a shot without media is a gap). "Keyframe" sends the same edit to
// Keyframe Pro as one timeline (licensed API; otherwise the first video only).
// Each shot can pick its own department for the edit ("Plan", shared in the
// project); "Exporter" writes the edit as one H.264 .mov plus media + .otio/.edl.

import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Clapperboard, Download, Film, Pause, Play, SkipBack, SkipForward, X } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '../../api/client'
import { openInKeyframe } from '../../lib/keyframe'
import type { ProductionShot, ProductionState } from '../../types'
import type { Selection } from './Production'
import './tracking.css'
import {
  applyVersion, buildMontage, mediaGroups, pickMedia, previewCandidates, shotOrigin,
  type MontageClip, type PreviewMedia, type PreviewOrigin, type PreviewSource,
} from './previewEdit'

const ORIGIN_LABELS: Array<{ id: PreviewOrigin; label: string }> = [
  { id: 'auto', label: 'Auto' }, { id: 'ref', label: 'Ref' }, { id: 'publish', label: 'Publish' },
]

// mov: H.264 playblasts play in Chromium; a codec it cannot decode (ProRes) ends in onError.
const PLAYABLE = ['mp4', 'mov', 'webm', 'ogv', 'ogg', 'm4v', 'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'avif', 'svg']
const playable = (file: string) => PLAYABLE.includes(file.split('.').pop()?.toLowerCase() ?? '')

export function TimelinePreview({ project, state, selection, previews, loading, source, setSource, origin, setOrigin, rev, fps, framesOf, montage, setMontage, onPlayingShot, setShotSource, setShotPreview }: {
  project:   string
  state:     ProductionState
  selection: Selection
  previews:  Record<string, PreviewMedia[]>
  loading:   boolean
  source:    PreviewSource
  setSource: (s: PreviewSource) => void
  rev:       number                              // bumps when a /ref zone changes (cache buster)
  origin:    PreviewOrigin
  setOrigin: (o: PreviewOrigin) => void
  fps:      number
  framesOf:  (shot: ProductionShot) => number
  montage:   { seqId?: string } | null          // null = shot preview
  setMontage: (m: { seqId?: string } | null) => void
  onPlayingShot: (id: string | null) => void
  setShotSource: (shotId: string, group: string | null) => void   // per-shot department of the edit (shared)
  setShotPreview: (shotId: string, patch: { preview_origin?: PreviewOrigin; preview_version?: string }) => void   // per-shot origin / version (shared)
}) {
  const shot = selection.kind === 'shot' ? state.shots.find(s => s.id === selection.id) : undefined
  const seq = selection.kind === 'seq' ? state.sequences.find(s => s.id === selection.id) : undefined
  const shotSeq = shot ? state.sequences.find(s => s.id === shot.seq_id) : undefined

  // Source choices: only the stages that hold media, for the selected shot, else
  // for the whole edit (no Storyboard / Animatique entry when nothing is there).
  const sources = useMemo(() => {
    const groups = mediaGroups(state, shot ? [shot] : state.shots, previews)
    const out: Array<{ id: PreviewSource; label: string }> = [{ id: 'auto', label: 'Auto' }, { id: 'all', label: 'Tout' }, ...groups]
    if (!out.some(o => o.id === source)) out.push({ id: source, label: `${source} (vide)` })
    return out
  }, [state, shot, previews, source])
  const groupsOf = (s: ProductionShot) => mediaGroups(state, [s], previews)
  // Versions offered for a shot: those of the media it shows (its source + origin), newest first.
  const versionsOf = (s: ProductionShot) => {
    const media = pickMedia(previews[s.id] ?? [], previewCandidates(state, s), s.preview_source || (source === 'all' ? 'auto' : source), shotOrigin(s, origin))[0]
    return media?.versions ?? []
  }
  const shotPickers = (s: ProductionShot) => (<>
    <ShotSourcePicker shot={s} groups={groupsOf(s)} onPick={g => setShotSource(s.id, g)} />
    <ShotOriginPicker shot={s} versions={versionsOf(s)} onPick={patch => setShotPreview(s.id, patch)} />
  </>)

  const clips = useMemo(
    () => (montage ? buildMontage(state, previews, source, fps, framesOf, montage.seqId, origin) : []),
    [montage, state, previews, source, origin, fps, framesOf],
  )

  const sendToKeyframe = (list: MontageClip[], title: string) => {
    const withMedia = list.filter(c => c.media)
    if (withMedia.length === 0) { void openInKeyframe(project, []); return }
    void openInKeyframe(project, withMedia.map(c => ({
      path: c.media!.abs_path, label: `${c.seq} ${c.shot} · ${c.media!.label} · ${c.media!.version || 'LAST'}`,
    })), { title, siblings: false, fallbackPath: withMedia[0].media!.abs_path })
  }
  // Montage open: its scope; else the selected sequence (or the shot's), else the film.
  const scope = () => {
    const seqId = montage ? montage.seqId : (seq?.id ?? shotSeq?.id)
    const list = buildMontage(state, previews, source, fps, framesOf, seqId, origin)
    const name = seqId ? state.sequences.find(s => s.id === seqId)?.name ?? 'Montage' : `${project} montage`
    return { list, name }
  }
  const keyframeScope = () => { const { list, name } = scope(); sendToKeyframe(list, name) }

  const [exporting, setExporting] = useState(false)
  const exportScope = async () => {
    const { list, name } = scope()
    const dest = await window.electronAPI?.openFolder()
    if (!dest) return
    setExporting(true)
    const id = toast.loading(`Export du montage ${name} (${list.length} plans)…`)
    try {
      const r = await api.exportMontage(project, {
        name, dest_dir: dest, fps, mov: true, folder: true,
        clips: list.map(c => ({ seq: c.seq, shot: c.shot, frames: c.frames,
          media: c.media ? { task: c.media.task, label: c.media.label, rel_path: c.media.rel_path, file: c.media.file, source: c.media.source } : null })),
      })
      toast.success(r.mov ? 'Montage exporté (.mov + timeline)' : 'Montage exporté (timeline seulement)', {
        id, description: r.dir, action: { label: 'Ouvrir', onClick: () => void window.electronAPI?.openPath(r.dir) },
      })
      for (const w of r.warnings) toast.warning(w)
    } catch (e) {
      toast.error(`Export impossible : ${e instanceof Error ? e.message : String(e)}`, { id })
    } finally { setExporting(false) }
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
        <label className="timeline-preview-source" title="Origine des médias : Auto (ref sinon publish), Ref (dépôt /ref), Publish (publiés)">
          <span>Origine</span>
          <select value={origin} onChange={e => setOrigin(e.target.value as PreviewOrigin)} aria-label="Origine de l’aperçu">
            {ORIGIN_LABELS.map(o => <option key={o.id} value={o.id}>{o.label}</option>)}
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
        <button className="timeline-preview-btn" disabled={state.shots.length === 0 || exporting} onClick={() => void exportScope()}
          title="Exporter le montage : un .mov H.264 + les médias et une timeline .otio / .edl (Resolve, Premiere)">
          <Download size={11} /> {exporting ? 'Export…' : 'Exporter'}
        </button>
      </div>

      {montage ? (
        <MontagePlayer project={project} rev={rev} clips={clips} loading={loading} onPlayingShot={onPlayingShot}
          shotPicker={c => {
            const s = state.shots.find(x => x.id === c.shotId)
            return s ? shotPickers(s) : null
          }} />
      ) : shot ? (<>
        <div className="timeline-preview-shotpick">
          {shotPickers(shot)}
        </div>
        <ShotPreview project={project} rev={rev} label={`${shotSeq?.name ?? ''} ${shot.name}`} loading={loading}
          media={pickMedia(previews[shot.id] ?? [], previewCandidates(state, shot), source, shotOrigin(shot, origin))
            .map(m => applyVersion(m, shot.preview_version))}
          empty={source === 'auto' || source === 'all' ? 'Rien de publié en Production pour ce shot'
            : `Rien de publié en ${sources.find(o => o.id === source)?.label ?? source} pour ce shot`} />
      </>) : (
        <div className="timeline-preview-empty">{seq ? `${seq.name} : lancez son montage ou choisissez un shot.` : 'Choisissez un shot pour voir son aperçu.'}</div>
      )}
    </div>
  )
}

// Department this shot uses in the edit, whatever the global source (shared in
// the project). Only the stages that hold media for the shot are offered.
function ShotSourcePicker({ shot, groups, onPick }: {
  shot: ProductionShot; groups: Array<{ id: string; label: string }>; onPick: (group: string | null) => void
}) {
  const value = shot.preview_source ?? ''
  const missing = !!value && !groups.some(g => g.id === value)
  return (
    <label className="timeline-preview-source" title="Département utilisé pour ce plan dans le montage (partagé avec l'équipe)">
      <span>Plan</span>
      <select value={value} onChange={e => onPick(e.target.value || null)} aria-label={`Département de ${shot.name} dans le montage`}>
        <option value="">Source globale</option>
        {groups.map(g => <option key={g.id} value={g.id}>{g.label}</option>)}
        {missing && <option value={value}>{value} (vide, source globale)</option>}
      </select>
    </label>
  )
}

// Origin and version this shot uses in the edit (shared in the project). Missing
// = inherit the global origin / LAST. A version absent from the list falls back to LAST.
function ShotOriginPicker({ shot, versions, onPick }: {
  shot: ProductionShot; versions: Array<{ version: string; file: string }>
  onPick: (patch: { preview_origin?: PreviewOrigin; preview_version?: string }) => void
}) {
  const origin = shot.preview_origin ?? ''
  const version = shot.preview_version ?? ''
  const missing = !!version && !versions.some(v => v.version === version)
  return (<>
    <label className="timeline-preview-source" title="Origine des médias de ce plan (partagé avec l'équipe)">
      <span>Origine</span>
      <select value={origin} onChange={e => onPick({ preview_origin: (e.target.value || undefined) as PreviewOrigin | undefined, preview_version: undefined })}
        aria-label={`Origine de ${shot.name} dans le montage`}>
        <option value="">Origine globale</option>
        {ORIGIN_LABELS.map(o => <option key={o.id} value={o.id}>{o.label}</option>)}
      </select>
    </label>
    <label className="timeline-preview-source" title="Version utilisée pour ce plan (LAST par défaut)">
      <span>Version</span>
      <select value={version} onChange={e => onPick({ preview_version: e.target.value || undefined })}
        aria-label={`Version de ${shot.name} dans le montage`}>
        <option value="">LAST</option>
        {versions.map(v => <option key={v.version} value={v.version}>{v.version}</option>)}
        {missing && <option value={version}>{version} (absente, LAST)</option>}
      </select>
    </label>
  </>)
}

function ShotPreview({ rev, project, label, media, loading, empty }: {
  rev: number; project: string; label: string; loading: boolean; empty: string
  media: Array<PreviewMedia & { group: string; label: string }>
}) {
  const [failed, setFailed] = useState<Set<string>>(new Set())
  if (media.length === 0) return <div className="timeline-preview-empty">{loading ? 'Chargement…' : empty}</div>
  return (
    <div className="timeline-preview-grid" data-count={media.length}>
      {media.map(m => (
        <figure key={m.task} className="timeline-preview-card">
          <div className="timeline-preview-media">
            {!playable(m.file) || failed.has(m.rel_path + m.file)
              ? <div className="timeline-preview-gap"><Film size={16} /> Format non lisible dans FLUX (Keyframe)</div>
              : m.kind === 'video'
                ? <video key={m.rel_path + m.version} src={api.refFileUrl(project, m.rel_path, m.file, m.source, rev)} controls muted playsInline preload="metadata"
                    onError={() => setFailed(f => new Set(f).add(m.rel_path + m.file))} />
                : <img src={api.refFileUrl(project, m.rel_path, m.file, m.source, rev)} alt={`${label} ${m.label}`} />}
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
function MontagePlayer({ rev, project, clips, loading, onPlayingShot, shotPicker }: {
  rev: number; project: string; clips: MontageClip[]; loading: boolean; onPlayingShot: (id: string | null) => void
  shotPicker: (clip: MontageClip) => ReactNode
}) {
  const [index, setIndex] = useState(0)
  const [playing, setPlaying] = useState(true)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const holdRef = useRef<number | undefined>(undefined)
  // Videos the browser could not decode: shown as unreadable, held like a gap.
  const [failed, setFailed] = useState<Set<string>>(new Set())
  const clip = clips[Math.min(index, clips.length - 1)]
  const isVideo = !!clip?.media && clip.media.kind === 'video' && playable(clip.media.file) && !failed.has(clip.shotId)
  const next = () => { if (index + 1 < clips.length) setIndex(index + 1); else setPlaying(false) }
  useEffect(() => () => window.clearTimeout(holdRef.current), [index])
  // A video shorter than its shot holds its last frame up to the shot duration (as the export).
  const onVideoEnded = (v: HTMLVideoElement) => {
    const rest = clip.seconds - v.currentTime
    if (rest > 0.05) holdRef.current = window.setTimeout(next, rest * 1000); else next()
  }

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
          <video ref={videoRef} key={clip.shotId} src={api.refFileUrl(project, clip.media!.rel_path, clip.media!.file, clip.media!.source, rev)}
            autoPlay={playing} muted playsInline
            onTimeUpdate={e => { if (e.currentTarget.currentTime >= clip.seconds) next() }}
            onEnded={e => onVideoEnded(e.currentTarget)} onError={() => setFailed(f => new Set(f).add(clip.shotId))} />
        ) : clip.media && playable(clip.media.file) ? (
          <img key={clip.shotId} src={api.refFileUrl(project, clip.media.rel_path, clip.media.file, clip.media.source, rev)} alt={clip.shot} />
        ) : (
          <div className="timeline-preview-gap">{clip.media ? 'Format non lisible dans FLUX (Keyframe ou Exporter)' : 'Rien de publié'}</div>
        )}
      </div>
      <div className="timeline-montage-bar">
        <button className="timeline-preview-btn" aria-label="Shot précédent" onClick={() => setIndex(i => Math.max(0, i - 1))}><SkipBack size={11} /></button>
        <button className="timeline-preview-btn" aria-label={playing ? 'Pause' : 'Lecture'} onClick={() => { if (!playing && index >= clips.length - 1) setIndex(0); setPlaying(p => !p) }}>{playing ? <Pause size={11} /> : <Play size={11} />}</button>
        <button className="timeline-preview-btn" aria-label="Shot suivant" onClick={() => setIndex(i => Math.min(clips.length - 1, i + 1))}><SkipForward size={11} /></button>
        <span className="timeline-montage-label">
          <strong>{clip.seq} {clip.shot}</strong> {clip.media ? `· ${clip.media.label} · ${clip.media.version || 'LAST'}` : ''} · {index + 1}/{clips.length}
        </span>
        {shotPicker(clip)}
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
