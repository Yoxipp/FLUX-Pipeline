// PageRenderer.tsx — renders a TOOL page (04_PAGES_TOOL §6, ADR 0066): folders > rows >
// widgets, the form widgets through ParamWidget (same widgets as ActionForm and the Flows
// editor), real <button>s for page buttons (Btn is a div). One renderer for the TOOL tab,
// the page editor preview and the generated Publisher panel (04 §7).
//
// A button runs the ACTIVE version of its flow: POST /flows/{flow}/run {event: button_id,
// values} with the fields bound to that flow (A7). The last run of each button comes from
// GET /flows/runs?flow&event&limit=1, refreshed on the WS run messages (no polling).
// Field values are local state; `remember: user` keeps the last entry per artist in the
// user data (flux.pages.remember), nothing is written in the page or the flow.
// preview: buttons are inert ("lancerait ..."), a click on a widget selects it (editor).

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { ChevronDown, ChevronRight, LoaderCircle, Play, Square } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '../../api/client'
import { flowsApi } from '../../api/flows'
import { ParamWidget, type ParamKind } from '../../components/shared/ParamWidget'
import { SecTitle } from '../../components/shared/ui'
import { useFlowsWs } from '../../hooks/useFlowsWs'
import type { FlowsWsMessage, PageDoc, PageFolder, PageIssue, PageLayoutItem, PageWidget, RunSummary } from '../flow_editor/types'
import { useTr } from '../flow_editor/useTr'
import { ago, blockedWidgets, initialValue, isDataKind, runValues, seconds, widgetsOf } from './links'

const REMEMBER_KEY = 'flux.pages.remember'
const EMPTY_RUN: ButtonRun = { last: null, pending: null, error: null, preview: null }

type HttpError = Error & { status?: number; detail?: { status?: string } }

export interface PageRendererProps {
  page: PageDoc
  issues?: PageIssue[]
  project?: string
  preview?: boolean                          // editor: inert buttons, click selects
  selected?: string | null
  onSelect?: (id: string) => void
  renderData?: (w: PageWidget) => ReactNode  // data widgets (DataWidgets.tsx)
  extraActions?: ReactNode                   // e.g. the Publisher destination block
}

const KIND_OF: Record<string, ParamKind> = {
  float: 'float', int: 'int', text: 'str', path: 'path', dir: 'dir', toggle: 'bool', select: 'select', list: 'list',
}

interface ButtonRun { last: RunSummary | null; pending: string | null; error: string | null; preview: string | null }

// -- last run per button --------------------------------------------------------------------

function useButtonRuns(page: PageDoc, project: string | undefined, enabled: boolean) {
  const buttons = useMemo(() => widgetsOf(page).filter(w => w.kind === 'button' && w.on_click), [page])
  const [runs, setRuns] = useState<Record<string, ButtonRun>>({})
  const pending = useRef<Record<string, string>>({})   // run_id -> widget id

  const refresh = useCallback((flow?: string) => {
    if (!enabled) return
    for (const b of buttons) {
      if (!b.on_click || (flow && b.on_click.flow !== flow)) continue
      flowsApi.listRuns({ flow: b.on_click.flow, event: b.on_click.button_id, limit: 1, project })
        .then(list => setRuns(r => ({ ...r, [b.id]: { ...EMPTY_RUN, ...r[b.id], last: list[0] ?? null } })))
        .catch(() => { /* backend down: the state stays as it was */ })
    }
  }, [buttons, project, enabled])

  useEffect(() => { refresh() }, [refresh])

  const onMessage = useCallback((msg: FlowsWsMessage) => {
    if (msg.type !== 'run_finished' && msg.type !== 'run_started') return
    if (!buttons.some(b => b.on_click?.flow === msg.flow)) return
    if (msg.type === 'run_finished') {
      const wid = pending.current[msg.run_id]
      if (wid) {
        delete pending.current[msg.run_id]
        setRuns(r => ({ ...r, [wid]: { ...EMPTY_RUN, ...r[wid], pending: null } }))
      }
      refresh(msg.flow)
    }
  }, [buttons, refresh])
  useFlowsWs(onMessage, refresh)

  const mark = useCallback((wid: string, patch: Partial<ButtonRun>, runId?: string) => {
    if (runId) pending.current[runId] = wid
    setRuns(r => ({ ...r, [wid]: { ...EMPTY_RUN, ...r[wid], ...patch } }))
  }, [])
  return { runs, mark, refresh }
}

