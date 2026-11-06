// Shotboard.tsx — the shotboard object of the board (ADR 0083). One row per sequence, one
// column per shot, READ live from Production (nothing is written when a shot arrives: the
// grid redraws). Each cell shows a still of the shot's media, picked like the Timeline
// (previewEdit.ts: the most advanced stage, ref or publish, the shot's own overrides),
// first frame by default; a slider picks another one, a second still can sit beside it.
// What a cell keeps lives in the board as one `shot` record (target = the shotboard,
// ref = shot:<seq>/<shot>): `frame_at`, `frame_at2` (null = one still), `text` (idea).
// The idea can be sent to Production as a 'retake' comment of a task of the shot
// (POST /production/<p>/retake); the shot's retakes are listed under it, read only.

import { createContext, memo, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { Plus, Send, X } from 'lucide-react'
import { api } from '../../../api/client'
import type { ProductionComment, ProductionShot, ProductionState } from '../../../types'
import { effectiveTasks } from '../../Production/tracking'
import { pickShotMedia, previewCandidates, type PreviewMedia } from '../../Production/previewEdit'
import { useTr } from '../../flow_editor/useTr'
import { grabFrame, peekFrame, type MediaKind } from './frameGrab'
import { textLocked, type Box, type Item } from './model'

// Layout, in board units.
export const SB = { head: 120, cellW: 240, cellH: 320, gap: 8, imgH: 126 }
const REFRESH_MS = 60_000   // media deposited without a Production change
const INK = 'oklch(25% 0.02 250)'

export interface ShotRow { seq: string; label?: string; shots: ProductionShot[] }

export function shotRows(state: ProductionState | null | undefined): ShotRow[] {
  if (!state) return []
  return [...state.sequences].sort((a, b) => a.order - b.order).map(seq => ({
    seq: seq.name, label: seq.label,
    shots: state.shots.filter(s => s.seq_id === seq.id).sort((a, b) => a.order - b.order),
  }))
}

export function shotboardSize(rows: ShotRow[]) {
  const cols = Math.max(1, ...rows.map(r => r.shots.length))
  return { w: SB.head + cols * (SB.cellW + SB.gap) + SB.gap, h: Math.max(1, rows.length) * (SB.cellH + SB.gap) + SB.gap }
}

export const shotRef = (seq: string, shot: string) => `shot:${seq}/${shot}`
export const cellKey = (target: string, ref: string) => `${target}|${ref.toUpperCase()}`

/** One cell per (shotboard, shot): two authors creating it at once give two records, the
 *  most recently changed one wins. */
export function shotCells(items: Item[]): Map<string, Item> {
  const out = new Map<string, Item>()
  for (const it of items) {
    if (it.type !== 'shot' || !it.target || !it.ref) continue
    const k = cellKey(it.target, it.ref)
    const cur = out.get(k)
    if (!cur || String(it._at ?? '') > String(cur._at ?? '')) out.set(k, it)
  }
  return out
}

/** Media of every shot (one request, like the Timeline), again every minute while shown. */
export function useShotPreviews(project: string | undefined, state: ProductionState | null | undefined, enabled: boolean) {
  const [previews, setPreviews] = useState<Record<string, PreviewMedia[]>>({})
  const query = useMemo(() => !state ? [] : state.shots.map(shot => ({
    id: shot.id, seq: state.sequences.find(s => s.id === shot.seq_id)?.name ?? '', shot: shot.name,
    tasks: previewCandidates(state, shot).map(c => c.token),
  })).filter(q => q.seq), [state])
  const key = JSON.stringify(query.map(q => [q.id, q.seq, q.shot, q.tasks]))
  useEffect(() => {
    if (!project || !enabled || !query.length) return
    let alive = true
    const load = () => api.getShotPreviews(project, query.map(({ seq, shot, tasks }) => ({ seq, shot, tasks })))
      .then(r => {
        if (!alive) return
        const map: Record<string, PreviewMedia[]> = {}
        r.shots.forEach((row, i) => { map[query[i].id] = row.media })
        setPreviews(map)
      })
      .catch(() => { /* keep the last media */ })
    void load()
    const t = setInterval(load, REFRESH_MS)
    return () => { alive = false; clearInterval(t) }
  }, [project, enabled, key])   // eslint-disable-line react-hooks/exhaustive-deps
  return previews
}

export interface ShotboardData {
  project?: string
  state: ProductionState | null
  rows: ShotRow[]
  previews: Record<string, PreviewMedia[]>
  cells: Map<string, Item>
  canEdit: boolean
  setCell: (board: Item, ref: string, fields: Record<string, unknown>) => void
  sendRetake: (seq: string, shot: string, task: string, text: string) => Promise<boolean>
}
export const ShotboardContext = createContext<ShotboardData | null>(null)

function mediaOf(d: ShotboardData, shot: ProductionShot) {
  if (!d.state || !d.project) return null
  const m = pickShotMedia(d.state, shot, d.previews, 'auto', 'auto')
  if (!m) return null
  const kind: MediaKind = m.kind === 'image' ? 'image' : 'video'
  return { m, kind, url: api.refFileUrl(d.project, m.rel_path, m.file, m.source) }
}

function retakesOf(shot: ProductionShot): Array<ProductionComment & { task: string }> {
  const out: Array<ProductionComment & { task: string }> = []
  for (const [task, detail] of Object.entries(shot.task_details ?? {})) {
    for (const c of detail.comments ?? []) if (c.kind === 'retake') out.push({ ...c, task: task.split('|')[0] })
  }
  return out.sort((a, b) => `${b.date} ${b.time}`.localeCompare(`${a.date} ${a.time}`))
}

export function ShotboardBody({ it }: { it: Item }) {
  const { tr } = useTr()
  const d = useContext(ShotboardContext)
  if (!d?.project) return <div style={note}>{tr('Ouvre un projet : le shotboard lit sa Production.', 'Open a project: the shotboard reads its Production.')}</div>
  if (!d.state) return <div style={note}>{tr('Chargement de Production...', 'Loading Production...')}</div>
  if (!d.rows.length) return <div style={note}>{tr('Aucune sequence dans Production.', 'No sequence in Production.')}</div>
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: SB.gap, padding: SB.gap }}>
      {d.rows.map(r => (
        <div key={r.seq} style={{ display: 'flex', gap: SB.gap, height: SB.cellH }}>
          <div style={{ width: SB.head - SB.gap, flex: 'none', display: 'flex', flexDirection: 'column', justifyContent: 'center', color: INK }}>
            <b style={{ fontSize: 15 }}>{r.seq}</b>
            {r.label && <span style={{ fontSize: 11, opacity: 0.7 }}>{r.label}</span>}
            <span style={{ fontSize: 10, opacity: 0.55 }}>{r.shots.length} shot(s)</span>
          </div>
          {r.shots.map(s => <ShotCell key={s.id} board={it} seq={r.seq} shot={s} />)}
        </div>
      ))}
    </div>
  )
}

