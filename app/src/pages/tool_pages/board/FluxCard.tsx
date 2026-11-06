// FluxCard.tsx — FLUX cards of the board (ADR 0074 n°5): an asset, a shot or the last publish
// of a task, READ from Production (the card stores only `ref`). One conditional read of
// GET /production/<project> per board, every 30 s while a card is on it; the cards get it
// through a context so the memoised board items do not re-render for nothing.

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { ExternalLink, FolderOpen, X } from 'lucide-react'
import { api } from '../../../api/client'
import type { ProductionAsset, ProductionPayload, ProductionPublish, ProductionShot, ProductionState } from '../../../types'
import { effectiveTasks, taskStatus } from '../../Production/tracking'
import { useTr } from '../../flow_editor/useTr'

const REFRESH_MS = 30_000
// Flat, muted status colours (no glow).
const STATUS_TONE: Record<string, string> = {
  TODO: 'oklch(70% 0.01 250)', WIP: 'oklch(62% 0.12 245)', WFA: 'oklch(70% 0.13 60)',
  RTK: 'oklch(60% 0.16 25)', APPROVED: 'oklch(62% 0.12 150)',
}

export interface FluxTarget {
  kind: 'asset' | 'shot' | 'publish'
  entity?: ProductionAsset | ProductionShot
  group: string                 // asset class or sequence name
  name: string
  task?: string
  publish?: ProductionPublish
}

export interface FluxBoardData {
  project?: string
  payload: ProductionPayload | null
  resolve: (ref: string) => FluxTarget | null
  open: (t: FluxTarget) => void
  reveal: (t: FluxTarget) => void
}
export const FluxBoardContext = createContext<FluxBoardData | null>(null)

const pubKey = (p: ProductionPublish) => `${p.date ?? ''} ${p.time ?? ''}`

export function resolveRef(state: ProductionState | undefined, byTask: Record<string, ProductionPublish[]>, ref: string): FluxTarget | null {
  if (!state) return null
  const m = /^(asset|shot|publish:asset|publish:shot):([^/]+)\/([^/]+)(?:\/([^/]+))?$/.exec(ref)
  if (!m) return null
  const [, kind, group, name, task] = m
  const up = (s: string) => s.toUpperCase()
  let entity: ProductionAsset | ProductionShot | undefined
  if (kind.endsWith('asset')) entity = state.assets.find(a => up(a.class) === up(group) && up(a.name) === up(name))
  else {
    const seq = state.sequences.find(s => up(s.name) === up(group))
    entity = seq ? state.shots.find(s => s.seq_id === seq.id && up(s.name) === up(name)) : undefined
  }
  if (!entity) return null
  if (!kind.startsWith('publish')) return { kind: kind as 'asset' | 'shot', entity, group, name }
  const t = effectiveTasks(state, entity).find(x => up(x.name) === up(task ?? ''))
  const list = t ? byTask[`${entity.id}|${t.id}`] ?? [] : []
  const publish = [...list].sort((a, b) => pubKey(b).localeCompare(pubKey(a)))[0]
  return { kind: 'publish', entity, group, name, task: t?.name ?? task, publish }
}

// The live Production data of a board: read only while *enabled* (a card on the board, the picker open).
export function useBoardProduction(project: string | undefined, enabled: boolean) {
  const [payload, setPayload] = useState<ProductionPayload | null>(null)
  const etag = useRef<string | undefined>(undefined)
  useEffect(() => {
    etag.current = undefined
    setPayload(null)
  }, [project])
  useEffect(() => {
    if (!project || !enabled) return
    let alive = true
    const load = () => api.getProductionConditional(project, etag.current)
      .then(r => { if (!alive || r.notModified || !r.data) return; etag.current = r.etag; setPayload(r.data) })
      .catch(() => { /* keep the last data; a card shows "introuvable" when nothing is known */ })
    void load()
    const t = setInterval(load, REFRESH_MS)
    return () => { alive = false; clearInterval(t) }
  }, [project, enabled])
  return payload
}

