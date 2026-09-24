// UsdLibrary.tsx — the USD page content: everything already published in the project.
// Left: assets (components created by hand, ADR 0023) and decors (assemblies), with search.
// Right: one entity in four views, like a documented USD pipeline tool (AYON scene
// inventory / Solaris stage manager): Content (departments or instances, editable),
// Versions, Composition (what the file really gives) and Dependencies.
// Backend: GET /usd/library, /usd/composition, POST /usd/component/{create,save,refresh,add-proposed},
// /usd/assembly/{create,edit,layout/publish}.

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Box, Boxes, RefreshCw, Copy, AlertTriangle, Search, Pencil, Check, X, Trash2, Pin as PinIcon, FolderOpen, ClipboardList, Plus, CopyPlus, Upload } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { Btn, SecTitle, Pill } from '../../components/shared/ui'
import { api } from '../../api/client'
import type {
  UsdAssemblyInfo, UsdAssemblyOp, UsdComponentFile, UsdComponentInfo, UsdComponentRecipe, UsdComponentResult,
  UsdComponentRules, UsdComposition, UsdCrowdCompat, UsdFileKind, UsdLibrary as Library, UsdPrimNode, UsdProposedFile,
} from '../../api/client'
import { useI18n } from '../../i18n'

type Tab = 'components' | 'assemblies'
type DetailTab = 'content' | 'versions' | 'composition' | 'deps'
type Selection = { tab: Tab; name: string } | null

const stateColor: Record<UsdComponentInfo['state'], string> = {
  ok: 'var(--ok)', stale: 'var(--warn)', empty: 'var(--ink-4)',
}

const mono: React.CSSProperties = { fontFamily: 'var(--mono)', fontSize: 10.5 }

export function UsdLibrary({ project, projects, onProject }: {
  project: string | null | undefined; projects: string[]; onProject: (name: string) => void
}) {
  const { t: tr } = useI18n()
  const [lib, setLib] = useState<Library | null>(null)
  const [loading, setLoading] = useState(false)
  const [tab, setTab] = useState<Tab>('components')
  const [query, setQuery] = useState('')
  const [sel, setSel] = useState<Selection>(null)
  const [legacy, setLegacy] = useState<{ name: string; rel_path: string }[]>([])

  const load = useCallback(() => {
    if (!project) { setLib(null); return }
    setLoading(true)
    api.getUsdLibrary(project)
      .then(setLib)
      .catch(e => { setLib(null); toast.error(e instanceof Error ? e.message : String(e)) })
      .finally(() => setLoading(false))
    // V4: old flat Constructor files, never imported, deletable (moved to a backup).
    api.getUsdLegacy(project)
      .then(r => setLegacy(r.files))
      .catch(() => setLegacy([]))
  }, [project])

  useEffect(() => { load() }, [load])

  const q = query.trim().toLowerCase()
  const components = useMemo(
    () => (lib?.components ?? []).filter(c => !q || c.name.toLowerCase().includes(q)), [lib, q])
  const assemblies = useMemo(
    () => (lib?.assemblies ?? []).filter(a => !q || a.name.toLowerCase().includes(q)), [lib, q])

  const selComponent = sel?.tab === 'components' ? lib?.components.find(c => c.name === sel.name) : undefined
  const selAssembly = sel?.tab === 'assemblies' ? lib?.assemblies.find(a => a.name === sel.name) : undefined

  useEffect(() => { setSel(null) }, [project])

  // Changing section drops the previous selection: the right panel waits for a new pick.
  function switchTab(tabName: Tab) {
    if (tabName === tab) return
    setTab(tabName)
    setSel(null)
  }

  function goTo(tabName: Tab, name: string) {
    setTab(tabName)
    setQuery('')
    setSel({ tab: tabName, name })
  }

  const projectPicker = (
    <select value={project ?? ''} onChange={e => onProject(e.target.value)} title={tr('usd.project')}
      style={{ ...selectStyle, width: '100%', height: 26 }}>
      {!project && <option value="">{tr('usd.lib.noProject')}</option>}
      {projects.map(p => <option key={p} value={p}>{p}</option>)}
    </select>
  )

  if (!project) {
    return <div style={{ padding: 20, width: 320, display: 'flex', flexDirection: 'column', gap: 8 }}>{projectPicker}</div>
  }

  return (
    <div style={{ flex: 1, display: 'flex', minHeight: 0, overflow: 'hidden' }}>
      {/* ── left: list ─────────────────────────────────────────────────────── */}
      <div style={{ width: 320, flexShrink: 0, borderRight: '1px solid var(--rule)', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
        <div style={{ padding: '12px 14px 8px', display: 'flex', flexDirection: 'column', gap: 8 }}>
          {projectPicker}
          <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
            <Pill active={tab === 'components'} onClick={() => switchTab('components')} style={{ cursor: 'pointer' }}>
              {tr('usd.lib.components')} {lib ? lib.components.length : ''}
            </Pill>
            <Pill active={tab === 'assemblies'} onClick={() => switchTab('assemblies')} style={{ cursor: 'pointer' }}>
              {tr('usd.lib.assemblies')} {lib ? lib.assemblies.length : ''}
            </Pill>
            <div style={{ flex: 1 }} />
            <Btn sm ghost title={tr('usd.lib.refresh')} onClick={load}>
              <RefreshCw size={11} strokeWidth={2} style={loading ? { animation: 'spin 1s linear infinite' } : undefined} />
            </Btn>
          </div>
          <div style={{ position: 'relative' }}>
            <Search size={11} strokeWidth={2} color="var(--ink-4)" style={{ position: 'absolute', left: 8, top: 8 }} />
            <input
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder={tr('usd.lib.search')}
              style={{
                width: '100%', height: 26, padding: '0 8px 0 24px', borderRadius: 5, border: '1px solid var(--rule-2)',
                background: 'var(--bg-deep)', color: 'var(--ink)', fontSize: 11, outline: 'none', boxSizing: 'border-box',
              }}
            />
          </div>
        </div>

        {tab === 'components' && lib && (
          <NewComponent project={project} creatable={lib.creatable} departments={lib.departments}
            onCreated={name => { load(); goTo('components', name) }} />
        )}
        {tab === 'assemblies' && lib && (
          <NewAssembly project={project} assemblies={lib.assemblies}
            onCreated={name => { load(); goTo('assemblies', name) }} />
        )}
        <div style={{ flex: 1, overflowY: 'auto', padding: '0 8px 12px', display: 'flex', flexDirection: 'column', gap: 2 }}>
          {tab === 'components' && components.map(c => (
            <ListRow key={c.name} active={sel?.tab === 'components' && sel.name === c.name}
              onClick={() => setSel({ tab: 'components', name: c.name })}
              icon={<Box size={12} strokeWidth={1.75} />}
              title={c.name}
              meta={<>
                <span style={{ ...mono, color: 'var(--ink-3)' }}>{c.version ?? '-'}</span>
                <span style={{ width: 6, height: 6, borderRadius: 3, background: stateColor[c.state], flexShrink: 0 }} />
              </>}
              sub={`${c.departments.join(' · ') || '-'}  ·  ${tr('usd.comp.fileCount', { n: c.files.length })}${c.used_by.length ? `  ·  ${c.used_by.length} asm` : ''}`}
            />
          ))}
          {tab === 'assemblies' && assemblies.map(a => (
            <ListRow key={a.file} active={sel?.tab === 'assemblies' && sel.name === a.name}
              onClick={() => setSel({ tab: 'assemblies', name: a.name })}
              icon={<Boxes size={12} strokeWidth={1.75} />}
              title={a.name}
              meta={<>
                <span style={{ ...mono, color: 'var(--ink-3)' }}>{a.version ?? '-'}</span>
                {a.broken > 0 && <AlertTriangle size={11} strokeWidth={2} color="var(--err)" />}
              </>}
              sub={`${a.instances.length} ${tr('usd.lib.instances').toLowerCase()}`}
            />
          ))}
          {tab === 'assemblies' && legacy.length > 0 && (
            <div style={{ marginTop: 10, padding: '8px 6px', borderTop: '1px solid var(--rule)' }}>
              <div className="lbl" style={{ fontSize: 10, color: 'var(--ink-3)', marginBottom: 4 }}>
                Anciens fichiers ({legacy.length}) : plus proposes a l'import
              </div>
              {legacy.map(f => (
                <div key={f.rel_path} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 10.5 }}>
                  <span style={{ ...mono, flex: 1, color: 'var(--ink-3)', overflow: 'hidden', textOverflow: 'ellipsis' }} title={f.rel_path}>{f.name}</span>
                  <Btn sm ghost title="Deplace le fichier dans <projet>/_backup_flux (rien n'est efface)"
                    onClick={() => {
                      if (!project) return
                      api.deleteUsdLegacy(project, f.rel_path)
                        .then(() => { toast.success(`${f.name} deplace dans le backup`); load() })
                        .catch(e => toast.error(e instanceof Error ? e.message : String(e)))
                    }}>
                    <Trash2 size={10} strokeWidth={2} /> Supprimer
                  </Btn>
                </div>
              ))}
            </div>
          )}
          {lib &&(tab === 'components' ? components : assemblies).length === 0 && (
            <div className="lbl" style={{ padding: '8px 6px', fontSize: 10, color: 'var(--ink-4)', lineHeight: 1.5 }}>
              {tr('usd.lib.empty')}
              {tab === 'components' && <><br />{tr('usd.lib.emptyAssets')}</>}
            </div>
          )}
        </div>
      </div>

      {/* ── right: detail ──────────────────────────────────────────────────── */}
      <div style={{ flex: 1, minWidth: 0, overflowY: 'auto', padding: '14px 20px 20px' }}>
        {selComponent ? (
          <ComponentDetail project={project} comp={selComponent} departments={lib?.departments ?? []}
            rules={lib?.rules as UsdComponentRules} onChanged={load} onOpenAssembly={n => goTo('assemblies', n)} />
        ) : selAssembly ? (
          <AssemblyDetail project={project} asm={selAssembly} components={lib?.components ?? []}
            onOpenComponent={n => goTo('components', n)} onChanged={load} />
        ) : (
          <div className="lbl" style={{ fontSize: 11, color: 'var(--ink-4)' }}>{tr('usd.lib.pick')}</div>
        )}
      </div>
    </div>
  )
}

