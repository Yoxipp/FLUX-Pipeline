// PageBuilder.tsx — the page editor (04_PAGES_TOOL §5), route /tool/:id/edit (id "new" =
// create a page). Like Houdini's Edit Parameter Interface, 4 columns:
//   Palette (widgets, templates) | Tree (folders > rows > widgets, data collections, problems)
//   | Properties (PageProps.tsx) | Preview (the same PageRenderer, inert buttons, click selects).
// Same generic store as the flow editor (undo / redo, flow_editor/store.ts). Validation in
// live (POST /flows/pages/validate, debounce 300 ms); saving with errors is allowed (the page
// is shown invalid). Ctrl+S saves, Ctrl+Z / Ctrl+Y undo / redo, Fermer = save then leave
// (decision 13: quit = Ctrl+S). Team TD only: the backend refuses otherwise.

import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Columns2, Database, FolderPlus, Redo2, Save, Trash2, Undo2, X } from 'lucide-react'
import { toast } from 'sonner'
import { flowsApi } from '../../api/flows'
import { useProject } from '../../ProjectContext'
import type { FlowListItem, PageDoc, PageIssue, PageLayoutItem, PageListItem, PageScope, PageWidget, PageWidgetKind } from '../flow_editor/types'
import { createDocStore, docOf, isDirty, useStore } from '../flow_editor/store'
import { useTr } from '../flow_editor/useTr'
import {
  PAGE_ID_RE, addData, addFolder, addWidget, emptyPage, findFolder, findWidget, kindLabel, moveItem, newWidget, removeData,
  removeItem, renameLocal, splitOut, suggestId, takenIds, updateData, updateFolder, updateWidget, type Target,
} from './builder'
import { DataWidget } from './DataWidgets'
import { pageIcon, PAGE_ICONS } from './icons'
import { PageRenderer } from './PageRenderer'
import { DataProps, FolderProps, PropRow, WidgetProps } from './PageProps'

type HttpError = Error & { status?: number; detail?: { by?: string; rev?: string } }

const PALETTE: PageWidgetKind[][] = [
  ['button', 'text', 'int', 'float', 'toggle', 'select', 'list', 'path', 'dir'],
  ['separator', 'label'],
  ['feed', 'table', 'cards', 'calendar', 'members', 'board'],
]

type Sel = { kind: 'widget'; id: string } | { kind: 'folder'; id: string } | { kind: 'data'; id: string } | { kind: 'page' } | null

const col = (w: number | string, extra: object = {}) => ({ width: w, flexShrink: 0, borderRight: '1px solid var(--rule)', overflowY: 'auto' as const, padding: '10px 10px', ...extra })

// -- create dialog --------------------------------------------------------------------------