export function FluxCardBody({ fluxRef: itemRef }: { fluxRef?: string }) {
  const { tr } = useTr()
  const ctx = useContext(FluxBoardContext)
  const target = ctx && itemRef ? ctx.resolve(itemRef) : null
  if (!ctx?.payload) return <div style={{ opacity: 0.6 }}>{tr('Chargement de Production...', 'Loading Production...')}</div>
  if (!target?.entity) return (
    <div style={{ opacity: 0.7 }}>
      <b>{itemRef?.split(':').pop()}</b><br />{tr('Introuvable dans Production (renomme ou autre projet).', 'Not found in Production (renamed or other project).')}
    </div>
  )
  const { entity } = target
  const thumb = entity.thumbnail && ctx.project ? api.refFileUrl(ctx.project, entity.thumbnail.rel_path, entity.thumbnail.file) : undefined
  const state = ctx.payload.production
  const tasks = target.kind === 'publish' ? [] : effectiveTasks(state, entity).sort((a, b) => a.order - b.order).slice(0, 6)
  const stop = (e: React.PointerEvent) => e.stopPropagation()
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'stretch', height: '100%' }}>
      <div style={{ width: 72, flex: 'none', borderRadius: 4, background: 'oklch(92% 0.01 250)', overflow: 'hidden' }}>
        {thumb && <img src={thumb} alt="" draggable={false} loading="lazy" style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />}
      </div>
      <div style={{ minWidth: 0, flex: 1, display: 'flex', flexDirection: 'column', gap: 3 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ fontSize: 10, textTransform: 'uppercase', opacity: 0.6 }}>{target.kind === 'publish' ? `publish ${target.task ?? ''}` : target.kind}</span>
          <span style={{ flex: 1 }} />
          {target.kind === 'publish'
            ? (target.publish && <button type="button" title={tr('Ouvrir le dossier dans le Folder Manager', 'Open the folder in the Folder Manager')}
                                         onPointerDown={stop} onClick={() => ctx.reveal(target)} style={iconBtn}><FolderOpen size={12} /></button>)
            : <button type="button" title={tr('Ouvrir dans Production', 'Open in Production')} onPointerDown={stop}
                      onClick={() => ctx.open(target)} style={iconBtn}><ExternalLink size={12} /></button>}
        </div>
        <b style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{target.group} / {target.name}</b>
        {target.kind === 'publish'
          ? (target.publish
              ? <span style={{ fontSize: 11, opacity: 0.8, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {target.publish.file} · {target.publish.user} · {target.publish.date}</span>
              : <span style={{ fontSize: 11, opacity: 0.6 }}>{tr('Aucun publish pour cette tache', 'No publish for this task')}</span>)
          : <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3 }}>
              {tasks.map(t => {
                const st = taskStatus(entity, t) || 'TODO'
                return <span key={t.id} title={`${t.name} : ${st}`}
                             style={{ fontSize: 10, padding: '0 4px', borderRadius: 3, color: 'white', background: STATUS_TONE[st] ?? STATUS_TONE.TODO }}>
                  {t.name}</span>
              })}
            </div>}
      </div>
    </div>
  )
}
const iconBtn: React.CSSProperties = { border: 'none', background: 'transparent', padding: 1, cursor: 'pointer', color: 'inherit', display: 'inline-flex' }