function ListRow({ active, onClick, icon, title, meta, sub }: {
  active: boolean; onClick: () => void; icon: React.ReactNode; title: string; meta: React.ReactNode; sub: string
}) {
  return (
    <div onClick={onClick} className="row" style={{
      padding: '6px 8px', borderRadius: 5, cursor: 'pointer',
      background: active ? 'var(--accent-soft)' : undefined,
      display: 'flex', flexDirection: 'column', gap: 2,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: active ? 'var(--accent-hi)' : 'var(--ink-3)' }}>
        {icon}
        <span style={{ fontSize: 11.5, fontWeight: 500, color: active ? 'var(--accent-hi)' : 'var(--ink)', flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{title}</span>
        {meta}
      </div>
      <span className="lbl" style={{ fontSize: 9.5, color: 'var(--ink-4)', paddingLeft: 18 }}>{sub}</span>
    </div>
  )
}

function copy(text: string, okMsg: string) {
  navigator.clipboard.writeText(text).then(() => toast.success(okMsg)).catch(() => toast.error(text))
}

const selectStyle: React.CSSProperties = {
  height: 24, padding: '0 6px', borderRadius: 5, border: '1px solid var(--rule-2)',
  background: 'var(--bg-deep)', color: 'var(--ink)', fontSize: 11, outline: 'none', cursor: 'pointer',
}

function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

// ── component (ADR 0023): created by hand, files per department with targets ──

function toRecipe(comp: UsdComponentInfo): UsdComponentRecipe {
  return {
    departments: [...comp.departments],
    files: comp.files.map(({ resolved_version: _r, composed_version: _c, found: _f, ...f }) => ({ ...f })),
  }
}

function fmtOf(path: string): string {
  const name = path.replace(/\\/g, '/').split('/').pop()?.toLowerCase() ?? ''
  if (name.endsWith('.bgeo.sc')) return 'bgeo.sc'
  return name.includes('.') ? name.split('.').pop() ?? '' : ''
}

function makeId(label: string, taken: Set<string>): string {
  let base = label.replace(/[^A-Za-z0-9_]/g, '_').replace(/^_+|_+$/g, '') || 'file'
  if (!/^[A-Za-z_]/.test(base)) base = `f_${base}`
  let out = base
  for (let n = 2; taken.has(out); n++) out = `${base}_${n}`
  return out
}

// Yellow panel (ADR 0023 point 9): informs only, never changes a selection.
function WarningPanel({ warnings }: { warnings: string[] }) {
  if (warnings.length === 0) return null
  return (
    <div style={{
      padding: '8px 10px', borderRadius: 6, border: '1px solid var(--warn)',
      background: 'color-mix(in oklch, var(--warn) 10%, var(--paper-2))',
      display: 'flex', flexDirection: 'column', gap: 3,
    }}>
      {warnings.map(w => (
        <span key={w} style={{ fontSize: 11, color: 'var(--warn)', display: 'flex', gap: 6, alignItems: 'flex-start', lineHeight: 1.45 }}>
          <AlertTriangle size={11} strokeWidth={2} style={{ flexShrink: 0, marginTop: 2 }} /> {w}
        </span>
      ))}
    </div>
  )
}

function NewComponent({ project, creatable, departments, onCreated }: {
  project: string; creatable: string[]; departments: string[]; onCreated: (name: string) => void
}) {
  const { t: tr } = useI18n()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [picked, setPicked] = useState<string[]>([])
  const [busy, setBusy] = useState(false)

  async function create() {
    setBusy(true)
    try {
      const res = await api.createUsdComponent(project, name, picked)
      toast.success(tr('usd.lib.saved', { name, version: res.version ?? '' }))
      setOpen(false); setName(''); setPicked([])
      onCreated(name)
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setBusy(false)
    }
  }

  if (!open) {
    return (
      <div style={{ padding: '0 14px 8px' }}>
        <Btn sm ghost disabled={creatable.length === 0} title={creatable.length === 0 ? tr('usd.comp.noCreatable') : undefined}
          onClick={() => setOpen(true)}>
          <Plus size={11} strokeWidth={2} /> {tr('usd.comp.new')}
        </Btn>
      </div>
    )
  }
  return (
    <div className="card" style={{ margin: '0 14px 8px', padding: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
      <select value={name} onChange={e => setName(e.target.value)} style={{ ...selectStyle, width: '100%', height: 26 }}>
        <option value="">{tr('usd.comp.pickAsset')}</option>
        {creatable.map(n => <option key={n} value={n}>{n}</option>)}
      </select>
      <span className="cap">{tr('usd.lib.departments')}</span>
      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
        {departments.map(d => (
          <Pill key={d} active={picked.includes(d)} style={{ cursor: 'pointer' }}
            onClick={() => setPicked(p => p.includes(d) ? p.filter(x => x !== d) : [...p, d])}>{d}</Pill>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
        <Btn sm ghost disabled={busy} onClick={() => setOpen(false)}><X size={11} strokeWidth={2} /></Btn>
        <Btn sm primary disabled={busy || !name || picked.length === 0} onClick={() => void create()}>
          <Check size={11} strokeWidth={2} /> {tr('usd.lib.create')}
        </Btn>
      </div>
    </div>
  )
}

// Versions of one published base: "latest" follows its LAST, a vNNN freezes it.
function VersionSelect({ project, name, file, disabled, onChange }: {
  project: string; name: string; file: UsdComponentFile; disabled: boolean; onChange: (v: string) => void
}) {
  const { t: tr } = useI18n()
  const [versions, setVersions] = useState<string[]>([])
  useEffect(() => {
    api.getUsdLayers(project, name, file.department, file.instance ?? '')
      .then(d => setVersions(Object.keys(d.versions).filter(v => v !== 'LAST')
        .sort((a, b) => Number(b.slice(1)) - Number(a.slice(1)))))
      .catch(() => setVersions([]))
  }, [project, name, file.department, file.instance])
  const value = file.version ?? 'latest'
  return (
    <select value={value} disabled={disabled} onChange={e => onChange(e.target.value)}
      style={{ ...selectStyle, width: 104, fontFamily: 'var(--mono)' }}>
      <option value="latest">{tr('usd.lib.followLatest')}</option>
      {!versions.includes(value) && value !== 'latest' && <option value={value}>{value}</option>}
      {versions.map(v => <option key={v} value={v}>{v}</option>)}
    </select>
  )
}

function IdPills({ label, ids, candidates, disabled, onToggle }: {
  label: string; ids: string[]; candidates: UsdComponentFile[]; disabled: boolean; onToggle: (id: string) => void
}) {
  if (candidates.length === 0) return null
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap', paddingLeft: 22 }}>
      <span className="cap" style={{ width: 70 }}>{label}</span>
      {candidates.map(c => (
        <Pill key={c.id} active={ids.includes(c.id)} style={{ cursor: disabled ? 'default' : 'pointer' }}
          onClick={() => { if (!disabled) onToggle(c.id) }}>{c.label}</Pill>
      ))}
    </div>
  )
}

function ComponentDetail({ project, comp, departments, rules, onChanged, onOpenAssembly }: {
  project: string; comp: UsdComponentInfo; departments: string[]; rules: UsdComponentRules
  onChanged: () => void; onOpenAssembly: (name: string) => void
}) {
  const { t: tr } = useI18n()
  const navigate = useNavigate()
  const [tab, setTab] = useState<DetailTab>('content')
  const [draft, setDraft] = useState<UsdComponentRecipe>(() => toRecipe(comp))
  const [manual, setManual] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  useEffect(() => { setDraft(toRecipe(comp)); setManual({}) }, [comp])
  const dirty = JSON.stringify(draft) !== JSON.stringify(toRecipe(comp))
  const assetDir = comp.dir.replace(/[\\/]usd[\\/]?$/i, '')
  const byId = new Map(comp.files.map(f => [f.id, f]))

  async function run(call: () => Promise<UsdComponentResult>) {
    setBusy(true)
    try {
      const res = await call()
      if (res.changed) toast.success(tr('usd.lib.saved', { name: comp.name, version: res.version ?? '' }))
      else toast.info(tr('usd.lib.noChange'))
      onChanged()
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setBusy(false)
    }
  }

  const patch = (id: string, p: Partial<UsdComponentFile>) =>
    setDraft(d => ({ ...d, files: d.files.map(f => f.id === id ? { ...f, ...p } : f) }))
  const toggleIn = (id: string, field: 'targets' | 'proxy_of' | 'depends', other: string) =>
    setDraft(d => ({ ...d, files: d.files.map(f => f.id !== id ? f : {
      ...f, [field]: f[field].includes(other) ? f[field].filter(x => x !== other) : [...f[field], other] }) }))
  const removeFile = (id: string) => setDraft(d => ({
    ...d, files: d.files.filter(f => f.id !== id).map(f => ({
      ...f, targets: f.targets.filter(x => x !== id), proxy_of: f.proxy_of.filter(x => x !== id),
      depends: f.depends.filter(x => x !== id) })) }))
  const taken = () => new Set(draft.files.map(f => f.id))

  function addProposed(p: UsdProposedFile) {
    const id = makeId(`${p.department.toLowerCase()}_${p.instance}${p.variante ? `_${p.variante}` : ''}`, taken())
    setDraft(d => ({ ...d, files: [...d.files, {
      id, label: p.base, department: p.department, kind: p.kind, format: p.format, source: 'publish',
      base: p.base, instance: p.instance, variante: p.variante, version: 'latest',
      targets: [], proxy_of: [], depends: [], active: !rules.preview.includes(p.kind),
    }] }))
  }

  function addManual(dept: string) {
    const path = (manual[dept] ?? '').trim()
    if (!path || !fmtOf(path)) return
    const stem = path.replace(/\\/g, '/').split('/').pop()?.replace(/\.[^.]+$/, '') ?? 'file'
    const kind = rules.default_kind[dept] ?? 'other'
    setDraft(d => ({ ...d, files: [...d.files, {
      id: makeId(stem, taken()), label: stem, department: dept, kind, format: fmtOf(path), source: 'manual',
      path, targets: [], proxy_of: [], depends: [], active: !rules.preview.includes(kind),
    }] }))
    setManual(m => ({ ...m, [dept]: '' }))
  }

  const freeDepartments = departments.filter(d => !draft.departments.includes(d))
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxWidth: 900 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <Box size={15} strokeWidth={1.75} color="var(--ink-3)" />
        <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--ink)' }}>{comp.name}</span>
        {comp.version && <span style={{ ...mono, color: 'var(--ink-3)' }}>{comp.version}</span>}
        <span className="lbl" style={{ fontSize: 10, color: stateColor[comp.state] }}>{tr(`usd.lib.state.${comp.state}`)}</span>
        <div style={{ flex: 1 }} />
        <Btn sm ghost onClick={() => navigate('/projects', { state: { openPath: assetDir } })} title={assetDir}>
          <FolderOpen size={11} strokeWidth={2} /> {tr('usd.lib.openFolder')}
        </Btn>
        {comp.class && (
          <Btn sm ghost onClick={() => navigate('/production', {
            state: { openFavorite: { project, class: comp.class, name: comp.name, task: comp.departments[0] ?? 'GEO' } },
          })}>
            <ClipboardList size={11} strokeWidth={2} /> {tr('usd.lib.openProduction')}
          </Btn>
        )}
        {comp.last && (
          <Btn sm ghost onClick={() => copy(comp.last as string, tr('usd.lib.copied'))} title={comp.last}>
            <Copy size={11} strokeWidth={2} /> {tr('usd.lib.copyPath')}
          </Btn>
        )}
        {comp.state === 'stale' && !dirty && (
          <Btn sm primary disabled={busy} onClick={() => void run(() => api.refreshUsdComponent(project, comp.name))}>
            <RefreshCw size={11} strokeWidth={2} /> {tr('usd.lib.update')}
          </Btn>
        )}
      </div>

      <DetailTabs tab={tab} onTab={setTab} />

      {tab === 'content' && (<>
        <WarningPanel warnings={comp.warnings} />
        {comp.legacy && (
          <span className="lbl" style={{ fontSize: 10, color: 'var(--warn)' }}>{tr('usd.comp.legacy')}</span>
        )}

        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
          <SecTitle>{tr('usd.lib.departments')}</SecTitle>
          <div style={{ flex: 1 }} />
          {freeDepartments.length > 0 && (
            <select value="" disabled={busy} title={tr('usd.comp.addDeptHint')}
              onChange={e => { const d = e.target.value; if (d) setDraft(r => ({ ...r, departments: [...r.departments, d] })) }}
              style={{ ...selectStyle, width: 170 }}>
              <option value="">{tr('usd.comp.addDept')}</option>
              {freeDepartments.map(d => <option key={d} value={d}>{d}</option>)}
            </select>
          )}
          <Btn sm ghost disabled={busy || dirty || comp.proposed.length === 0} title={tr('usd.comp.addAllHint')}
            onClick={() => void run(() => api.addProposedUsdComponent(project, comp.name))}>
            <Plus size={11} strokeWidth={2} /> {tr('usd.comp.addAll')}
          </Btn>
        </div>

        {draft.departments.length === 0 && (
          <span className="lbl" style={{ fontSize: 10, color: 'var(--ink-4)' }}>{tr('usd.comp.noDept')}</span>
        )}
        {draft.departments.map(dept => {
          const files = draft.files.filter(f => f.department === dept)
          const proposed = comp.proposed.filter(p => p.department === dept && !draft.files.some(f => f.base === p.base))
          return (
            <div key={dept} className="card" style={{ padding: '8px 10px', display: 'flex', flexDirection: 'column', gap: 6 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--ink)' }}>{dept}</span>
                <span className="lbl" style={{ fontSize: 10, color: 'var(--ink-4)' }}>{tr('usd.comp.fileCount', { n: files.length })}</span>
                <div style={{ flex: 1 }} />
                <Btn sm ghost disabled={busy || files.length > 0} title={files.length > 0 ? tr('usd.comp.removeDeptHint') : tr('usd.lib.remove')}
                  onClick={() => setDraft(r => ({ ...r, departments: r.departments.filter(d => d !== dept) }))}>
                  <Trash2 size={10} strokeWidth={2} />
                </Btn>
              </div>

              {files.map(f => {
                const preview = rules.preview.includes(f.kind)
                const others = draft.files.filter(o => o.id !== f.id)
                const info = byId.get(f.id)
                const nonUsd = !['usd', 'usda', 'usdc', 'usdz'].includes(f.format)
                return (
                  <div key={f.id} style={{ display: 'flex', flexDirection: 'column', gap: 4, borderTop: '1px solid var(--rule)', paddingTop: 6 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <input type="checkbox" checked={f.active} disabled={busy || preview}
                        title={preview ? tr('usd.comp.previewOnly') : tr('usd.comp.activeHint')}
                        onChange={e => patch(f.id, { active: e.target.checked })} />
                      <span style={{ ...mono, color: 'var(--ink-2)', flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                        title={f.source === 'publish' ? f.base : f.path}>{f.label}</span>
                      <span className="lbl" style={{ fontSize: 9.5, color: nonUsd ? 'var(--warn)' : 'var(--ink-3)' }}>.{f.format}</span>
                      <select value={f.kind} disabled={busy} onChange={e => patch(f.id, { kind: e.target.value as UsdFileKind })}
                        style={{ ...selectStyle, width: 96 }}>
                        {rules.kinds.map(k => <option key={k} value={k}>{tr(`usd.kind.${k}`)}</option>)}
                      </select>
                      {f.source === 'publish'
                        ? <VersionSelect project={project} name={comp.name} file={f} disabled={busy} onChange={v => patch(f.id, { version: v })} />
                        : <span className="lbl" style={{ fontSize: 9.5, color: 'var(--ink-4)', width: 104 }}>{tr('usd.comp.manual')}</span>}
                      {info && info.found === false && (
                        <span className="lbl" style={{ fontSize: 9.5, color: 'var(--err)' }}>{tr('usd.comp.notFound')}</span>
                      )}
                      <Btn sm ghost disabled={busy} title={tr('usd.lib.remove')} onClick={() => removeFile(f.id)}>
                        <Trash2 size={10} strokeWidth={2} />
                      </Btn>
                    </div>
                    <IdPills label={tr('usd.comp.targets')} ids={f.targets} disabled={busy}
                      candidates={others.filter(o => (rules.targets[f.kind] ?? []).includes(o.kind))}
                      onToggle={id => toggleIn(f.id, 'targets', id)} />
                    <IdPills label={tr('usd.comp.proxyOf')} ids={f.proxy_of} disabled={busy}
                      candidates={others.filter(o => (rules.proxy[f.kind] ?? []).includes(o.kind))}
                      onToggle={id => toggleIn(f.id, 'proxy_of', id)} />
                    <IdPills label={tr('usd.comp.depends')} ids={f.depends} disabled={busy} candidates={others}
                      onToggle={id => toggleIn(f.id, 'depends', id)} />
                  </div>
                )
              })}

              {proposed.length > 0 && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap', borderTop: '1px solid var(--rule)', paddingTop: 6 }}>
                  <span className="cap" style={{ marginRight: 4 }}>{tr('usd.comp.proposed')}</span>
                  {proposed.map(p => (
                    <Pill key={p.base} style={{ cursor: 'pointer' }} onClick={() => addProposed(p)}>
                      <Plus size={9} strokeWidth={2} /> {p.base} {p.version} .{p.format}
                    </Pill>
                  ))}
                </div>
              )}
              <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <input value={manual[dept] ?? ''} placeholder={tr('usd.comp.manualPath')}
                  onChange={e => setManual(m => ({ ...m, [dept]: e.target.value }))}
                  onKeyDown={e => { if (e.key === 'Enter') addManual(dept) }}
                  style={{ ...selectStyle, flex: 1, fontFamily: 'var(--mono)', cursor: 'text' }} />
                <Btn sm ghost disabled={busy || !fmtOf(manual[dept] ?? '')}
                  title={fmtOf(manual[dept] ?? '') ? undefined : tr('usd.comp.needExt')} onClick={() => addManual(dept)}>
                  <Plus size={11} strokeWidth={2} /> {tr('usd.lib.add')}
                </Btn>
              </div>
            </div>
          )
        })}

        {dirty && (
          <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end', alignItems: 'center' }}>
            <span className="lbl" style={{ fontSize: 10, color: 'var(--ink-3)', flex: 1 }}>{tr('usd.comp.unsaved')}</span>
            <Btn sm ghost disabled={busy} onClick={() => setDraft(toRecipe(comp))}><X size={11} strokeWidth={2} /> {tr('usd.comp.cancel')}</Btn>
            <Btn sm primary disabled={busy} onClick={() => void run(() => api.saveUsdComponent(project, comp.name, draft))}>
              <Check size={11} strokeWidth={2} /> {tr('usd.comp.save')}
            </Btn>
          </div>
        )}
      </>)}

      {tab === 'versions' && <VersionsView versions={comp.versions} current={comp.version} />}
      {tab === 'composition' && <CompositionView project={project} file={comp.last} />}

      {tab === 'deps' && (<>
      <SecTitle>{tr('usd.deps.sources')}</SecTitle>
      <div className="card" style={{ padding: '6px 10px', display: 'flex', flexDirection: 'column', gap: 3 }}>
        {comp.files.map(f => (
          <div key={f.id} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 11, color: 'var(--ink-2)', width: 70 }}>{f.department}</span>
            <span style={{ ...mono, color: 'var(--ink-3)', flex: 1 }}>{f.source === 'publish' ? f.base : f.path}</span>
            <span style={{ ...mono, color: 'var(--ink-3)' }}>{f.composed_version ?? ''}</span>
          </div>
        ))}
        {comp.files.length === 0 && <span className="lbl" style={{ fontSize: 10, color: 'var(--ink-4)' }}>-</span>}
      </div>

      <SkeletonInfo project={project} name={comp.name} />

      <SecTitle>{tr('usd.lib.usedBy')}</SecTitle>
      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
        {comp.used_by.length === 0 && <span className="lbl" style={{ fontSize: 10, color: 'var(--ink-4)' }}>{tr('usd.lib.unused')}</span>}
        {comp.used_by.map(a => (
          <Pill key={a} onClick={() => onOpenAssembly(a)} style={{ cursor: 'pointer' }}>
            <Boxes size={10} strokeWidth={2} /> {a}
          </Pill>
        ))}
      </div>
      </>)}
    </div>
  )
}

function NewAssembly({ project, assemblies, onCreated }: {
  project: string; assemblies: UsdAssemblyInfo[]; onCreated: (name: string) => void
}) {
  const { t: tr } = useI18n()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [source, setSource] = useState('')
  const [busy, setBusy] = useState(false)
  const valid = /^[A-Za-z_][A-Za-z0-9_]*$/.test(name)

  async function create() {
    setBusy(true)
    try {
      const res = await api.createUsdAssembly(project, name, source || undefined)
      toast.success(tr('usd.lib.saved', { name, version: res.version ?? '' }))
      setOpen(false); setName(''); setSource('')
      onCreated(name)
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setBusy(false)
    }
  }

  if (!open) {
    return (
      <div style={{ padding: '0 14px 8px' }}>
        <Btn sm ghost onClick={() => setOpen(true)}><Plus size={11} strokeWidth={2} /> {tr('usd.lib.newAssembly')}</Btn>
      </div>
    )
  }
  return (
    <div className="card" style={{ margin: '0 14px 8px', padding: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
      <input autoFocus value={name} onChange={e => setName(e.target.value)} placeholder={tr('usd.lib.assemblyName')}
        onKeyDown={e => { if (e.key === 'Enter' && valid && !busy) void create() }}
        style={{ ...selectStyle, width: '100%', height: 26, boxSizing: 'border-box', fontFamily: 'var(--mono)' }} />
      <select value={source} onChange={e => setSource(e.target.value)} style={{ ...selectStyle, width: '100%', height: 26 }}>
        <option value="">{tr('usd.lib.blank')}</option>
        {assemblies.map(a => <option key={a.name} value={a.name}>{tr('usd.lib.copyOf', { name: a.name })}</option>)}
      </select>
      <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
        <Btn sm ghost disabled={busy} onClick={() => setOpen(false)}><X size={11} strokeWidth={2} /></Btn>
        <Btn sm primary disabled={busy || !valid} onClick={() => void create()}>
          <Check size={11} strokeWidth={2} /> {tr('usd.lib.create')}
        </Btn>
      </div>
    </div>
  )
}

function AssemblyDetail({ project, asm, components, onOpenComponent, onChanged }: {
  project: string; asm: UsdAssemblyInfo; components: UsdComponentInfo[]
  onOpenComponent: (name: string) => void; onChanged: () => void
}) {
  const { t: tr } = useI18n()
  const navigate = useNavigate()
  // prim of the row being relinked / renamed
  const [editing, setEditing] = useState<{ prim: string; mode: 'link' | 'rename' } | null>(null)
  const [target, setTarget] = useState('')
  const [version, setVersion] = useState('LAST')
  const [newName, setNewName] = useState('')
  const [addComp, setAddComp] = useState('')
  const [addCount, setAddCount] = useState(1)
  const [addVersion, setAddVersion] = useState('LAST')
  const [busy, setBusy] = useState(false)
  const [tab, setTab] = useState<DetailTab>('content')
  useEffect(() => { setEditing(null) }, [asm.file])

  const linkable = components.filter(c => c.versions.length > 0)
  const componentOf = (i: UsdAssemblyInfo['instances'][number]) =>
    components.find(c => c.name === i.component)
  const versionsOf = (name: string) => linkable.find(c => c.name === name)?.versions ?? []
  const instName = (prim: string) => prim.split('/').pop() ?? prim
  const instVersion = (i: UsdAssemblyInfo['instances'][number]) =>
    i.follows_last ? 'LAST' : (i.asset_path.match(/_(v\d+)\//)?.[1] ?? 'LAST')

  async function publishLayout(dcc: 'houdini' | 'maya') {
    setBusy(true)
    try {
      const res = await api.publishUsdLayout(project, asm.name, dcc)
      toast.success(tr('usd.lib.layoutPublished', {
        layout: res.layout_version, n: res.placements, name: asm.name, version: res.version ?? '' }))
      res.warnings.forEach(w => toast.warning(w))
      onChanged()
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setBusy(false)
    }
  }

  async function edit(ops: UsdAssemblyOp[]) {
    setBusy(true)
    try {
      const res = await api.editUsdAssembly(project, asm.name, ops)
      if (res.changed) toast.success(tr('usd.lib.saved', { name: asm.name, version: res.version ?? '' }))
      else toast.info(tr('usd.lib.noChange'))
      res.warnings.forEach(w => toast.warning(w))
      setEditing(null)
      onChanged()
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setBusy(false)
    }
  }

  function startLink(i: UsdAssemblyInfo['instances'][number]) {
    setEditing({ prim: i.prim, mode: 'link' })
    setTarget(i.component ?? linkable[0]?.name ?? '')
    setVersion(instVersion(i))
  }

  const freezeOps: UsdAssemblyOp[] = asm.instances
    .filter(i => i.follows_last && i.component)
    .map(i => ({ op: 'set_version', name: instName(i.prim),
                 version: components.find(c => c.name === i.component)?.version ?? 'LAST' }))

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxWidth: 820 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <Boxes size={15} strokeWidth={1.75} color="var(--ink-3)" />
        <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--ink)' }}>{asm.name}</span>
        {asm.version && <span style={{ ...mono, color: 'var(--ink-3)' }}>{asm.version}</span>}
        {asm.broken > 0 && (
          <span className="lbl" style={{ fontSize: 10, color: 'var(--err)' }}>{tr('usd.lib.brokenCount', { n: asm.broken })}</span>
        )}
        <div style={{ flex: 1 }} />
        <Btn sm ghost onClick={() => navigate('/projects', { state: { openPath: asm.file.replace(/[\\/][^\\/]+$/, '') } })}>
          <FolderOpen size={11} strokeWidth={2} /> {tr('usd.lib.openFolder')}
        </Btn>
        <Btn sm ghost onClick={() => copy(asm.file, tr('usd.lib.copied'))} title={asm.file}>
          <Copy size={11} strokeWidth={2} />
        </Btn>
      </div>
      {asm.legacy && (
        <span className="lbl" style={{ fontSize: 10, color: 'var(--warn)' }}>{tr('usd.lib.legacy')}</span>
      )}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
        <span className="lbl" style={{ fontSize: 10, color: 'var(--ink-4)' }} title={asm.layout ?? undefined}>
          {tr('usd.lib.layout')} : {asm.layout_version ?? (asm.layout ? asm.layout.split(/[\\/]/).pop() : tr('usd.lib.noLayout'))}
        </span>
        <div style={{ flex: 1 }} />
        <span className="cap" title={tr('usd.lib.layoutHelp')}>{tr('usd.lib.publishLayout')}</span>
        <Btn sm ghost disabled={busy || asm.instances.length === 0} title={tr('usd.lib.layoutHelp')}
          onClick={() => void publishLayout('houdini')}>
          <Upload size={11} strokeWidth={2} /> Houdini
        </Btn>
        <Btn sm ghost disabled={busy || asm.instances.length === 0} title={tr('usd.lib.layoutHelp')}
          onClick={() => void publishLayout('maya')}>
          <Upload size={11} strokeWidth={2} /> Maya
        </Btn>
      </div>

      <DetailTabs tab={tab} onTab={setTab} />

      {tab === 'content' && (<>
      <SecTitle>{tr('usd.lib.add')}</SecTitle>
      <div className="card" style={{ padding: '6px 10px', display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        <select value={addComp} onChange={e => { setAddComp(e.target.value); setAddVersion('LAST') }} style={{ ...selectStyle, width: 170 }}>
          <option value="">{tr('usd.lib.components')}</option>
          {linkable.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}
        </select>
        <span className="cap">{tr('usd.lib.count')}</span>
        <input type="number" min={1} max={500} value={addCount} onChange={e => setAddCount(Math.max(1, Number(e.target.value) || 1))}
          style={{ ...selectStyle, width: 56, fontFamily: 'var(--mono)' }} />
        <select value={addVersion} onChange={e => setAddVersion(e.target.value)} style={{ ...selectStyle, width: 100, fontFamily: 'var(--mono)' }}>
          <option value="LAST">{tr('usd.lib.followLast')}</option>
          {[...versionsOf(addComp)].reverse().map(v => <option key={v} value={v}>{v}</option>)}
        </select>
        <div style={{ flex: 1 }} />
        <Btn sm primary disabled={busy || !addComp}
          onClick={() => void edit([{ op: 'add', component: addComp, count: addCount, version: addVersion }])}>
          <Plus size={11} strokeWidth={2} /> {tr('usd.lib.add')}
        </Btn>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <SecTitle>{tr('usd.lib.instances')}</SecTitle>
        <div style={{ flex: 1 }} />
        <Btn sm ghost disabled={busy || asm.instances.length === 0}
          onClick={() => void edit([{ op: 'set_version', all: true, version: 'LAST' }])}>{tr('usd.lib.allLast')}</Btn>
        <Btn sm ghost disabled={busy || freezeOps.length === 0} onClick={() => void edit(freezeOps)}>
          <PinIcon size={10} strokeWidth={2} /> {tr('usd.lib.freezeAll')}
        </Btn>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {asm.instances.length === 0 && <span className="lbl" style={{ fontSize: 10, color: 'var(--ink-4)' }}>{tr('usd.lib.noInstance')}</span>}
        {asm.instances.map(i => {
          const name = instName(i.prim)
          const rowEdit = editing?.prim === i.prim ? editing.mode : null
          return (
          <div key={`${i.prim}|${i.asset_path}`} className="card" style={{
            padding: '6px 10px', display: 'flex', flexDirection: 'column', gap: 6,
            borderColor: i.broken ? 'var(--err)' : undefined,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ ...mono, color: 'var(--ink-2)', flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={i.asset_path}>
                {i.prim.split('/').slice(2).join('/')}
              </span>
              {i.component ? (
                <Pill onClick={() => onOpenComponent(i.component as string)} style={{ cursor: 'pointer' }}>
                  <Box size={10} strokeWidth={2} /> {i.component}
                </Pill>
              ) : (
                <span className="lbl" style={{ fontSize: 9.5, color: 'var(--ink-4)' }}>{tr('usd.lib.notComponent')}</span>
              )}
              <span className="lbl" style={{ fontSize: 9.5, color: 'var(--ink-3)', width: 40, textAlign: 'right' }}>
                {i.follows_last ? tr('usd.lib.followLast') : (i.asset_path.match(/_(v\d+)\//)?.[1] ?? tr('usd.lib.frozen'))}
              </span>
              {/* ADR 0023: each component file is a variant set on / off; an instance may override it. */}
              {(componentOf(i)?.files.length ?? 0) > 1 && componentOf(i)?.files.map(f => (
                <select key={f.id} value={i.variants?.[f.id] ?? ''} disabled={busy}
                  title={`${tr('usd.lib.variant')} ${f.label}`}
                  onChange={e => void edit([{ op: 'set_variant', name, department: f.id, variant: e.target.value }])}
                  style={{ ...selectStyle, width: 110, fontFamily: 'var(--mono)' }}>
                  <option value="">{f.label} ·</option>
                  <option value="on">{f.label} on</option>
                  <option value="off">{f.label} off</option>
                </select>
              ))}
              {i.broken && (
                <span className="lbl" style={{ fontSize: 9.5, color: 'var(--err)', display: 'flex', alignItems: 'center', gap: 4 }}>
                  <AlertTriangle size={10} strokeWidth={2} /> {tr('usd.lib.broken')}
                </span>
              )}
              {!rowEdit && (<>
                <Btn sm ghost disabled={busy || linkable.length === 0} onClick={() => startLink(i)} title={tr('usd.lib.changeLink')}>
                  <Pencil size={10} strokeWidth={2} />
                </Btn>
                <Btn sm ghost disabled={busy} title={tr('usd.lib.rename')}
                  onClick={() => { setEditing({ prim: i.prim, mode: 'rename' }); setNewName(name) }}>Aa</Btn>
                <Btn sm ghost disabled={busy || !i.component} title={tr('usd.lib.duplicate')}
                  onClick={() => void edit([{ op: 'duplicate', name }])}>
                  <CopyPlus size={10} strokeWidth={2} />
                </Btn>
                <Btn sm ghost disabled={busy} title={tr('usd.lib.remove')} onClick={() => void edit([{ op: 'remove', name }])}>
                  <Trash2 size={10} strokeWidth={2} />
                </Btn>
              </>)}
            </div>
            {rowEdit === 'link' && (
              <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', borderTop: '1px solid var(--rule)', paddingTop: 6 }}>
                <span className="cap">{tr('usd.lib.components')}</span>
                <select value={target} onChange={e => { setTarget(e.target.value); setVersion('LAST') }} style={{ ...selectStyle, width: 160 }}>
                  {linkable.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}
                </select>
                <span className="cap">{tr('usd.col.version')}</span>
                <select value={version} onChange={e => setVersion(e.target.value)} style={{ ...selectStyle, width: 110, fontFamily: 'var(--mono)' }}>
                  <option value="LAST">{tr('usd.lib.followLast')}</option>
                  {[...versionsOf(target)].reverse().map(v => <option key={v} value={v}>{v}</option>)}
                </select>
                <div style={{ flex: 1 }} />
                <Btn sm primary disabled={busy || !target}
                  onClick={() => void edit([{ op: 'relink', name, component: target, version }])}>
                  <Check size={11} strokeWidth={2} /> {tr('usd.lib.apply')}
                </Btn>
                <Btn sm ghost disabled={busy} onClick={() => setEditing(null)}><X size={11} strokeWidth={2} /></Btn>
              </div>
            )}
            {rowEdit === 'rename' && (
              <div style={{ display: 'flex', gap: 6, alignItems: 'center', borderTop: '1px solid var(--rule)', paddingTop: 6 }}>
                <input autoFocus value={newName} onChange={e => setNewName(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter' && newName && newName !== name) void edit([{ op: 'rename', name, new_name: newName }]) }}
                  style={{ ...selectStyle, flex: 1, fontFamily: 'var(--mono)' }} />
                <Btn sm primary disabled={busy || !/^[A-Za-z_][A-Za-z0-9_]*$/.test(newName) || newName === name}
                  onClick={() => void edit([{ op: 'rename', name, new_name: newName }])}>
                  <Check size={11} strokeWidth={2} /> {tr('usd.lib.apply')}
                </Btn>
                <Btn sm ghost disabled={busy} onClick={() => setEditing(null)}><X size={11} strokeWidth={2} /></Btn>
              </div>
            )}
          </div>
          )
        })}
      </div>
      </>)}

      {tab === 'versions' && <VersionsView versions={asm.versions} current={asm.version} />}
      {tab === 'composition' && <CompositionView project={project} file={asm.file} />}

      {tab === 'deps' && (<>
        <SecTitle>{tr('usd.deps.components')}</SecTitle>
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          {[...new Set(asm.instances.map(i => i.component).filter(Boolean))].map(c => (
            <Pill key={c as string} onClick={() => onOpenComponent(c as string)} style={{ cursor: 'pointer' }}>
              <Box size={10} strokeWidth={2} /> {c}
            </Pill>
          ))}
          {asm.instances.length === 0 && <span className="lbl" style={{ fontSize: 10, color: 'var(--ink-4)' }}>-</span>}
        </div>

        <SecTitle>{tr('usd.lib.layout')}</SecTitle>
        <span style={{ ...mono, color: 'var(--ink-3)' }} title={asm.layout ?? undefined}>
          {asm.layout ? asm.layout.split(/[\\/]/).pop() : tr('usd.lib.noLayout')}
        </span>
      </>)}
    </div>
  )
}

// ── detail views shared by assets and decors ─────────────────────────────────

function DetailTabs({ tab, onTab }: { tab: DetailTab; onTab: (t: DetailTab) => void }) {
  const { t: tr } = useI18n()
  const tabs: DetailTab[] = ['content', 'versions', 'composition', 'deps']
  return (
    <div style={{ display: 'flex', gap: 4, borderBottom: '1px solid var(--rule)', paddingBottom: 6 }}>
      {tabs.map(t => (
        <Pill key={t} active={tab === t} onClick={() => onTab(t)} style={{ cursor: 'pointer' }}>{tr(`usd.tab.${t}`)}</Pill>
      ))}
    </div>
  )
}

// Version history: newest first, the one LAST points at is marked.
function VersionsView({ versions, current }: { versions: string[]; current: string | null }) {
  const { t: tr } = useI18n()
  if (versions.length === 0) return <span className="lbl" style={{ fontSize: 10, color: 'var(--ink-4)' }}>-</span>
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      {[...versions].reverse().map(v => (
        <div key={v} className="card" style={{ padding: '5px 10px', display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ ...mono, color: v === current ? 'var(--accent-hi)' : 'var(--ink-2)' }}>{v}</span>
          {v === current && <span className="lbl" style={{ fontSize: 9.5, color: 'var(--accent-hi)' }}>{tr('usd.versions.current')}</span>}
        </div>
      ))}
    </div>
  )
}

// Crowd (A6, ADR 0022): the asset's skeleton signature, the assets on the same rig and
// the animation clips that fit it. One request per project, shared by every asset.
const crowdCache = new Map<string, Promise<UsdCrowdCompat>>()

function SkeletonInfo({ project, name }: { project: string; name: string }) {
  const { t: tr } = useI18n()
  const [compat, setCompat] = useState<UsdCrowdCompat | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    setCompat(null); setError('')
    let req = crowdCache.get(project)
    if (!req) {
      req = api.getUsdCrowdCompat(project)
      crowdCache.set(project, req)
      req.catch(() => crowdCache.delete(project))
      setTimeout(() => crowdCache.delete(project), 30000)
    }
    req.then(setCompat).catch(e => setError(errMsg(e)))
  }, [project, name])

  const info = compat?.assets[name]
  const clips = compat && info ? compat.clips.filter(c => info.clips.includes(c.base)) : []
  return (<>
    <SecTitle>{tr('usd.crowd.skeleton')}</SecTitle>
    <div className="card" style={{ padding: '6px 10px', display: 'flex', flexDirection: 'column', gap: 5 }}>
      {error && <span className="lbl" style={{ fontSize: 10, color: 'var(--err)' }}>{error}</span>}
      {!error && !compat && <span className="lbl" style={{ fontSize: 10, color: 'var(--ink-4)' }}>...</span>}
      {compat && !info && <span className="lbl" style={{ fontSize: 10, color: 'var(--ink-4)' }}>{tr('usd.crowd.noSkeleton')}</span>}
      {info && (<>
        <span style={{ ...mono, color: 'var(--ink-2)' }}>
          {tr('usd.crowd.signature')} {info.signature} · {info.joint_count} {tr('usd.crowd.joints')}
        </span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap' }}>
          <span className="cap" style={{ marginRight: 4 }}>{tr('usd.crowd.sameRig')}</span>
          {info.compatible.length === 0 && <span className="lbl" style={{ fontSize: 10, color: 'var(--ink-4)' }}>{tr('usd.crowd.none')}</span>}
          {info.compatible.map(a => <Pill key={a}>{a}</Pill>)}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap' }}>
          <span className="cap" style={{ marginRight: 4 }}>{tr('usd.crowd.clips')}</span>
          {clips.length === 0 && <span className="lbl" style={{ fontSize: 10, color: 'var(--ink-4)' }}>{tr('usd.crowd.none')}</span>}
          {clips.map(c => (
            <Pill key={c.base}>
              {c.asset} {c.clip}{c.range ? ` ${c.range[0]}-${c.range[1]}` : ''}
            </Pill>
          ))}
        </div>
      </>)}
    </div>
  </>)
}

// Composition of the published file, read by the backend with pxr (read only).
function CompositionView({ project, file }: { project: string; file: string | null }) {
  const { t: tr } = useI18n()
  const [comp, setComp] = useState<UsdComposition | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    setComp(null); setError('')
    if (!file) return
    api.getUsdComposition(project, file)
      .then(setComp)
      .catch(e => setError(errMsg(e)))
  }, [project, file])

  if (!file) return <span className="lbl" style={{ fontSize: 10, color: 'var(--ink-4)' }}>{tr('usd.comp.empty')}</span>
  if (error) return <span className="lbl" style={{ fontSize: 10, color: 'var(--err)' }}>{error}</span>
  if (!comp) return <span className="lbl" style={{ fontSize: 10, color: 'var(--ink-4)' }}>...</span>
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div className="card" style={{ padding: '6px 10px', display: 'flex', flexDirection: 'column', gap: 2 }}>
        {comp.tree ? <PrimRow node={comp.tree} depth={0} /> : <span className="lbl" style={{ fontSize: 10 }}>-</span>}
      </div>
      <SecTitle>{tr('usd.comp.layers')}</SecTitle>
      <div className="card" style={{ padding: '6px 10px', display: 'flex', flexDirection: 'column', gap: 2 }}>
        {comp.layers.map(l => (
          <span key={l.path} style={{ ...mono, color: l.root ? 'var(--ink-2)' : 'var(--ink-3)' }}>
            {l.root ? '* ' : '  '}{l.path}
          </span>
        ))}
      </div>
    </div>
  )
}

function PrimRow({ node, depth }: { node: UsdPrimNode; depth: number }) {
  const { t: tr } = useI18n()
  const vsets = Object.entries(node.variant_sets)
  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, paddingLeft: depth * 14 }}>
        <span style={{ ...mono, color: 'var(--ink)' }}>{node.name || '/'}</span>
        {node.type && <span className="lbl" style={{ fontSize: 9.5, color: 'var(--ink-3)' }}>{node.type}</span>}
        {node.kind && <Pill>{node.kind}</Pill>}
        {node.purpose && node.purpose !== 'default' && (
          <span className="lbl" style={{ fontSize: 9.5, color: 'var(--ink-4)' }}>{node.purpose}</span>
        )}
        {vsets.map(([name, v]) => (
          <span key={name} className="lbl" style={{ fontSize: 9.5, color: 'var(--accent-hi)' }}>
            {name} = {v.selection || '-'} ({v.variants.length})
          </span>
        ))}
        {node.arcs.map((a, i) => (
          <span key={i} className="lbl" title={a.asset} style={{ fontSize: 9.5, color: 'var(--ink-4)' }}>
            {a.arc} {a.asset.split('/').pop()}
          </span>
        ))}
        {node.instanceable && (
          <span className="lbl" style={{ fontSize: 9.5, color: 'var(--ink-4)' }}>{tr('usd.comp.instanced')}</span>
        )}
      </div>
      {node.children.map(c => <PrimRow key={c.path} node={c} depth={depth + 1} />)}
      {node.truncated && !node.instanceable && (
        <span className="lbl" style={{ fontSize: 9.5, color: 'var(--ink-4)', paddingLeft: (depth + 1) * 14 }}>
          {tr('usd.comp.more')}
        </span>
      )}
    </>
  )
}
