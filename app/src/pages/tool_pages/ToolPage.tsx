// ToolPage.tsx — the TOOL tab (04_PAGES_TOOL §6): the pages made by the team, rendered by
// PageRenderer with the data widgets. Rail of the pages on the left (hidden with a single
// page), grouped by scope (team, project), search beyond 8 pages; the last page opened is
// kept per artist (user data flux.tool.last). "Editer" (Team TD) opens /tool/:id/edit.
// Everyone sees and uses the pages; the backend checks the rights again on every write.
// ADR 0078: the pages meant for someone else (for_me false) sit under "Other tools", folded
// by default (kept per artist, flux.tool.others_open): a filter of the rail, never a lock.

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ChevronDown, ChevronRight, Pencil, Plus, Search } from 'lucide-react'
import { api } from '../../api/client'
import { flowsApi } from '../../api/flows'
import { useFlowsWs } from '../../hooks/useFlowsWs'
import { usePageList } from '../../hooks/usePages'
import { useProject } from '../../ProjectContext'
import type { FlowsWsMessage, PageListItem, PageRead } from '../flow_editor/types'
import { useTr } from '../flow_editor/useTr'
import { DataWidget } from './DataWidgets'
import { pageIcon } from './icons'
import { PageRenderer } from './PageRenderer'

const LAST_KEY = 'flux.tool.last'
const OTHERS_KEY = 'flux.tool.others_open'
const forMe = (p: PageListItem) => p.for_me !== false

function Rail({ pages, current, onPick }: { pages: PageListItem[]; current: string | null; onPick: (p: PageListItem) => void }) {
  const { tr } = useTr()
  const [q, setQ] = useState('')
  const shown = pages.filter(p => !p.shadowed && (!q || `${p.label} ${p.id}`.toLowerCase().includes(q.toLowerCase())))
  const mine = shown.filter(forMe)
  const others = shown.filter(p => !forMe(p))
  const [openOthers, setOpenOthers] = useState(false)
  useEffect(() => {
    api.getUserData().then(d => { if (d?.[OTHERS_KEY] === true) setOpenOthers(true) }).catch(() => { /* folded */ })
  }, [])
  // The current page or a search hit stays visible even when it is an other tool.
  const othersOpen = openOthers || !!q || others.some(p => p.id === current)
  const toggleOthers = () => {
    const next = !openOthers
    setOpenOthers(next)
    api.setUserData({ [OTHERS_KEY]: next }).catch(() => { /* not kept */ })
  }
  const groups: [string, PageListItem[]][] = [
    [tr('Projet', 'Project'), mine.filter(p => p.scope === 'project')],
    [tr('Equipe', 'Team'), mine.filter(p => p.scope === 'team')],
  ]
  const item = (p: PageListItem) => {
    const Icon = pageIcon(p.icon)
    return (
      <div key={`${p.scope}/${p.id}`} className={`nav${current === p.id ? ' active' : ''}`} onClick={() => onPick(p)} title={p.error ?? p.description}>
        <Icon size={14} strokeWidth={1.75} /> <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.label}</span>
      </div>
    )
  }
  return (
    <aside style={{ width: 200, flexShrink: 0, borderRight: '1px solid var(--rule)', padding: '10px 8px', overflowY: 'auto' }}>
      {pages.length > 8 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
          <Search size={12} style={{ color: 'var(--ink-4)' }} />
          <input value={q} onChange={e => setQ(e.target.value)} placeholder={tr('Chercher', 'Search')}
                 style={{ flex: 1, minWidth: 0, height: 24, padding: '0 6px', border: '1px solid var(--rule-2)', background: 'var(--bg-deep)', borderRadius: 5, fontSize: 12, color: 'var(--ink)' }} />
        </div>
      )}
      {others.length > 0 && <div className="cap" style={{ padding: '0 6px 6px', color: 'var(--ink-2)' }}>{tr('Tes tools', 'Your tools')}</div>}
      {groups.filter(([, list]) => list.length).map(([title, list]) => (
        <div key={title} style={{ marginBottom: 10 }}>
          <div className="cap" style={{ padding: '0 6px 4px' }}>{title}</div>
          {list.map(item)}
        </div>
      ))}
      {others.length > 0 && (
        <div style={{ marginTop: 6, borderTop: '1px solid var(--rule)', paddingTop: 8 }}>
          <div className="nav" onClick={toggleOthers} title={tr('Pages faites pour les autres personnes, roles ou departements', 'Pages meant for other people, roles or departments')}>
            {othersOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
            <span className="cap" style={{ color: 'var(--ink-2)' }}>Other tools</span>
            <span className="tp-note" style={{ marginLeft: 'auto' }}>{others.length}</span>
          </div>
          {othersOpen && others.map(item)}
        </div>
      )}
    </aside>
  )
}