// Picker: choose an asset or a shot (optionally one of its tasks for a publish card).
export function FluxPicker({ payload, onPick, onClose }: { payload: ProductionPayload | null; onPick: (ref: string) => void; onClose: () => void }) {
  const { tr } = useTr()
  const [kind, setKind] = useState<'asset' | 'shot' | 'publish'>('asset')
  const [query, setQuery] = useState('')
  const [entity, setEntity] = useState<{ ref: string; e: ProductionAsset | ProductionShot } | null>(null)
  const state = payload?.production
  const rows = useMemo(() => {
    if (!state) return []
    const seqName = new Map(state.sequences.map(s => [s.id, s.name]))
    const all = [
      ...state.assets.map(a => ({ scope: 'asset', group: a.class, name: a.name, e: a as ProductionAsset | ProductionShot })),
      ...state.shots.map(s => ({ scope: 'shot', group: seqName.get(s.seq_id) ?? '?', name: s.name, e: s as ProductionAsset | ProductionShot })),
    ]
    const q = query.trim().toLowerCase()
    return all.filter(r => (kind === 'publish' || r.scope === kind) && (!q || `${r.group}/${r.name}`.toLowerCase().includes(q))).slice(0, 200)
  }, [state, kind, query])
  const pick = useCallback((r: (typeof rows)[number]) => {
    const ref = `${r.scope}:${r.group}/${r.name}`
    if (kind === 'publish') setEntity({ ref, e: r.e })
    else onPick(ref)
  }, [kind, onPick])
  return (
    <div onPointerDown={e => e.stopPropagation()} onWheel={e => e.stopPropagation()} onKeyDown={e => { e.stopPropagation(); if (e.key === 'Escape') onClose() }}
         style={{ position: 'absolute', left: 10, top: 10, width: 300, maxHeight: 'calc(100% - 20px)', display: 'flex', flexDirection: 'column', zIndex: 8,
                  background: 'var(--paper)', border: '1px solid var(--rule)', borderRadius: 8, boxShadow: '0 4px 14px oklch(0% 0 0 / 0.2)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 4, padding: 8, borderBottom: '1px solid var(--rule)' }}>
        {(['asset', 'shot', 'publish'] as const).map(k => (
          <button key={k} type="button" className="btn ghost sm" onClick={() => { setKind(k); setEntity(null) }}
                  style={{ background: kind === k ? 'var(--paper-2)' : undefined }}>{k === 'asset' ? 'Asset' : k === 'shot' ? 'Shot' : 'Publish'}</button>
        ))}
        <span style={{ flex: 1 }} />
        <button type="button" className="btn ghost sm" title={tr('Fermer', 'Close')} onClick={onClose}><X size={13} /></button>
      </div>
      {!state ? <div className="tp-note" style={{ padding: 10 }}>{tr('Chargement de Production...', 'Loading Production...')}</div>
        : entity ? <>
          <div className="cap" style={{ padding: '6px 10px' }}>{entity.ref.split(':')[1]} : {tr('quelle tache ?', 'which task?')}</div>
          <div style={{ overflow: 'auto' }}>
            {effectiveTasks(state, entity.e).map(t => (
              <div key={t.id} className="tp-row" onClick={() => onPick(`publish:${entity.ref}/${t.name}`)} style={rowStyle}>{t.name}</div>
            ))}
          </div>
        </> : <>
          <input autoFocus value={query} placeholder={tr('Chercher', 'Search')} onChange={e => setQuery(e.target.value)}
                 style={{ margin: 8, height: 26, padding: '0 8px', border: '1px solid var(--rule-2)', borderRadius: 5, background: 'var(--bg-deep)', color: 'var(--ink)', fontSize: 12 }} />
          <div style={{ overflow: 'auto' }}>
            {rows.map(r => (
              <div key={`${r.scope}:${r.e.id}`} onClick={() => pick(r)} style={rowStyle}>
                <span style={{ opacity: 0.55, fontSize: 10, marginRight: 6 }}>{r.scope}</span>{r.group} / {r.name}
              </div>
            ))}
            {!rows.length && <div className="tp-note" style={{ padding: 10 }}>{tr('Rien dans Production.', 'Nothing in Production.')}</div>}
          </div>
        </>}
    </div>
  )
}
const rowStyle: React.CSSProperties = { padding: '5px 10px', fontSize: 12, cursor: 'pointer', borderTop: '1px solid var(--rule)' }
