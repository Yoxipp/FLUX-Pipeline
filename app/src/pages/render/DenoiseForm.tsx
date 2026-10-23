// DenoiseForm.tsx: denoise an already rendered sequence on the farm (2026-10-23), bottom of the Launch tab.
// A frame, a pattern (####) or the folder: the backend finds the sequence (features/render/image_sequence.py)
// and spools RenderMan denoise_batch tasks into <folder>/denoised. The frames need RenderMan's denoise AOVs.

import { useState } from 'react'
import { toast } from 'sonner'
import { ChevronDown, ChevronRight, FolderOpen, Play } from 'lucide-react'
import { api } from '../../api/client'
import type { RenderSettings } from '../../api/client'
import { Check, Row, btn, card, disabledIf, errMsg, hint, input, lbl, openFolder, useTr, warnText } from './renderUi'

export function DenoiseForm({ project, settings, onSubmitted }: {
  project: string; settings: RenderSettings | null; onSubmitted: () => void
}) {
  const { tr } = useTr()
  const [open, setOpen] = useState(false)   // its own folded box, apart from the render form
  const [path, setPath] = useState('')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [cross, setCross] = useState(settings?.denoise_crossframe ?? true)
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState<{ title: string; output: string; count: number; warnings: string[] } | null>(null)

  const browse = async () => {
    const p = await window.electronAPI?.openFile?.([{ name: 'EXR', extensions: ['exr'] }])
    if (p) setPath(p)
  }
  const launch = async () => {
    if (!path.trim()) return
    setBusy(true)
    try {
      const r = await api.renderDenoise({
        project, path: path.trim(), crossframe: cross,
        ...(start !== '' ? { frame_start: Number(start) } : {}), ...(end !== '' ? { frame_end: Number(end) } : {}),
      })
      setDone({ title: r.title, output: r.output, count: r.count, warnings: [...r.warnings, ...(r.priority_warning ? [r.priority_warning] : [])] })
      toast.success(r.dry_run ? tr("Simulation : job denoise ecrit, rien n'est envoye", 'Simulation: denoise job written, nothing sent')
        : tr(`Denoise envoye (${r.count} images)`, `Denoise sent (${r.count} frames)`), {
        action: { label: tr('Ouvrir le dossier', 'Open folder'), onClick: () => openFolder(r.files.alf) },
      })
      onSubmitted()
    } catch (e) { toast.error(errMsg(e)) }
    finally { setBusy(false) }
  }

  const head = (
    <button type="button" onClick={() => setOpen(o => !o)}
      style={{ display: 'flex', alignItems: 'center', gap: 6, width: '100%', background: 'none', border: 'none', padding: 0, cursor: 'pointer', textAlign: 'left' }}>
      {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
      <span style={{ ...lbl, marginBottom: 0 }}>{tr('Denoiser une sequence deja rendue', 'Denoise an already rendered sequence')}</span>
    </button>
  )
  if (!open) return <div style={card}>{head}</div>

  return (
    <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 10 }}>
      {head}
      <Row label={tr('Sequence (une image, un motif #### ou le dossier)', 'Sequence (one frame, a #### pattern or the folder)')}
        help={tr('RenderMan denoise_batch sur la farm, vers <dossier>/denoised. Les images doivent avoir les AOV de denoise RenderMan.',
          'RenderMan denoise_batch on the farm, into <folder>/denoised. The frames need the RenderMan denoise AOVs.')}>
        <div style={{ display: 'flex', gap: 6 }}>
          <input style={input} value={path} onChange={e => setPath(e.target.value)} placeholder="\\\\serveur\\...\\render\\v003\\SQ01_SH010.1001.exr" />
          <button type="button" style={btn()} onClick={() => void browse()} title={tr('Parcourir', 'Browse')}><FolderOpen size={12} /></button>
        </div>
      </Row>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
        <Row label={tr('Image debut (vide = premiere)', 'Start frame (empty = first)')}>
          <input type="number" style={input} value={start} onChange={e => setStart(e.target.value)} />
        </Row>
        <Row label={tr('Image fin (vide = derniere)', 'End frame (empty = last)')}>
          <input type="number" style={input} value={end} onChange={e => setEnd(e.target.value)} />
        </Row>
      </div>
      <Check label={tr('Entre images (crossframe)', 'Crossframe')} checked={cross} onChange={setCross} />
      <div>
        <button type="button" style={{ ...btn(true), ...disabledIf(busy || !path.trim()) }} onClick={() => void launch()}>
          <Play size={11} strokeWidth={2} />{busy ? tr('Envoi...', 'Sending...') : tr('Lancer le denoise', 'Launch denoise')}
        </button>
      </div>
      {done && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <div style={hint}>{done.title} : {done.count} {tr('images', 'frames')} {'->'} {done.output}</div>
          {done.warnings.map((w, i) => <div key={i} style={warnText}>{w}</div>)}
        </div>
      )}
    </div>
  )
}