export function ToolPage() {
  const { tr } = useTr()
  const navigate = useNavigate()
  const { project } = useProject()
  const [params, setParams] = useSearchParams()
  const { list, error: listError } = usePageList(project)
  const [read, setRead] = useState<PageRead | null>(null)
  const [error, setError] = useState<string | null>(null)
  const pages = useMemo(() => list?.pages ?? [], [list])
  const wanted = params.get('page')
  const canCreate = !!list && (list.can_edit.team || list.can_edit.project)

  // Without ?page: the last page this artist opened, else the first one.
  useEffect(() => {
    if (wanted || !pages.length) return
    let alive = true
    api.getUserData().then(d => {
      const last = typeof d?.[LAST_KEY] === 'string' ? d[LAST_KEY] as string : null
      const pick = pages.find(p => p.id === last && !p.shadowed) ?? pages.find(p => !p.shadowed && forMe(p)) ?? pages.find(p => !p.shadowed)
      if (alive && pick) setParams({ page: pick.id }, { replace: true })
    }).catch(() => { const first = pages.find(p => !p.shadowed && forMe(p)) ?? pages.find(p => !p.shadowed); if (alive && first) setParams({ page: first.id }, { replace: true }) })
    return () => { alive = false }
  }, [wanted, pages, setParams])

  const load = useCallback(() => {
    if (!wanted) { setRead(null); return }
    flowsApi.getPage(wanted, { project: project || undefined })
      .then(r => { setRead(r); setError(null) })
      .catch(err => { setRead(null); setError((err as Error).message) })
  }, [wanted, project])
  useEffect(() => { load() }, [load])

  // The page or a flow it runs changed (save, activation): reread its issues.
  useFlowsWs(useCallback((msg: FlowsWsMessage) => {
    if ((msg.type === 'page_changed' && msg.page === wanted) || msg.type === 'activation' || msg.type === 'flow_changed') load()
  }, [wanted, load]), load)

  const pick = (p: PageListItem) => {
    setParams({ page: p.id })
    api.setUserData({ [LAST_KEY]: p.id }).catch(() => { /* not kept: the first page opens next time */ })
  }

  const visible = pages.filter(p => !p.shadowed)
  const Icon = pageIcon(read?.page.icon)
  return (
    <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
      {visible.length > 1 && <Rail pages={pages} current={wanted} onPick={pick} />}
      <div style={{ flex: 1, minWidth: 0, overflowY: 'auto', padding: '16px 22px' }}>
        {listError && <div className="tp-note" style={{ color: 'var(--err)' }}>{listError}</div>}
        {list && !visible.length && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, alignItems: 'flex-start' }}>
            <div style={{ fontSize: 14, color: 'var(--ink-2)' }}>{tr('Aucune page TOOL pour le moment.', 'No TOOL page yet.')}</div>
            {canCreate
              ? <button type="button" className="btn primary" onClick={() => navigate('/tool/new/edit')}><Plus size={13} /> {tr('Nouvelle page', 'New page')}</button>
              : <div className="tp-note">{tr('Un Team TD cree les pages de l\'equipe.', 'A Team TD creates the team pages.')}</div>}
          </div>
        )}
        {error && <div className="tp-note" style={{ color: 'var(--err)' }}>{error}</div>}
        {read && (
          <>
            <header style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
              <Icon size={18} strokeWidth={1.75} style={{ color: 'var(--ink-2)' }} />
              <h1 style={{ fontSize: 17, fontWeight: 600, color: 'var(--ink)', margin: 0 }}>{read.page.label || read.id}</h1>
              <span className="tag">{read.scope === 'team' ? tr('equipe', 'team') : tr('projet', 'project')}</span>
              <span style={{ flex: 1 }} />
              {canCreate && <button type="button" className="btn ghost sm" onClick={() => navigate('/tool/new/edit')}><Plus size={12} /> {tr('Nouvelle', 'New')}</button>}
              {read.can_edit && <button type="button" className="btn sm" onClick={() => navigate(`/tool/${read.id}/edit?scope=${read.scope}`)}><Pencil size={12} /> {tr('Editer', 'Edit')}</button>}
            </header>
            {read.page.description && <div className="tp-note" style={{ marginBottom: 12, color: 'var(--ink-3)' }}>{read.page.description}</div>}
            {read.issues.some(i => i.level === 'error') && !read.can_edit && (
              <div className="tp-note" style={{ marginBottom: 8, color: 'var(--ink-3)' }}>{tr('Previens un TD pour corriger cette page.', 'Tell a TD to fix this page.')}</div>
            )}
            <PageRenderer key={`${read.scope}/${read.id}`} page={read.page} issues={read.issues} project={project || undefined}
                          renderData={w => <DataWidget page={read.page} widget={w} project={project || undefined} />} />
          </>
        )}
      </div>
    </div>
  )
}