function NewPage({ project, canTeam, canProject, templates, pages }: { project?: string; canTeam: boolean; canProject: boolean; templates: PageListItem[]; pages: PageListItem[] }) {
  const { tr } = useTr()
  const navigate = useNavigate()
  const [label, setLabel] = useState('')
  const [id, setId] = useState('')
  const [idEdited, setIdEdited] = useState(false)
  const [scope, setScope] = useState<PageScope>(canTeam ? 'team' : 'project')
  const [from, setFrom] = useState('')          // '' | tpl:<id> | copy:<scope>/<id>
  const [busy, setBusy] = useState(false)
  const taken = useMemo(() => new Set(pages.map(p => p.id)), [pages])
  // From a template: its own id while free (the template flows find the page by it, e.g. page: team).
  const tplId = from.startsWith('tpl:') ? from.slice(4) : ''
  const shownId = idEdited ? id : tplId && !taken.has(tplId) && !label ? tplId : suggestId(label || 'page', taken).replace(/^w_/, 'p_')

  const create = async () => {
    if (!PAGE_ID_RE.test(shownId)) { toast.error(tr('Id invalide : minuscules, chiffres et _, 2 a 41 caracteres', 'Invalid id: lowercase, digits and _, 2 to 41 characters')); return }
    setBusy(true)
    try {
      let doc = emptyPage(shownId, label || shownId)
      if (from) {
        const [kind, ref] = from.split(':')
        const [fscope, fid] = kind === 'tpl' ? ['shipped', ref] : ref.split('/')
        const src = await flowsApi.getPage(fid, { scope: fscope as PageScope, project })
        doc = { ...src.page, id: shownId, label: label || src.page.label }
      }
      await flowsApi.savePage(doc, scope, { project, base_rev: null })
      navigate(`/tool/${shownId}/edit?scope=${scope}`, { replace: true })
    } catch (err) {
      toast.error((err as Error).message)
    } finally { setBusy(false) }
  }

  return (
    <div style={{ padding: 24, maxWidth: 520, display: 'flex', flexDirection: 'column', gap: 4 }}>
      <h1 style={{ fontSize: 17, fontWeight: 600, margin: '0 0 12px' }}>{tr('Nouvelle page TOOL', 'New TOOL page')}</h1>
      <PropRow label={tr('Libelle', 'Label')}><input autoFocus value={label} onChange={e => setLabel(e.target.value)} placeholder="Daily render" style={{ flex: 1, height: 26, padding: '0 8px', border: '1px solid var(--rule-2)', background: 'var(--bg-deep)', borderRadius: 5, color: 'var(--ink)' }} /></PropRow>
      <PropRow label="id"><input value={shownId} onChange={e => { setIdEdited(true); setId(e.target.value) }} style={{ flex: 1, height: 26, padding: '0 8px', border: '1px solid var(--rule-2)', background: 'var(--bg-deep)', borderRadius: 5, color: 'var(--ink)', fontFamily: 'var(--mono)' }} /></PropRow>
      <PropRow label={tr('Portee', 'Scope')}>
        <select value={scope} onChange={e => setScope(e.target.value as PageScope)} style={{ flex: 1, height: 26 }}>
          {canTeam && <option value="team">{tr('Equipe (tous les projets)', 'Team (every project)')}</option>}
          {canProject && project && <option value="project">{tr(`Projet ${project}`, `Project ${project}`)}</option>}
        </select>
      </PropRow>
      <PropRow label={tr('Depart', 'Start from')}>
        <select value={from} onChange={e => setFrom(e.target.value)} style={{ flex: 1, height: 26 }}>
          <option value="">{tr('Page vide', 'Empty page')}</option>
          {templates.map(t => <option key={t.id} value={`tpl:${t.id}`}>{tr('Modele : ', 'Template: ')}{t.label}</option>)}
          {pages.filter(p => !p.error).map(p => <option key={`${p.scope}/${p.id}`} value={`copy:${p.scope}/${p.id}`}>{tr('Copie de ', 'Copy of ')}{p.label}</option>)}
        </select>
      </PropRow>
      <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
        <button type="button" className="btn ghost" onClick={() => navigate('/tool')}>{tr('Annuler', 'Cancel')}</button>
        <button type="button" className="btn primary" disabled={busy} onClick={() => { void create() }}>{tr('Creer', 'Create')}</button>
      </div>
    </div>
  )
}

// -- tree -------------------------------------------------------------------------------------

function Tree({ items, sel, setSel, bad, depth = 0 }: { items: PageLayoutItem[]; sel: Sel; setSel: (s: Sel) => void; bad: Record<string, 'error' | 'warning'>; depth?: number }) {
  const { tr, lang } = useTr()
  return (
    <>
      {items.map((it, k) => 'folder' in it
        ? <div key={it.folder.id}>
            <Line depth={depth} on={sel?.kind === 'folder' && sel.id === it.folder.id} onClick={() => setSel({ kind: 'folder', id: it.folder.id })}
                  icon={<FolderPlus size={12} />} id={it.folder.id} label={`${it.folder.label || ''}${it.folder.mode && it.folder.mode !== 'plain' ? ` (${it.folder.mode === 'tabs' ? tr('onglet', 'tab') : tr('repliable', 'collapsible')})` : ''}`} state={bad[it.folder.id]} />
            <Tree items={it.children} sel={sel} setSel={setSel} bad={bad} depth={depth + 1} />
          </div>
        : <div key={`r${k}-${it.row[0]?.id}`} style={{ borderLeft: it.row.length > 1 ? '2px solid var(--rule-2)' : undefined, marginLeft: depth * 12 }}>
            {it.row.map(w => <Line key={w.id} depth={0} on={sel?.kind === 'widget' && sel.id === w.id} onClick={() => setSel({ kind: 'widget', id: w.id })}
                                   icon={<span className="cap" style={{ fontSize: 9.5 }}>{kindLabel(w.kind, lang).slice(0, 3)}</span>} id={w.id} label={w.label ?? w.text ?? ''} state={bad[w.id]}
                                   linked={!!(w.on_click || w.bind || w.source?.flow)} />)}
          </div>)}
    </>
  )
}