// -- widgets --------------------------------------------------------------------------------

function RunState({ state }: { state: ButtonRun | undefined }) {
  const { tr, lang } = useTr()
  if (state?.preview) return <div className="cap" style={{ color: 'var(--ink-3)' }}>{state.preview}</div>
  if (state?.error) return <div className="cap" style={{ color: 'var(--err)' }}>{state.error}</div>
  if (state?.pending) {
    return <div className="cap" style={{ color: 'var(--ink-3)', display: 'flex', alignItems: 'center', gap: 6 }}>
      <LoaderCircle size={12} style={{ animation: 'spin 1s linear infinite' }} /> {tr('en cours', 'running')}
    </div>
  }
  const last = state?.last
  if (!last) return <div className="cap" style={{ color: 'var(--ink-4)' }}>{tr('jamais lance', 'never run')}</div>
  if (last.status === 'running' || last.status === 'queued') {
    return <div className="cap" style={{ color: 'var(--ink-3)' }}>{tr(`en cours, par ${last.user ?? '?'}`, `running, by ${last.user ?? '?'}`)}</div>
  }
  if (last.status === 'ok') {
    const when = ago(last.ended ?? last.started, lang)
    return <div className="cap" style={{ color: 'var(--ok)' }}>
      {tr(`fini ${when} (${seconds(last.duration_ms, lang)}) par ${last.user ?? '?'}`, `done ${when} (${seconds(last.duration_ms, lang)}) by ${last.user ?? '?'}`)}
    </div>
  }
  return <div className="cap" style={{ color: 'var(--err)' }} title={last.error ?? ''}>
    {tr('erreur', 'error')}{last.error ? ` : ${last.error}` : ''} ({ago(last.ended ?? last.started, lang)})
  </div>
}

function FieldWidget({ w, value, onChange, blocked }: { w: PageWidget; value: unknown; onChange: (v: unknown) => void; blocked?: string }) {
  const { tr } = useTr()
  const kind = w.kind === 'text' && w.multiline ? 'text' : KIND_OF[w.kind]
  const pick = w.kind === 'dir'
    ? async () => { const p = await window.electronAPI?.openFolder(); if (p) onChange(p) }
    : w.kind === 'path'
      ? async () => {
          const filters = w.filters?.length ? [{ name: tr('Fichiers', 'Files'), extensions: w.filters.map(f => f.replace(/^\./, '')) }] : undefined
          const p = await window.electronAPI?.openFile(filters)
          if (p) onChange(p)
        }
      : undefined
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0, opacity: blocked ? 0.5 : 1 }} title={blocked ?? w.tooltip}>
      <span className="cap" style={{ width: 130, flexShrink: 0 }}>{w.label || w.id}{w.kind === 'float' && w.unit ? ` (${w.unit})` : ''}</span>
      <ParamWidget kind={kind} value={value} onChange={onChange} disabled={!!blocked} placeholder={w.placeholder}
                   options={w.options?.map(o => o.value)} onPickPath={pick && window.electronAPI ? () => { void pick() } : undefined} />
    </div>
  )
}

// -- layout ---------------------------------------------------------------------------------

interface Ctx {
  page: PageDoc
  values: Record<string, unknown>
  setValue: (id: string, v: unknown) => void
  blocked: Record<string, string>
  runs: Record<string, ButtonRun>
  click: (w: PageWidget) => void
  stop: (runId: string) => void
  preview: boolean
  selected?: string | null
  onSelect?: (id: string) => void
  renderData?: (w: PageWidget) => ReactNode
}