const ShotCell = memo(function ShotCell({ board, seq, shot }: { board: Item; seq: string; shot: ProductionShot }) {
  const { tr } = useTr()
  const d = useContext(ShotboardContext)!
  const ref = shotRef(seq, shot.name)
  const cell = d.cells.get(cellKey(board.rid, ref))
  const media = mediaOf(d, shot)
  const free = d.canEdit && !textLocked(board)
  const at1 = cell?.frame_at ?? 0
  const at2 = typeof cell?.frame_at2 === 'number' ? cell.frame_at2 : null
  const tasks = useMemo(() => d.state ? effectiveTasks(d.state, shot).sort((a, b) => a.order - b.order).map(t => t.name) : [], [d.state, shot])
  const [task, setTask] = useState<string>('')
  const chosen = task || tasks.find(t => t.toUpperCase() === media?.m.task.toUpperCase()) || tasks[0] || ''
  const [idea, setIdea] = useState(cell?.text ?? '')
  const typing = useRef(false)
  useEffect(() => { if (!typing.current) setIdea(cell?.text ?? '') }, [cell?.text])
  const [sending, setSending] = useState(false)
  // Slider drafts: the still follows them (2 % steps, cached), the board gets the release.
  const [draft1, setDraft1] = useState<number | null>(null)
  const [draft2, setDraft2] = useState<number | null>(null)
  const q = (v: number | null, d: number) => v === null ? d : Math.round(v * 50) / 50
  const retakes = retakesOf(shot)
  const stop = (e: React.SyntheticEvent) => e.stopPropagation()
  const put = (fields: Record<string, unknown>) => d.setCell(board, ref, fields)
  const send = async () => {
    const text = idea.trim()
    if (!text || !chosen) return
    setSending(true)
    try { await d.sendRetake(seq, shot.name, chosen, text) } finally { setSending(false) }
  }
  return (
    <div style={{ width: SB.cellW, flex: 'none', boxSizing: 'border-box', padding: 8, borderRadius: 6, background: 'oklch(98% 0 0)',
                  border: '1px solid oklch(85% 0.01 250)', display: 'flex', flexDirection: 'column', gap: 4, color: INK, fontSize: 11 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 4, height: 18 }}>
        <b style={{ fontSize: 12 }}>{shot.name}</b>
        {shot.label && <span style={{ opacity: 0.6, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{shot.label}</span>}
        <span style={{ flex: 1 }} />
        {media && <span title={media.m.file} style={{ opacity: 0.55 }}>{media.m.task} {media.m.version}</span>}
      </div>
      <div style={{ display: 'flex', gap: 4, height: SB.imgH }}>
        <Still media={media} at={q(draft1, at1)} />
        {at2 !== null && <Still media={media} at={q(draft2, at2)}
                                onDrop={free ? () => put({ frame_at2: null }) : undefined} />}
      </div>
      <div style={{ display: 'flex', gap: 4, height: 18, alignItems: 'center' }} onPointerDown={stop}>
        <Slider value={at1} disabled={!free || media?.kind !== 'video'} onDraft={setDraft1} onCommit={v => put({ frame_at: v })} />
        {at2 !== null
          ? <Slider value={at2} disabled={!free || media?.kind !== 'video'} onDraft={setDraft2} onCommit={v => put({ frame_at2: v })} />
          : free && media?.kind === 'video' && (
            <button type="button" title={tr('Ajouter une 2e image', 'Add a 2nd still')} onClick={() => put({ frame_at2: 1 })} style={iconBtn}><Plus size={12} /></button>)}
      </div>
      <textarea value={idea} readOnly={!free} placeholder={free ? tr('Retake / idee', 'Retake / idea') : ''}
                onPointerDown={stop} onKeyDown={stop}
                onFocus={() => { typing.current = true }}
                onChange={e => setIdea(e.target.value)}
                onBlur={e => { typing.current = false; const v = e.target.value; if (v !== (cell?.text ?? '')) put({ text: v || null }) }}
                style={{ height: 56, resize: 'none', boxSizing: 'border-box', border: '1px solid oklch(85% 0.01 250)', borderRadius: 4,
                         padding: 4, font: 'inherit', fontSize: 11.5, color: INK, background: 'white' }} />
      <div style={{ display: 'flex', gap: 4, alignItems: 'center', height: 22 }} onPointerDown={stop}>
        <select value={chosen} disabled={!d.canEdit || !tasks.length} onChange={e => setTask(e.target.value)}
                title={tr('Tache qui recoit la retake dans Production', 'Task that gets the retake in Production')}
                style={{ flex: 1, minWidth: 0, height: 20, fontSize: 11, color: INK, background: 'white', border: '1px solid oklch(85% 0.01 250)', borderRadius: 4 }}>
          {tasks.map(t => <option key={t} value={t}>{t}</option>)}
        </select>
        <button type="button" disabled={!d.canEdit || sending || !idea.trim() || !chosen} onClick={() => { void send() }}
                title={tr('Ajouter cette idee aux retakes du shot dans Production', 'Add this idea to the shot retakes in Production')}
                style={{ ...iconBtn, gap: 3, padding: '0 6px', height: 20, border: '1px solid oklch(80% 0.01 250)', borderRadius: 4,
                         opacity: !d.canEdit || !idea.trim() ? 0.45 : 1 }}>
          <Send size={11} /> Retake
        </button>
      </div>
      <div style={{ flex: 1, minHeight: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column', gap: 1 }}
           title={retakes.map(r => `${r.task} ${r.date} ${r.author} : ${r.text}`).join('\n')}>
        {retakes.length === 0
          ? <span style={{ opacity: 0.45 }}>{tr('Aucune retake dans Production', 'No retake in Production')}</span>
          : <>
            <span style={{ opacity: 0.6 }}>{retakes.length} retake(s) Production</span>
            {retakes.slice(0, 2).map(r => (
              <span key={r.id} style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                <b>{r.task}</b> {r.text}</span>
            ))}
          </>}
      </div>
    </div>
  )
})

// The still of one cell, at the position written in the board.
function Still({ media, at, onDrop }: { media: ReturnType<typeof mediaOf>; at: number; onDrop?: () => void }) {
  const { tr } = useTr()
  const canvas = useRef<HTMLCanvasElement>(null)
  const [state, setState] = useState<'wait' | 'ok' | 'fail' | 'none'>('wait')
  const url = media?.url, kind = media?.kind
  useEffect(() => {
    if (!url || !kind) { setState('none'); return }
    let alive = true
    const draw = (b: ImageBitmap | null) => {
      if (!alive) return
      const c = canvas.current
      if (!b || !c) { setState('fail'); return }
      c.width = b.width; c.height = b.height
      c.getContext('2d')!.drawImage(b, 0, 0)
      setState('ok')
    }
    const hit = peekFrame(url, kind, at)
    if (hit) draw(hit)
    else { setState('wait'); void grabFrame(url, kind, at).then(draw) }
    return () => { alive = false }
  }, [url, kind, at])
  return (
    <div style={{ position: 'relative', flex: 1, minWidth: 0, borderRadius: 4, overflow: 'hidden', background: 'oklch(92% 0.01 250)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <canvas ref={canvas} style={{ width: '100%', height: '100%', objectFit: 'contain', display: state === 'ok' ? 'block' : 'none' }} />
      {state !== 'ok' && <span style={{ fontSize: 10.5, opacity: 0.6, padding: 6, textAlign: 'center', wordBreak: 'break-all' }}>
        {state === 'none' ? tr('Aucun media pour ce shot', 'No media for this shot')
          : state === 'wait' ? '...' : `${tr('Illisible ici', 'Not readable here')} (${media?.m.file ?? ''})`}</span>}
      {onDrop && <button type="button" title={tr('Retirer cette image', 'Remove this still')} onPointerDown={e => e.stopPropagation()} onClick={onDrop}
                         style={{ ...iconBtn, position: 'absolute', right: 2, top: 2, background: 'oklch(98% 0 0 / 0.85)', borderRadius: 3 }}><X size={11} /></button>}
    </div>
  )
}

// 0..1 in the media; written on release only (one journal line per pick).
function Slider({ value, disabled, onDraft, onCommit }: { value: number; disabled: boolean; onDraft: (v: number | null) => void; onCommit: (v: number) => void }) {
  const [draft, setDraftState] = useState<number | null>(null)
  const setDraft = (v: number | null) => { setDraftState(v); onDraft(v) }
  const commit = () => {
    if (draft !== null && Math.abs(draft - value) > 0.0005) onCommit(Math.round(draft * 100) / 100)
    setDraft(null)
  }
  return (
    <input type="range" min={0} max={1} step={0.01} value={draft ?? value} disabled={disabled}
           onChange={e => setDraft(Number(e.target.value))} onPointerUp={commit} onKeyUp={commit} onBlur={commit}
           title={`${Math.round((draft ?? value) * 100)} %`}
           style={{ flex: 1, minWidth: 0, height: 14, accentColor: 'oklch(55% 0.12 245)' }} />
  )
}

/** PNG / PDF export (exportBoard.ts): the grid, the stills already made, the ideas. */
export function drawShotboard(d: ShotboardData | null, ctx: CanvasRenderingContext2D, it: Item, b: Box) {
  ctx.fillStyle = '#ffffff'
  ctx.strokeStyle = '#b9bcc2'
  ctx.fillRect(b.x, b.y, b.w, b.h)
  ctx.strokeRect(b.x, b.y, b.w, b.h)
  if (!d?.state) return
  ctx.textBaseline = 'top'
  d.rows.forEach((r, ri) => {
    const y = b.y + SB.gap + ri * (SB.cellH + SB.gap)
    ctx.fillStyle = '#2a2f38'
    ctx.font = '600 15px system-ui, sans-serif'
    ctx.fillText(r.seq, b.x + SB.gap, y + SB.cellH / 2 - 8)
    r.shots.forEach((s, si) => {
      const x = b.x + SB.head + si * (SB.cellW + SB.gap)
      ctx.fillStyle = '#fafafa'
      ctx.fillRect(x, y, SB.cellW, SB.cellH)
      ctx.strokeRect(x, y, SB.cellW, SB.cellH)
      ctx.fillStyle = '#2a2f38'
      ctx.font = '600 12px system-ui, sans-serif'
      ctx.fillText(s.name, x + 8, y + 8)
      const cell = d.cells.get(cellKey(it.rid, shotRef(r.seq, s.name)))
      const media = mediaOf(d, s)
      const ats = [cell?.frame_at ?? 0, ...(typeof cell?.frame_at2 === 'number' ? [cell.frame_at2] : [])]
      const slotW = (SB.cellW - 16 - (ats.length - 1) * 4) / ats.length
      ats.forEach((at, i) => {
        const sx = x + 8 + i * (slotW + 4), sy = y + 30
        const bmp = media ? peekFrame(media.url, media.kind, at) : null
        if (bmp) {
          const k = Math.min(slotW / bmp.width, SB.imgH / bmp.height)
          ctx.drawImage(bmp, sx + (slotW - bmp.width * k) / 2, sy + (SB.imgH - bmp.height * k) / 2, bmp.width * k, bmp.height * k)
        } else { ctx.fillStyle = '#e6e7ea'; ctx.fillRect(sx, sy, slotW, SB.imgH) }
      })
      if (cell?.text) {
        ctx.fillStyle = '#2a2f38'
        ctx.font = '11.5px system-ui, sans-serif'
        cell.text.split('\n').slice(0, 6).forEach((line, li) => ctx.fillText(line.slice(0, 40), x + 8, y + 40 + SB.imgH + li * 14))
      }
    })
  })
}

const note: React.CSSProperties = { padding: 16, fontSize: 13, color: INK, opacity: 0.7 }
const iconBtn: React.CSSProperties = { border: 'none', background: 'transparent', padding: 1, cursor: 'pointer', color: 'inherit', display: 'inline-flex', alignItems: 'center' }