function Line({ depth, on, onClick, icon, id, label, state, linked }: { depth: number; on: boolean; onClick: () => void; icon: ReactNode; id: string; label: string; state?: 'error' | 'warning'; linked?: boolean }) {
  return (
    <div onClick={onClick} className={`nav${on ? ' active' : ''}`} style={{ paddingLeft: 6 + depth * 12, gap: 6, fontSize: 12, minHeight: 24 }}>
      <span style={{ width: 22, display: 'inline-flex', justifyContent: 'center', color: 'var(--ink-3)' }}>{icon}</span>
      <span style={{ fontFamily: 'var(--mono)', color: 'var(--ink)' }}>{id}</span>
      <span style={{ color: 'var(--ink-4)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>{label}</span>
      {(state || linked) && <span title={state ?? 'ok'} style={{ width: 7, height: 7, borderRadius: 4, background: state === 'error' ? 'var(--err)' : state === 'warning' ? 'var(--warn, var(--accent))' : 'var(--ok)' }} />}
    </div>
  )
}

// -- editor -----------------------------------------------------------------------------------

function Editor({ pageId, scope }: { pageId: string; scope: PageScope }) {
  const { tr, lang } = useTr()
  const navigate = useNavigate()
  const { project } = useProject()
  const store = useMemo(() => createDocStore<PageDoc>(), [])
  const doc = useStore(store, s => docOf(s))
  const dirty = useStore(store, s => isDirty(s))
  const [rev, setRev] = useState<string | null>(null)
  const [issues, setIssues] = useState<PageIssue[]>([])
  const [sel, setSel] = useState<Sel>({ kind: 'page' })
  const [flows, setFlows] = useState<FlowListItem[]>([])
  const [tab, setTab] = useState<'widgets' | 'templates'>('widgets')
  const [templates, setTemplates] = useState<PageListItem[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  const proj = project || undefined

  const load = useCallback(() => {
    flowsApi.getPage(pageId, { scope, project: proj })
      .then(r => { store.load(r.page); setRev(r.rev); setIssues(r.issues); setLoadError(null) })
      .catch(err => setLoadError((err as Error).message))
  }, [pageId, scope, proj, store])
  useEffect(() => { load() }, [load])
  useEffect(() => {
    flowsApi.list(proj).then(setFlows).catch(() => setFlows([]))
    flowsApi.listPages(proj).then(l => setTemplates(l.templates)).catch(() => setTemplates([]))
  }, [proj])

  // Live validation (debounce 300 ms).
  useEffect(() => {
    if (!doc) return
    let alive = true
    const t = setTimeout(() => {
      flowsApi.validatePage(doc, scope, proj).then(r => { if (alive) setIssues(r.issues) }).catch(() => { /* backend down: keep the last issues */ })
    }, 300)
    return () => { alive = false; clearTimeout(t) }
  }, [doc, scope, proj])

  const apply = useCallback((fn: (d: PageDoc) => PageDoc, key?: string) => store.apply(fn, key), [store])

  const save = useCallback(async (force = false): Promise<boolean> => {
    const cur = docOf(store.get())
    if (!cur) return true
    if (!isDirty(store.get()) && !force) return true
    try {
      const r = await flowsApi.savePage(cur, scope, { project: proj, base_rev: rev, force })
      setRev(r.rev)
      setIssues(r.issues)
      store.markSaved(cur)
      const errors = r.issues.filter(i => i.level === 'error').length
      if (errors) toast.warning(tr(`Page enregistree, ${errors} probleme(s) : les widgets concernes sont grises`, `Page saved, ${errors} problem(s): the widgets concerned are greyed`))
      else toast.success(tr('Page enregistree', 'Page saved'))
      return true
    } catch (err) {
      const e = err as HttpError
      if (e.status === 409 && window.confirm(tr(`${e.message}. Ecraser sa version ?`, `${e.message}. Overwrite their version?`))) return save(true)
      if (e.status !== 409) toast.error(e.message)
      return false
    }
  }, [store, scope, proj, rev, tr])

  // Ctrl+S, Ctrl+Z, Ctrl+Y / Ctrl+Shift+Z (not while typing in a field: the browser undoes the field).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey)) return
      const typing = /^(INPUT|TEXTAREA|SELECT)$/.test((e.target as HTMLElement)?.tagName ?? '')
      if (e.key.toLowerCase() === 's') { e.preventDefault(); void save() }
      else if (!typing && e.key.toLowerCase() === 'z' && !e.shiftKey) { e.preventDefault(); store.undo() }
      else if (!typing && (e.key.toLowerCase() === 'y' || (e.key.toLowerCase() === 'z' && e.shiftKey))) { e.preventDefault(); store.redo() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [save, store])

  const close = async () => { if (await save()) navigate(`/tool?page=${pageId}`) }

  const target: Target = sel?.kind === 'widget' ? { widget: sel.id } : sel?.kind === 'folder' ? { folder: sel.id } : null
  const add = (kind: PageWidgetKind) => {
    if (!doc) return
    const { widget, data } = newWidget(kind, doc, lang)
    apply(d => addWidget(data ? addData(d, data) : d, widget, target))
    setSel({ kind: 'widget', id: widget.id })
  }
  const addCollection = () => {
    if (!doc) return
    const taken = new Set(doc.data.map(d => d.id))
    let id = 'donnees'
    for (let n = 2; taken.has(id); n++) id = `donnees_${n}`
    apply(d => addData(d, { id, fields: [{ id: 'name', type: 'str', label: 'Nom' }] }))
    setSel({ kind: 'data', id })
  }

  const widget = doc && sel?.kind === 'widget' ? findWidget(doc, sel.id) : undefined
  const folder = doc && sel?.kind === 'folder' ? findFolder(doc, sel.id) : undefined
  const spec = doc && sel?.kind === 'data' ? doc.data.find(d => d.id === sel.id) : undefined

  // A linked button keeps its flow in step (page + flow in one backend operation);
  // anything else is renamed in the document.
  const rename = async (w: PageWidget, next: string) => {
    if (!doc) return
    if (takenIds(doc).has(next)) { toast.error(tr(`L'id ${next} existe deja`, `The id ${next} already exists`)); return }
    const linked = w.kind === 'button' && w.on_click?.button_id === w.id
    if (!linked) { apply(d => renameLocal(d, w.id, next)); setSel({ kind: 'widget', id: next }); return }
    if (dirty && !(await save())) return
    try {
      const plan = await flowsApi.renameWidget(pageId, scope, w.id, next, { project: proj })
      const files = plan.files.map(f => f.kind === 'flow' ? `flows/${f.id} (v${f.next_version})` : `pages/${f.id}.yml`)
      if (!window.confirm(tr(`${files.length} fichier(s) seront modifies : ${files.join(', ')}. Renommer ?`, `${files.length} file(s) will change: ${files.join(', ')}. Rename?`))) return
      await flowsApi.renameWidget(pageId, scope, w.id, next, { apply: true, project: proj, base_rev: rev ?? undefined })
      if (plan.files.some(f => f.kind === 'flow')) toast.info(tr('Le flow a une nouvelle version : active-la pour que le bouton marche', 'The flow has a new version: activate it so the button works'))
      load()
      setSel({ kind: 'widget', id: next })
    } catch (err) { toast.error((err as Error).message) }
  }

  // "Au clic": the flow gets its event.button node (new version, confirmed), then the page points to it.
  const linkButton = async (w: PageWidget, flow: string) => {
    const info = flows.find(f => f.name === flow)
    const next = (info?.current ?? 0) + 1
    if (!window.confirm(tr(`Le flow ${flow} recoit un node Bouton "${w.id}" si il ne l'a pas encore (cree la version v${String(next).padStart(3, '0')}). Continuer ?`,
                           `The flow ${flow} gets a Button node "${w.id}" if it has none yet (creates version v${String(next).padStart(3, '0')}). Continue?`))) return
    try {
      const r = await flowsApi.linkButton(flow, w.id, proj)
      apply(d => updateWidget(d, w.id, { on_click: { flow, button_id: w.id } }))
      toast.success(r.created ? tr(`Node Bouton ajoute a ${flow} (v${r.version})`, `Button node added to ${flow} (v${r.version})`) : tr(`${flow} a deja ce bouton`, `${flow} already has this button`))
      flowsApi.list(proj).then(setFlows).catch(() => { /* list kept */ })
    } catch (err) { toast.error((err as Error).message) }
  }

  const remove = () => {
    if (sel?.kind === 'widget' || sel?.kind === 'folder') { const id = sel.id; apply(d => removeItem(d, id)); setSel({ kind: 'page' }) }
    else if (sel?.kind === 'data') { const id = sel.id; apply(d => removeData(d, id)); setSel({ kind: 'page' }) }
  }
  const move = (dir: -1 | 1, inRow = false) => { if (sel?.kind === 'widget' || sel?.kind === 'folder') { const id = sel.id; apply(d => moveItem(d, id, dir, inRow)) } }

  const deletePage = async () => {
    if (!window.confirm(tr(`Supprimer la page ${pageId} ? (copie gardee dans _trash)`, `Delete the page ${pageId}? (copy kept in _trash)`))) return
    try { await flowsApi.deletePage(pageId, scope, proj); store.load(null); navigate('/tool') } catch (err) { toast.error((err as Error).message) }
  }

  if (loadError) return <div style={{ padding: 20 }} className="cap">{loadError}</div>
  if (!doc) return <div style={{ padding: 20 }} className="cap">{tr('Chargement...', 'Loading...')}</div>

  const bad: Record<string, 'error' | 'warning'> = {}
  for (const i of issues) if (i.widget && bad[i.widget] !== 'error') bad[i.widget] = i.level
  const Icon = pageIcon(doc.icon)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', borderBottom: '1px solid var(--rule)' }}>
        <Icon size={16} />
        <span style={{ fontWeight: 600 }}>{doc.label || doc.id}</span>
        <span className="tag">{scope === 'team' ? tr('equipe', 'team') : tr('projet', 'project')}</span>
        {dirty && <span className="cap" style={{ color: 'var(--ink-3)' }}>{tr('modifie', 'modified')}</span>}
        <span style={{ flex: 1 }} />
        <button type="button" className="btn ghost sm" title="Ctrl+Z" onClick={() => store.undo()}><Undo2 size={12} /></button>
        <button type="button" className="btn ghost sm" title="Ctrl+Y" onClick={() => store.redo()}><Redo2 size={12} /></button>
        <button type="button" className="btn sm" title="Ctrl+S" onClick={() => { void save() }}><Save size={12} /> {tr('Enregistrer', 'Save')}</button>
        <button type="button" className="btn ghost sm" onClick={() => { void deletePage() }} title={tr('Supprimer la page', 'Delete the page')}><Trash2 size={12} /></button>
        <button type="button" className="btn ghost sm" onClick={() => { void close() }}><X size={12} /> {tr('Fermer', 'Close')}</button>
      </div>
      <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
        {/* Palette */}
        <div style={col(200)}>
          <div style={{ display: 'flex', gap: 4, marginBottom: 8 }}>
            <button type="button" className={`btn sm${tab === 'widgets' ? '' : ' ghost'}`} onClick={() => setTab('widgets')}>{tr('Widgets', 'Widgets')}</button>
            <button type="button" className={`btn sm${tab === 'templates' ? '' : ' ghost'}`} onClick={() => setTab('templates')}>{tr('Modeles', 'Templates')}</button>
          </div>
          {tab === 'widgets' ? PALETTE.map((group, g) => (
            <div key={g} style={{ marginBottom: 10 }}>
              <div className="cap" style={{ marginBottom: 4 }}>{[tr('Formulaire', 'Form'), tr('Decor', 'Decor'), tr('Donnees', 'Data')][g]}</div>
              {group.map(kind => (
                <button type="button" key={kind} className="btn ghost sm" style={{ width: '100%', justifyContent: 'flex-start', marginBottom: 2 }} onClick={() => add(kind)}
                        title={tr('Ajoute sous la selection', 'Adds below the selection')}>{kindLabel(kind, lang)}</button>
              ))}
            </div>
          )) : (
            <div>
              <div className="cap" style={{ marginBottom: 6, color: 'var(--ink-4)' }}>{tr('Un modele cree une nouvelle page (Nouvelle page > Depart).', 'A template creates a new page (New page > Start from).')}</div>
              {templates.map(t => <div key={t.id} className="cap" style={{ padding: '3px 0', color: 'var(--ink-2)' }}>{t.label}</div>)}
              <button type="button" className="btn sm" style={{ marginTop: 8 }} onClick={() => { void close().then(() => navigate('/tool/new/edit')) }}>{tr('Nouvelle page', 'New page')}</button>
            </div>
          )}
        </div>

        {/* Tree */}
        <div style={col(280, { display: 'flex', flexDirection: 'column' })}>
          <div style={{ display: 'flex', gap: 2, marginBottom: 6, flexWrap: 'wrap' }}>
            <button type="button" className="btn ghost sm" title={tr('Monter', 'Up')} onClick={() => move(-1)}><ArrowUp size={12} /></button>
            <button type="button" className="btn ghost sm" title={tr('Descendre', 'Down')} onClick={() => move(1)}><ArrowDown size={12} /></button>
            <button type="button" className="btn ghost sm" title={tr('A gauche dans la ligne', 'Left in the row')} onClick={() => move(-1, true)}><ArrowLeft size={12} /></button>
            <button type="button" className="btn ghost sm" title={tr('A droite dans la ligne', 'Right in the row')} onClick={() => move(1, true)}><ArrowRight size={12} /></button>
            <button type="button" className="btn ghost sm" title={tr('Sortir de la ligne', 'Out of the row')} onClick={() => { if (sel?.kind === 'widget') { const id = sel.id; apply(d => splitOut(d, id)) } }}><Columns2 size={12} /></button>
            <button type="button" className="btn ghost sm" title={tr('Nouveau dossier', 'New folder')}
                    onClick={() => { const id = suggestId('dossier', takenIds(doc)); apply(d => addFolder(d, { id, label: tr('Dossier', 'Folder'), mode: 'plain' }, target)); setSel({ kind: 'folder', id }) }}><FolderPlus size={12} /></button>
            <button type="button" className="btn ghost sm" title={tr('Nouvelle collection de donnees', 'New data collection')} onClick={addCollection}><Database size={12} /></button>
            <button type="button" className="btn ghost sm" title={tr('Supprimer', 'Delete')} onClick={remove}><Trash2 size={12} /></button>
          </div>
          <div onClick={() => setSel({ kind: 'page' })} className={`nav${sel?.kind === 'page' ? ' active' : ''}`} style={{ fontSize: 12 }}>{tr('Page', 'Page')}</div>
          <Tree items={doc.layout} sel={sel} setSel={setSel} bad={bad} />
          <div className="cap" style={{ margin: '12px 0 4px' }}>{tr('Donnees', 'Data')}</div>
          {doc.data.map(d => (
            <div key={d.id} onClick={() => setSel({ kind: 'data', id: d.id })} className={`nav${sel?.kind === 'data' && sel.id === d.id ? ' active' : ''}`} style={{ fontSize: 12, gap: 6 }}>
              <Database size={12} /> <span style={{ fontFamily: 'var(--mono)' }}>{d.id}</span> <span className="cap">{d.kind === 'board' ? 'board' : `${d.fields?.length ?? 0} ${tr('champs', 'fields')}`}</span>
            </div>
          ))}
          <div className="cap" style={{ margin: '12px 0 4px' }}>{tr('Problemes', 'Problems')} ({issues.length})</div>
          <div style={{ flex: 1, minHeight: 60 }}>
            {issues.map((i, k) => (
              <div key={k} onClick={() => i.widget && setSel(findFolder(doc, i.widget) ? { kind: 'folder', id: i.widget } : { kind: 'widget', id: i.widget })}
                   style={{ fontSize: 11.5, padding: '3px 4px', cursor: i.widget ? 'pointer' : 'default', color: i.level === 'error' ? 'var(--err)' : 'var(--ink-3)' }} title={lang === 'en' ? i.why_en : i.why_fr}>
                {lang === 'en' ? i.message_en : i.message_fr}
              </div>
            ))}
          </div>
        </div>

        {/* Properties */}
        <div style={col(300)}>
          {sel?.kind === 'page' && <>
            <PropRow label="id"><span className="tag" style={{ fontFamily: 'var(--mono)' }}>{doc.id}</span></PropRow>
            <PropRow label={tr('Libelle', 'Label')}><input value={doc.label ?? ''} onChange={e => { const v = e.target.value; apply(d => ({ ...d, label: v }), 'page:label') }} style={{ flex: 1, height: 24 }} /></PropRow>
            <PropRow label={tr('Icone', 'Icon')}>
              <select value={doc.icon ?? 'wrench'} onChange={e => { const v = e.target.value; apply(d => ({ ...d, icon: v })) }} style={{ flex: 1, height: 24 }}>
                {Object.keys(PAGE_ICONS).map(k => <option key={k} value={k}>{k}</option>)}
              </select>
            </PropRow>
            <PropRow label={tr('Description', 'Description')}><input value={doc.description ?? ''} onChange={e => { const v = e.target.value; apply(d => ({ ...d, description: v || undefined }), 'page:desc') }} style={{ flex: 1, height: 24 }} /></PropRow>
          </>}
          {widget && <WidgetProps key={widget.id} doc={doc} w={widget} scope={scope} project={proj} flows={flows}
                                  onPatch={(p, key) => apply(d => updateWidget(d, widget.id, p), key)}
                                  onRename={next => { void rename(widget, next) }}
                                  onLinkButton={flow => { void linkButton(widget, flow) }}
                                  onOpenFlow={flow => { if (window.electronAPI?.detachPage) window.electronAPI.detachPage(`/action-graph?flow=${encodeURIComponent(flow)}`); else navigate(`/action-graph?flow=${encodeURIComponent(flow)}`) }} />}
          {folder && <FolderProps key={folder.id} f={folder} onPatch={(p, key) => apply(d => updateFolder(d, folder.id, p), key)}
                                  onRename={next => { if (takenIds(doc).has(next)) toast.error(tr('Id deja pris', 'Id already taken')); else { apply(d => renameLocal(d, folder.id, next)); setSel({ kind: 'folder', id: next }) } }} />}
          {spec && <DataProps key={spec.id} spec={spec} scope={scope} onPatch={(p, key) => apply(d => updateData(d, spec.id, p), key)} onRemove={remove} />}
        </div>

        {/* Preview */}
        <div style={{ flex: 1, minWidth: 0, overflowY: 'auto', padding: '14px 18px', background: 'var(--paper)' }}>
          <div className="cap" style={{ marginBottom: 10, color: 'var(--ink-4)' }}>{tr('Apercu : les boutons ne lancent rien', 'Preview: buttons run nothing')}</div>
          <PageRenderer page={doc} issues={issues} project={proj} preview selected={sel?.kind === 'widget' ? sel.id : null}
                        onSelect={id => setSel({ kind: 'widget', id })}
                        renderData={w => <DataWidget page={doc} widget={w} project={proj} preview />} />
        </div>
      </div>
    </div>
  )
}

export function PageBuilder() {
  const { id = 'new' } = useParams()
  const [params] = useSearchParams()
  const { project } = useProject()
  const [list, setList] = useState<{ pages: PageListItem[]; templates: PageListItem[]; can: { team: boolean; project: boolean } } | null>(null)
  useEffect(() => {
    if (id !== 'new') return
    flowsApi.listPages(project || undefined)
      .then(l => setList({ pages: l.pages, templates: l.templates, can: l.can_edit }))
      .catch(() => setList({ pages: [], templates: [], can: { team: false, project: false } }))
  }, [id, project])
  if (id === 'new') {
    if (!list) return null
    return <NewPage project={project || undefined} canTeam={list.can.team} canProject={list.can.project} templates={list.templates} pages={list.pages} />
  }
  const scope = (params.get('scope') as PageScope) || 'team'
  return <Editor key={`${scope}/${id}`} pageId={id} scope={scope} />
}