function WidgetCell({ w, ctx }: { w: PageWidget; ctx: Ctx }) {
  const { tr } = useTr()
  let body: ReactNode
  if (w.kind === 'button') {
    const blocked = ctx.blocked[w.id]
    const state = ctx.runs[w.id]
    const running = !!state?.pending
    body = (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'flex-start' }}>
        <button type="button" className={running ? 'btn' : 'btn primary'} disabled={!!blocked} title={blocked ?? w.tooltip}
                onClick={e => { e.stopPropagation(); if (running) ctx.stop(state!.pending!); else ctx.click(w) }}
                style={{ opacity: blocked ? 0.5 : 1, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          {running ? <><Square size={12} />{tr('Stop', 'Stop')}</> : <><Play size={12} />{w.label || w.id}</>}
        </button>
        {blocked ? <div className="cap" style={{ color: 'var(--ink-4)' }}>{blocked}</div> : <RunState state={state} />}
      </div>
    )
  } else if (w.kind === 'separator') {
    body = <div style={{ borderTop: '1px solid var(--rule)', paddingTop: 6 }}>{w.label && <span className="cap">{w.label}</span>}</div>
  } else if (w.kind === 'label') {
    body = <div className="cap" style={{ color: 'var(--ink-2)', whiteSpace: 'pre-wrap' }}>{w.text ?? w.label}</div>
  } else if (isDataKind(w.kind)) {
    body = ctx.renderData ? ctx.renderData(w)
      : <div className="cap" style={{ color: 'var(--ink-4)' }}>{tr(`${w.kind} : ${w.label || w.id}`, `${w.kind}: ${w.label || w.id}`)}</div>
    if (ctx.blocked[w.id]) body = <div className="cap" style={{ color: 'var(--ink-4)' }} title={ctx.blocked[w.id]}>{ctx.blocked[w.id]}</div>
  } else {
    body = <FieldWidget w={w} value={ctx.values[w.id]} blocked={ctx.blocked[w.id]} onChange={v => ctx.setValue(w.id, v)} />
  }
  const sel = ctx.preview && ctx.selected === w.id
  return (
    <div onClickCapture={ctx.preview && ctx.onSelect ? () => ctx.onSelect!(w.id) : undefined}
         style={{ minWidth: 0, borderRadius: 6, outline: sel ? '2px solid var(--accent)' : 'none', outlineOffset: 2 }}>
      {body}
    </div>
  )
}

function Row({ row, ctx }: { row: PageWidget[]; ctx: Ctx }) {
  return (
    <div style={{ display: 'grid', gap: 12, alignItems: 'start', gridTemplateColumns: row.map(w => `minmax(0, ${w.w ?? 1}fr)`).join(' ') }}>
      {row.map(w => <WidgetCell key={w.id} w={w} ctx={ctx} />)}
    </div>
  )
}

type FolderItem = { folder: PageFolder; children: PageLayoutItem[] }

function Tabs({ folders, ctx }: { folders: FolderItem[]; ctx: Ctx }) {
  const [cur, setCur] = useState(0)
  const open = folders[Math.min(cur, folders.length - 1)]
  return (
    <div>
      <div style={{ display: 'flex', gap: 2, borderBottom: '1px solid var(--rule)', marginBottom: 10 }}>
        {folders.map((f, k) => (
          <button type="button" key={f.folder.id} onClick={() => setCur(k)} className="btn ghost"
                  style={{ borderRadius: '6px 6px 0 0', borderBottom: k === cur ? '2px solid var(--accent)' : '2px solid transparent', color: k === cur ? 'var(--ink)' : 'var(--ink-3)' }}>
            {f.folder.label || f.folder.id}
          </button>
        ))}
      </div>
      <Items items={open.children} ctx={ctx} />
    </div>
  )
}

function Folder({ item, ctx }: { item: FolderItem; ctx: Ctx }) {
  const [closed, setClosed] = useState(false)
  const { folder } = item
  if (folder.mode === 'collapsible') {
    return (
      <div>
        <button type="button" className="btn ghost" onClick={() => setClosed(c => !c)} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, padding: '2px 4px' }}>
          {closed ? <ChevronRight size={13} /> : <ChevronDown size={13} />}<span className="cap">{folder.label || folder.id}</span>
        </button>
        {!closed && <div style={{ marginTop: 8 }}><Items items={item.children} ctx={ctx} /></div>}
      </div>
    )
  }
  return (
    <div>
      {folder.label && <SecTitle>{folder.label}</SecTitle>}
      <Items items={item.children} ctx={ctx} />
    </div>
  )
}

// Consecutive `tabs` folders form one tab bar (Houdini Edit Parameter Interface).
function Items({ items, ctx }: { items: PageLayoutItem[]; ctx: Ctx }) {
  const out: ReactNode[] = []
  for (let k = 0; k < items.length; k++) {
    const item = items[k]
    if ('row' in item) { out.push(<Row key={`r${k}`} row={item.row} ctx={ctx} />); continue }
    if (item.folder.mode === 'tabs') {
      const group: FolderItem[] = []
      while (k < items.length && 'folder' in items[k] && (items[k] as FolderItem).folder.mode === 'tabs') group.push(items[k++] as FolderItem)
      k--
      out.push(<Tabs key={`t${group[0].folder.id}`} folders={group} ctx={ctx} />)
      continue
    }
    out.push(<Folder key={item.folder.id} item={item} ctx={ctx} />)
  }
  return <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>{out}</div>
}

// -- page -----------------------------------------------------------------------------------

export function PageRenderer({ page, issues = [], project, preview = false, selected, onSelect, renderData, extraActions }: PageRendererProps) {
  const { tr, lang } = useTr()
  const widgets = useMemo(() => widgetsOf(page), [page])
  const [remembered, setRemembered] = useState<Record<string, unknown> | null>(null)
  const [values, setValues] = useState<Record<string, unknown>>({})
  const { runs, mark } = useButtonRuns(page, project, !preview)
  const blocked = useMemo(() => blockedWidgets(issues, lang), [issues, lang])

  // Remembered entries of this artist (remember: user), read once per page.
  useEffect(() => {
    if (!widgets.some(w => w.remember === 'user')) { setRemembered({}); return }
    let alive = true
    api.getUserData()
      .then(d => { if (alive) setRemembered(((d?.[REMEMBER_KEY] as Record<string, Record<string, unknown>>) ?? {})[page.id] ?? {}) })
      .catch(() => { if (alive) setRemembered({}) })
    return () => { alive = false }
  }, [page.id, widgets])

  // Values follow the page: a new widget gets its initial value, a kept one keeps its entry.
  useEffect(() => {
    if (remembered === null) return
    setValues(old => Object.fromEntries(widgets.map(w => [w.id, w.id in old && !preview ? old[w.id] : initialValue(w, remembered)])))
  }, [widgets, remembered, preview])

  const setValue = useCallback((id: string, v: unknown) => setValues(old => ({ ...old, [id]: v })), [])

  const click = useCallback(async (w: PageWidget) => {
    if (!w.on_click) return
    const vals = runValues(page, w.on_click.flow, values)
    if (preview) {
      mark(w.id, { preview: tr(`lancerait ${w.on_click.flow}, evenement ${w.on_click.button_id}, valeurs ${JSON.stringify(vals)}`,
                              `would run ${w.on_click.flow}, event ${w.on_click.button_id}, values ${JSON.stringify(vals)}`) })
      return
    }
    if (w.confirm && !window.confirm(w.confirm)) return
    const keep = widgets.filter(x => x.remember === 'user')
    if (keep.length) {
      const mine = Object.fromEntries(keep.map(x => [x.id, values[x.id]]))
      api.getUserData().then(d => {
        const all = { ...((d?.[REMEMBER_KEY] as Record<string, unknown>) ?? {}), [page.id]: mine }
        return api.setUserData({ [REMEMBER_KEY]: all })
      }).catch(() => { /* not kept: the next visit shows the defaults */ })
    }
    mark(w.id, { error: null, preview: null })
    try {
      const r = await flowsApi.run(w.on_click.flow, { event: w.on_click.button_id, values: vals, project })
      mark(w.id, { pending: r.run_id }, r.run_id)
    } catch (err) {
      const e = err as HttpError
      const msg = e.detail?.status === 'skipped' ? tr('Deja en cours', 'Already running') : e.message
      mark(w.id, { error: msg, pending: null })
    }
  }, [page, values, preview, project, widgets, mark, tr])

  const stop = useCallback((runId: string) => {
    flowsApi.cancelRun(runId, project).catch(err => toast.error((err as Error).message))
  }, [project])

  const ctx: Ctx = { page, values, setValue, blocked, runs, click: w => { void click(w) }, stop, preview, selected, onSelect, renderData }
  const errorCount = issues.filter(i => i.level === 'error').length

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {errorCount > 0 && !preview && (
        <div className="cap" style={{ padding: '6px 10px', borderRadius: 6, background: 'var(--paper-2)', border: '1px solid var(--rule-2)', color: 'var(--ink-2)' }}>
          {tr(`Cette page a ${errorCount} probleme(s) : les widgets concernes sont grises.`, `This page has ${errorCount} problem(s): the widgets concerned are greyed out.`)}
        </div>
      )}
      {extraActions}
      <Items items={page.layout} ctx={ctx} />
    </div>
  )
}
