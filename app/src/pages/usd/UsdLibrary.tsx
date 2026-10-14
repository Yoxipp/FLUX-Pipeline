// UsdLibrary.tsx — the USD page content: everything already published in the project.
// Left: assets (components created by hand, ADR 0023, links in blocks ADR 0024) and decors
// (assemblies), with search, sort and filter by classification tokens (retake 03, lib/usdTokenSort).
// Right: one entity in four views, like a documented USD pipeline tool (AYON scene
// inventory / Solaris stage manager): Content (departments or instances, editable),
// Versions, Composition (what the file really gives) and Dependencies.
// Backend: GET /usd/library, /usd/composition, POST /usd/component/{create,save,refresh,add-proposed},
// /usd/assembly/{create,edit,layout/publish}.

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Box, Boxes, RefreshCw, Copy, AlertTriangle, Search, Pencil, Check, X, Trash2, Pin as PinIcon, FolderOpen, ClipboardList, Plus, CopyPlus, Upload } from 'lucide-react'
import { useLocation, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { Btn, SecTitle, Pill } from '../../components/shared/ui'
import { api } from '../../api/client'
import type {
  UsdAssemblyInfo, UsdAssemblyOp, UsdComponentBlock, UsdComponentFile, UsdComponentInfo, UsdComponentRecipe,
  UsdComponentResult, UsdComponentRules, UsdComposition, UsdCrowdCompat, UsdLibrary as Library, UsdLinkArc,
  UsdPrimNode, UsdProposedFile,
} from '../../api/client'
import { useI18n } from '../../i18n'
import { OpenInMenu, projectRelPath } from '../../components/shared/OpenInMenu'
import { ExpandPicker } from '../../components/shared/ExpandPicker'
import { useSessionState } from '../../hooks/useSessionState'
import { NO_TOKEN, SORT_NAME, sortAndFilter, tokenValue, tokenValues } from '../../lib/usdTokenSort'

type Tab = 'components' | 'assemblies'
type DetailTab = 'content' | 'versions' | 'composition' | 'deps'
type Selection = { tab: Tab; name: string } | null

const stateColor: Record<UsdComponentInfo['state'], string> = {
  ok: 'var(--ok)', stale: 'var(--warn)', empty: 'var(--ink-4)',
}

const mono: React.CSSProperties = { fontFamily: 'var(--mono)', fontSize: 11.5 }

export function UsdLibrary({ project, projects, onProject }: {
  project: string | null | undefined; projects: string[]; onProject: (name: string) => void
}) {
  const { t: tr } = useI18n()
  const [lib, setLib] = useState<Library | null>(null)
  const [loading, setLoading] = useState(false)
  const [tab, setTab] = useState<Tab>('components')
  const [query, setQuery] = useState('')
  // Sort key and token filter survive page changes for the session (like the Publisher).
  const [sortKey, setSortKey] = useSessionState<string>('usd.lib.sort', SORT_NAME)
  const [tokenFilter, setTokenFilter] = useSessionState<Record<string, string[]>>('usd.lib.tokenFilter', {})
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
  const tokenKeys = lib?.token_keys ?? []
  // A sort key gone from the project (token category removed) falls back to the name.
  const activeSort = sortKey === SORT_NAME || tokenKeys.includes(sortKey) ? sortKey : SORT_NAME
  const selected = useMemo(() => activeSort === SORT_NAME ? [] : (tokenFilter[activeSort] ?? []), [activeSort, tokenFilter])
  const components = useMemo(
    () => sortAndFilter((lib?.components ?? []).filter(c => !q || c.name.toLowerCase().includes(q)), activeSort, selected),
    [lib, q, activeSort, selected])
  const assemblies = useMemo(
    () => sortAndFilter((lib?.assemblies ?? []).filter(a => !q || a.name.toLowerCase().includes(q)), activeSort, selected),
    [lib, q, activeSort, selected])
  // Values offered as filter chips: those of the current tab, plus selected ones that
  // no longer exist (shown as obsolete so the artist can drop them).
  const tabEntries = tab === 'components' ? (lib?.components ?? []) : (lib?.assemblies ?? [])
  const presentValues = activeSort === SORT_NAME ? [] : tokenValues(tabEntries, activeSort)
  const obsoleteValues = lib ? selected.filter(v => !presentValues.includes(v)) : []
  function toggleValue(v: string) {
    setTokenFilter(f => {
      const cur = f[activeSort] ?? []
      return { ...f, [activeSort]: cur.includes(v) ? cur.filter(x => x !== v) : [...cur, v] }
    })
  }
  const groupLabel = (v: string) => v === NO_TOKEN ? tr('usd.lib.noToken') : v

  const selComponent = sel?.tab === 'components' ? lib?.components.find(c => c.name === sel.name) : undefined
  const selAssembly = sel?.tab === 'assemblies' ? lib?.assemblies.find(a => a.name === sel.name) : undefined

  useEffect(() => { setSel(null) }, [project])

  // Deep link (Production "USD assemble" task -> Ouvrir la page USD): select that
  // asset's component, or its assembly for a decor, once the library is loaded.
  const location = useLocation()
  const [pendingOpen, setPendingOpen] = useState<string | null>(null)
  useEffect(() => {
    const name = (location.state as { openUsd?: string } | null)?.openUsd
    if (name) {
      setPendingOpen(name)
      window.history.replaceState({}, '')
    }
  }, [location.state])
  useEffect(() => {
    if (!pendingOpen || !lib) return
    if (lib.components.some(c => c.name === pendingOpen)) goTo('components', pendingOpen)
    else if (lib.assemblies.some(a => a.name === pendingOpen)) goTo('assemblies', pendingOpen)
    else toast.info(`${pendingOpen} : pas encore de component, crée-le dans la liste`)
    setPendingOpen(null)
  }, [pendingOpen, lib])   // eslint-disable-line react-hooks/exhaustive-deps

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
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <div style={{ position: 'relative', flex: 1, minWidth: 0 }}>
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
            {tokenKeys.length > 0 && (
              <ExpandPicker title={tr('usd.lib.sortBy')} mono value={activeSort} onChange={setSortKey}
                options={[{ value: SORT_NAME, label: tr('usd.lib.sortName') },
                  ...tokenKeys.map(k => ({ value: k, label: k, title: `${tr('usd.lib.sortBy')} ${k}` }))]} />
            )}
          </div>
          {activeSort !== SORT_NAME && (presentValues.length > 1 || selected.length > 0) && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, alignItems: 'center' }}>
              {presentValues.map(v => (
                <Pill key={v} active={selected.includes(v)} onClick={() => toggleValue(v)}
                  style={{ cursor: 'pointer', fontFamily: v === NO_TOKEN ? undefined : 'var(--mono)' }}>
                  {groupLabel(v)} {tabEntries.filter(e => tokenValue(e, activeSort) === v).length}
                </Pill>
              ))}
              {obsoleteValues.map(v => (
                <span key={v} title={tr('usd.lib.obsoleteToken')} onClick={() => toggleValue(v)}
                  style={{ ...mono, cursor: 'pointer', color: 'var(--warn)', textDecoration: 'line-through', padding: '0 4px' }}>
                  {groupLabel(v)} <X size={9} strokeWidth={2} />
                </span>
              ))}
              {selected.length > 0 && (
                <Btn sm ghost onClick={() => setTokenFilter(f => ({ ...f, [activeSort]: [] }))}>{tr('usd.lib.clearFilter')}</Btn>
              )}
            </div>
          )}
        </div>

        {tab === 'components' && lib && (
          <NewComponent project={project} creatable={lib.creatable}
            onCreated={name => { load(); goTo('components', name) }} />
        )}
        {tab === 'assemblies' && lib && (
          <NewAssembly project={project} assemblies={lib.assemblies}
            onCreated={name => { load(); goTo('assemblies', name) }} />
        )}
        <div style={{ flex: 1, overflowY: 'auto', padding: '0 8px 12px', display: 'flex', flexDirection: 'column', gap: 2 }}>
          {tab === 'components' && components.map((c, i) => (
            <div key={c.name} style={{ display: 'contents' }}>
            {activeSort !== SORT_NAME && (i === 0 || tokenValue(components[i - 1], activeSort) !== tokenValue(c, activeSort)) && (
              <GroupHeader label={groupLabel(tokenValue(c, activeSort))} />
            )}
            <ListRow active={sel?.tab === 'components' && sel.name === c.name}
              onClick={() => setSel({ tab: 'components', name: c.name })}
              icon={<Box size={12} strokeWidth={1.75} />}
              title={c.name}
              meta={<>
                <span style={{ ...mono, color: 'var(--ink-3)' }}>{c.version ?? '-'}</span>
                <span style={{ width: 6, height: 6, borderRadius: 3, background: stateColor[c.state], flexShrink: 0 }} />
              </>}
              sub={`${c.blocks.map(b => b.name).join(' · ') || '-'}  ·  ${c.files.length} link${c.files.length > 1 ? 's' : ''}${c.used_by.length ? `  ·  ${c.used_by.length} asm` : ''}`}
            />
            </div>
          ))}
          {tab === 'assemblies' && assemblies.map((a, i) => (
            <div key={a.file} style={{ display: 'contents' }}>
            {activeSort !== SORT_NAME && (i === 0 || tokenValue(assemblies[i - 1], activeSort) !== tokenValue(a, activeSort)) && (
              <GroupHeader label={groupLabel(tokenValue(a, activeSort))} />
            )}
            <ListRow active={sel?.tab === 'assemblies' && sel.name === a.name}
              onClick={() => setSel({ tab: 'assemblies', name: a.name })}
              icon={<Boxes size={12} strokeWidth={1.75} />}
              title={a.name}
              meta={<>
                <span style={{ ...mono, color: 'var(--ink-3)' }}>{a.version ?? '-'}</span>
                {a.broken > 0 && <AlertTriangle size={11} strokeWidth={2} color="var(--err)" />}
              </>}
              sub={`${a.instances.length} ${tr('usd.lib.instances').toLowerCase()}`}
            />
            </div>
          ))}
          {tab === 'assemblies' && legacy.length > 0 && (
            <div style={{ marginTop: 10, padding: '8px 6px', borderTop: '1px solid var(--rule)' }}>
              <div className="lbl" style={{ fontSize: 11, color: 'var(--ink-3)', marginBottom: 4 }}>
                Anciens fichiers ({legacy.length}) : plus proposes a l'import
              </div>
              {legacy.map(f => (
                <div key={f.rel_path} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11.5 }}>
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
            <div className="lbl" style={{ padding: '8px 6px', fontSize: 11, color: 'var(--ink-4)', lineHeight: 1.5 }}>
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

function GroupHeader({ label }: { label: string }) {
  return (
    <div className="lbl" style={{ ...mono, fontSize: 11, color: 'var(--ink-4)', padding: '8px 6px 2px', letterSpacing: '.04em' }}>
      {label}
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
      <span className="lbl" style={{ fontSize: 11, color: 'var(--ink-4)', paddingLeft: 18 }}>{sub}</span>
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

// ── component (ADR 0023 + 0024): created by hand, links grouped in blocks ────

const ID_RE = /^[A-Za-z_][A-Za-z0-9_]*$/

function toRecipe(comp: UsdComponentInfo): UsdComponentRecipe {
  return {
    blocks: comp.blocks.map(b => ({ ...b })),
    departments: [],   // derived from the links by the backend
    // A proxy of its whole block goes back with no proxy_of (the backend fills it), so a
    // link added to the block later is covered too; a single pick stays explicit.
    files: comp.files.map(({ resolved_version: _r, composed_version: _c, found: _f, ...f }) =>
      ({ ...f, proxy_of: f.proxy && f.proxy_of.length > 1 ? [] : f.proxy_of })),
  }
}

// Same rule as component_recipe.default_targets: the geometries / grooms whose name
// (publish instance, else label without its task prefix) matches, else all of them.
function nameKey(f: { source?: string; instance?: string; variante?: string; label?: string; department?: string }): string {
  if (f.source === 'publish' && f.instance) return `${f.instance}${f.variante ? `_${f.variante}` : ''}`.toLowerCase()
  let key = f.label ?? ''
  for (const p of [f.department ?? '', 'GEO', 'GROOM', 'SHADING', 'RIG', 'ANIM', 'LOOKDEV', 'LOOK', 'SHADER']) {
    if (p && key.toUpperCase().startsWith(`${p.toUpperCase()}_`)) { key = key.slice(p.length + 1); break }
  }
  return key.toLowerCase()
}

function defaultTargets(files: UsdComponentFile[], key: string): string[] {
  const surfaces = files.filter(f => f.kind === 'geometry' || f.kind === 'groom')
  const same = surfaces.filter(f => key && nameKey(f) === key).map(f => f.id)
  return same.length ? same : surfaces.map(f => f.id)
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

const cleanId = (s: string) => s.replace(/[^A-Za-z0-9_]/g, '_')

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

// New component: the asset only. Blocks model / look / rig come empty (ADR 0024).
function NewComponent({ project, creatable, onCreated }: {
  project: string; creatable: string[]; onCreated: (name: string) => void
}) {
  const { t: tr } = useI18n()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)

  async function create() {
    setBusy(true)
    try {
      const res = await api.createUsdComponent(project, name)
      toast.success(tr('usd.lib.saved', { name, version: res.version ?? '' }))
      setOpen(false); setName('')
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
    <div style={{ margin: '0 14px 8px', display: 'flex', gap: 6 }}>
      <select autoFocus value={name} onChange={e => setName(e.target.value)} style={{ ...selectStyle, flex: 1, height: 26 }}>
        <option value="">{tr('usd.comp.pickAsset')}</option>
        {creatable.map(n => <option key={n} value={n}>{n}</option>)}
      </select>
      <Btn sm primary disabled={busy || !name} onClick={() => void create()}><Check size={11} strokeWidth={2} /></Btn>
      <Btn sm ghost disabled={busy} onClick={() => setOpen(false)}><X size={11} strokeWidth={2} /></Btn>
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
      style={{ ...selectStyle, width: 70, fontFamily: 'var(--mono)' }}>
      <option value="latest">{tr('usd.lib.followLast')}</option>
      {!versions.includes(value) && value !== 'latest' && <option value={value}>{value}</option>}
      {versions.map(v => <option key={v} value={v}>{v}</option>)}
    </select>
  )
}

// Small labelled checkbox of a link row.
function Check2({ label, checked, disabled, title, onChange }: {
  label: string; checked: boolean; disabled?: boolean; title?: string; onChange: (on: boolean) => void
}) {
  return (
    <label title={title} style={{
      display: 'flex', alignItems: 'center', gap: 4, fontSize: 11.5,
      color: disabled ? 'var(--ink-4)' : 'var(--ink-3)', cursor: disabled ? 'default' : 'pointer',
    }}>
      <input type="checkbox" checked={checked} disabled={disabled} onChange={e => onChange(e.target.checked)} />
      {label}
    </label>
  )
}

function LinkRow({ project, comp, link, files, rules, busy, onPatch, onRemove, onToggleTarget }: {
  project: string; comp: UsdComponentInfo; link: UsdComponentFile; files: UsdComponentFile[]
  rules: UsdComponentRules; busy: boolean
  onPatch: (p: Partial<UsdComponentFile>) => void; onRemove: () => void; onToggleTarget: (id: string) => void
}) {
  const { t: tr } = useI18n()
  const info = comp.files.find(f => f.id === link.id)
  const sublayer = link.arc === 'sublayer'
  // The name field stays open while it is being retyped (an empty name = no variant).
  const [variantOn, setVariantOn] = useState(!!link.variant)
  const showVariant = variantOn || !!link.variant
  const canProxy = Object.keys(rules.proxy).includes(link.kind)
  const needsTarget = link.kind === 'shader' || link.kind === 'animation'
  // Files this link may be the proxy of: any geometry / groom of the component (2026-09-26).
  const proxyOf = files.filter(o => o.id !== link.id && !o.proxy && (rules.proxy[link.kind] ?? []).includes(o.kind))
  const targets = files.filter(o => o.id !== link.id && (rules.targets[link.kind] ?? []).includes(o.kind))
  const nonUsd = !['usd', 'usda', 'usdc', 'usdz'].includes(link.format)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 5, borderTop: '1px solid var(--rule)', paddingTop: 6 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        {!sublayer && !link.variant && (
          <input type="checkbox" checked={link.active} disabled={busy || rules.preview.includes(link.kind)}
            title={tr('usd.comp.activeHint')} onChange={e => onPatch({ active: e.target.checked })} />
        )}
        <span style={{ ...mono, color: 'var(--ink-2)', flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
          title={link.source === 'publish' ? link.base : link.path}>
          {link.label}
          <span style={{ color: nonUsd ? 'var(--warn)' : 'var(--ink-4)' }}> .{link.format}</span>
        </span>
        {info && info.found === false && (
          <span className="lbl" style={{ fontSize: 11, color: 'var(--err)' }}>{tr('usd.comp.notFound')}</span>
        )}
        <span className="lbl" style={{ fontSize: 11, color: 'var(--ink-3)' }}>{link.department}</span>
        {link.source === 'publish'
          ? <VersionSelect project={project} name={comp.name} file={link} disabled={busy} onChange={v => onPatch({ version: v })} />
          : <span className="lbl" style={{ fontSize: 11, color: 'var(--ink-4)', width: 70 }}>{tr('usd.comp.manual')}</span>}
        <Btn sm ghost disabled={busy} title={tr('usd.lib.remove')} onClick={onRemove}>
          <Trash2 size={10} strokeWidth={2} />
        </Btn>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', paddingLeft: 22 }}>
        {sublayer && (
          // ADR 0031: the arc is set by FLUX; an older sublayer link stays until switched back.
          <span title={tr('usd.comp.legacySublayer')}>
            <Pill active style={{ cursor: busy ? 'default' : 'pointer' }}
              onClick={() => { if (!busy) onPatch({ arc: 'reference' as UsdLinkArc }) }}>
              {tr('usd.comp.legacySublayerShort')}
            </Pill>
          </span>
        )}
        <Check2 label={tr('usd.lib.variant')} checked={showVariant} disabled={busy || sublayer}
          onChange={on => { setVariantOn(on); onPatch({ variant: on ? 'default' : '' }) }} />
        {showVariant && (
          <input value={link.variant} disabled={busy} placeholder={tr('usd.comp.variantName')}
            onChange={e => onPatch({ variant: cleanId(e.target.value) })}
            style={{ ...selectStyle, width: 110, fontFamily: 'var(--mono)', cursor: 'text',
                     borderColor: ID_RE.test(link.variant) ? undefined : 'var(--err)' }} />
        )}
        <Check2 label="Proxy" checked={!!link.proxy} disabled={busy || sublayer || !canProxy}
          title={canProxy ? tr('usd.comp.proxyHint') : tr('usd.comp.proxyKinds')}
          onChange={on => onPatch({ proxy: on, proxy_of: [] })} />
        {link.proxy && proxyOf.length > 0 && (
          // Which file of the component this link is the proxy of (default: its block).
          <select value={link.proxy_of.length === 1 ? link.proxy_of[0] : ''} disabled={busy}
            title={tr('usd.comp.proxyOfHint')}
            onChange={e => onPatch({ proxy_of: e.target.value ? [e.target.value] : [] })}
            style={{ ...selectStyle, width: 150 }}>
            <option value="">{tr('usd.comp.proxyOfBlock')}</option>
            {proxyOf.map(o => <option key={o.id} value={o.id}>{o.label}</option>)}
          </select>
        )}
        {needsTarget && targets.length > 0 && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 3, flexWrap: 'wrap' }}>
            <span className="cap">{tr('usd.comp.targets')}</span>
            {targets.map(c => (
              <Pill key={c.id} active={link.targets.includes(c.id)} style={{ cursor: busy ? 'default' : 'pointer' }}
                onClick={() => { if (!busy) onToggleTarget(c.id) }}>{c.label}</Pill>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// Block a task's links go in (GEO -> model, SHADING -> look), same rule as the backend.
function blockOfTask(rules: UsdComponentRules, dept: string): string {
  return rules?.block_of_task?.[dept.toUpperCase()] ?? dept.toLowerCase()
}

// Task of a block (model -> GEO), "" when the block is not a task's own.
function taskOfBlock(rules: UsdComponentRules, departments: string[], block: string): string {
  const b = block.toLowerCase()
  return departments.find(d => blockOfTask(rules, d).toLowerCase() === b || d.toLowerCase() === b) ?? ''
}

// "New link": pick a task (the block's own by default), then one of its publishes or
// any file of the project.
function NewLink({ comp, departments, taken, busy, onAdd, defaultDept = '' }: {
  comp: UsdComponentInfo; departments: string[]; taken: Set<string>; busy: boolean
  onAdd: (dept: string, what: UsdProposedFile | string) => void
  defaultDept?: string
}) {
  const { t: tr } = useI18n()
  const [open, setOpen] = useState(false)
  const [dept, setDept] = useState(defaultDept)
  const [pick, setPick] = useState('')
  const [path, setPath] = useState('')
  // USD publishes by base, other formats (abc, fbx...) by the path of their LAST.
  const publishes = comp.proposed.filter(p => p.department === dept && !taken.has(p.path ?? p.base))
  const keyOf = (p: UsdProposedFile) => p.path ?? p.base
  const manual = pick === '__manual__'
  const ok = !!dept && (manual ? !!fmtOf(path) : !!pick)

  function reset() { setOpen(false); setDept(defaultDept); setPick(''); setPath('') }
  function add() {
    if (!ok) return
    onAdd(dept, manual ? path.trim() : publishes.find(p => keyOf(p) === pick) as UsdProposedFile)
    reset()
  }

  if (!open) {
    return (
      <div>
        <Btn sm ghost disabled={busy} onClick={() => { setDept(defaultDept); setOpen(true) }}><Plus size={11} strokeWidth={2} /> New link</Btn>
      </div>
    )
  }
  return (
    <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', borderTop: '1px solid var(--rule)', paddingTop: 6 }}>
      <select autoFocus value={dept} onChange={e => { setDept(e.target.value); setPick('') }} style={{ ...selectStyle, width: 110 }}>
        <option value="">{tr('usd.col.task')}</option>
        {departments.map(d => <option key={d} value={d}>{d}</option>)}
      </select>
      <select value={pick} disabled={!dept} onChange={e => setPick(e.target.value)} style={{ ...selectStyle, flex: 1, minWidth: 160, fontFamily: 'var(--mono)' }}>
        <option value="">{dept && publishes.length === 0 ? tr('usd.comp.noPublish') : tr('usd.comp.pickFile')}</option>
        {publishes.map(p => <option key={keyOf(p)} value={keyOf(p)}>{p.base} {p.version} .{p.format}</option>)}
        <option value="__manual__">{tr('usd.comp.otherFile')}</option>
      </select>
      {manual && (
        <input autoFocus value={path} placeholder={tr('usd.comp.manualPath')} onChange={e => setPath(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') add() }}
          title={fmtOf(path) ? undefined : tr('usd.comp.needExt')}
          style={{ ...selectStyle, flex: 2, minWidth: 200, fontFamily: 'var(--mono)', cursor: 'text' }} />
      )}
      <Btn sm primary disabled={busy || !ok} onClick={add}><Check size={11} strokeWidth={2} /></Btn>
      <Btn sm ghost onClick={reset}><X size={11} strokeWidth={2} /></Btn>
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
  const [newBlock, setNewBlock] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { setDraft(toRecipe(comp)); setNewBlock(null) }, [comp])
  const dirty = JSON.stringify(draft) !== JSON.stringify(toRecipe(comp))
  const assetDir = comp.dir.replace(/[\\/]usd[\\/]?$/i, '')
  const invalid = draft.files.some(f => f.variant && !ID_RE.test(f.variant))

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
  const toggleTarget = (id: string, other: string) =>
    setDraft(d => ({ ...d, files: d.files.map(f => f.id !== id ? f : {
      ...f, targets: f.targets.includes(other) ? f.targets.filter(x => x !== other) : [...f.targets, other] }) }))
  const removeFiles = (drop: (f: UsdComponentFile) => boolean) => setDraft(d => {
    const gone = new Set(d.files.filter(drop).map(f => f.id))
    return { ...d, files: d.files.filter(f => !gone.has(f.id)).map(f => ({
      ...f, targets: f.targets.filter(x => !gone.has(x)), proxy_of: f.proxy_of.filter(x => !gone.has(x)),
      depends: f.depends.filter(x => !gone.has(x)) })) }
  })
  const setBlock = (name: string, p: Partial<UsdComponentBlock>) =>
    setDraft(d => ({ ...d, blocks: d.blocks.map(b => b.name === name ? { ...b, ...p } : b) }))
  const removeBlock = (name: string) => {
    removeFiles(f => f.block === name)
    setDraft(d => ({ ...d, blocks: d.blocks.filter(b => b.name !== name) }))
  }
  const blockName = cleanId((newBlock ?? '').trim())
  const blockOk = ID_RE.test(blockName) && !draft.blocks.some(b => b.name.toLowerCase() === blockName.toLowerCase())
  function addBlock() {
    if (!blockOk) return
    setDraft(d => ({ ...d, blocks: [...d.blocks, { name: blockName, variant: '' }] }))
    setNewBlock(null)
  }

  function addLink(block: string, dept: string, what: UsdProposedFile | string) {
    const taken = new Set([...draft.files.map(f => f.id), ...draft.blocks.map(b => b.name)])
    const kind = typeof what === 'string' ? (rules.default_kind[dept] ?? 'other') : what.kind
    // A shader targets the geometry of its name, else all of them (editable), like "add all".
    const key = typeof what === 'string'
      ? nameKey({ label: what.replace(/\\/g, '/').split('/').pop()?.replace(/\.[^.]+$/, '') ?? '', department: dept })
      : nameKey({ source: 'publish', instance: what.instance, variante: what.variante })
    const targets = kind === 'shader' ? defaultTargets(draft.files, key) : []
    const common = {
      block, department: dept, kind, arc: 'reference' as UsdLinkArc, variant: '', proxy: false,
      targets, proxy_of: [], depends: [], active: !rules.preview.includes(kind),
    }
    if (typeof what === 'string') {
      const stem = what.replace(/\\/g, '/').split('/').pop()?.replace(/\.[^.]+$/, '') ?? 'file'
      setDraft(d => ({ ...d, files: [...d.files, {
        ...common, id: makeId(stem, taken), label: stem, format: fmtOf(what), source: 'manual', path: what }] }))
    } else if (what.path) {
      // A non-USD publish (abc, fbx...): linked as a file, its LAST follows new publishes.
      const id = makeId(`${dept.toLowerCase()}_${what.instance}${what.variante ? `_${what.variante}` : ''}_${what.format}`, taken)
      const filePath = what.path
      setDraft(d => ({ ...d, files: [...d.files, {
        ...common, id, label: what.base, format: what.format, source: 'manual', path: filePath }] }))
    } else {
      const id = makeId(`${dept.toLowerCase()}_${what.instance}${what.variante ? `_${what.variante}` : ''}`, taken)
      setDraft(d => ({ ...d, files: [...d.files, {
        ...common, id, label: what.base, format: what.format, source: 'publish',
        base: what.base, instance: what.instance, variante: what.variante, version: 'latest' }] }))
    }
  }

  const usedBases = new Set(draft.files.flatMap(f => [f.base ?? '', f.path ?? '']).filter(Boolean))
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxWidth: 900 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <Box size={15} strokeWidth={1.75} color="var(--ink-3)" />
        <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--ink)' }}>{comp.name}</span>
        {comp.version && <span style={{ ...mono, color: 'var(--ink-3)' }}>{comp.version}</span>}
        <span className="lbl" style={{ fontSize: 11, color: stateColor[comp.state] }}>{tr(`usd.lib.state.${comp.state}`)}</span>
        <div style={{ flex: 1 }} />
        <Btn sm ghost onClick={() => navigate('/projects', { state: { openPath: assetDir } })} title={assetDir}>
          <FolderOpen size={11} strokeWidth={2} /> {tr('usd.lib.openFolder')}
        </Btn>
        {comp.class && (
          <Btn sm ghost onClick={() => navigate('/production', {
            // The asset's "USD assemble" task (2026-09-26), not its first department.
            state: { openFavorite: { project, class: comp.class, name: comp.name, task: 'USD' } },
          })}>
            <ClipboardList size={11} strokeWidth={2} /> {tr('usd.lib.openProduction')}
          </Btn>
        )}
        {comp.last && <OpenInMenu project={project} relPath={projectRelPath(project, comp.last)} />}
        {comp.last && (
          <Btn sm ghost onClick={() => copy(comp.last as string, tr('usd.lib.copied'))} title={comp.last}>
            <Copy size={11} strokeWidth={2} />
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

        {draft.blocks.map(block => {
          const links = draft.files.filter(f => f.block === block.name)
          const variants = [...new Set(links.map(f => f.variant).filter(Boolean))] as string[]
          return (
            <div key={block.name} className="card" style={{ padding: '8px 10px', display: 'flex', flexDirection: 'column', gap: 6 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--ink)' }}>{block.name}</span>
                {variants.length > 0 && (
                  <select value={variants.includes(block.variant) ? block.variant : variants[0]} disabled={busy}
                    title={tr('usd.comp.defaultVariant')}
                    onChange={e => setBlock(block.name, { variant: e.target.value })}
                    style={{ ...selectStyle, width: 120, fontFamily: 'var(--mono)' }}>
                    {variants.map(v => <option key={v} value={v}>{v}</option>)}
                  </select>
                )}
                <div style={{ flex: 1 }} />
                <Check2 label={tr('usd.comp.deferred')} checked={!!block.deferred} disabled={busy}
                  onChange={on => setBlock(block.name, { deferred: on })} />
                <Btn sm ghost disabled={busy} title={tr('usd.comp.removeBlock')} onClick={() => removeBlock(block.name)}>
                  <Trash2 size={10} strokeWidth={2} />
                </Btn>
              </div>
              {links.map(f => (
                <LinkRow key={f.id} project={project} comp={comp} link={f} files={draft.files} rules={rules} busy={busy}
                  onPatch={p => patch(f.id, p)} onRemove={() => removeFiles(x => x.id === f.id)}
                  onToggleTarget={id => toggleTarget(f.id, id)} />
              ))}
              <NewLink comp={comp} departments={departments} taken={usedBases} busy={busy}
                defaultDept={taskOfBlock(rules, departments, block.name)}
                onAdd={(dept, what) => addLink(block.name, dept, what)} />
            </div>
          )
        })}

        {newBlock === null ? (
          <div>
            <Btn sm ghost disabled={busy} onClick={() => setNewBlock('')}><Plus size={11} strokeWidth={2} /> {tr('usd.comp.addBlock')}</Btn>
          </div>
        ) : (
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
            <input autoFocus value={newBlock} placeholder={tr('usd.comp.blockName')}
              onChange={e => setNewBlock(cleanId(e.target.value))}
              onKeyDown={e => { if (e.key === 'Enter') addBlock(); if (e.key === 'Escape') setNewBlock(null) }}
              style={{ ...selectStyle, width: 180, fontFamily: 'var(--mono)', cursor: 'text' }} />
            <Btn sm primary disabled={!blockOk} onClick={addBlock}><Check size={11} strokeWidth={2} /></Btn>
            <Btn sm ghost onClick={() => setNewBlock(null)}><X size={11} strokeWidth={2} /></Btn>
            {/* The project's tasks that have no block yet: one click names the block. */}
            {departments
              .filter(d => !draft.blocks.some(b => b.name.toLowerCase() === blockOfTask(rules, d).toLowerCase()))
              .map(d => (
                <Pill key={d} style={{ cursor: 'pointer' }}>
                  <span title={`Block ${blockOfTask(rules, d)} pour la task ${d}`}
                    onClick={() => {
                      const name = cleanId(blockOfTask(rules, d))
                      setDraft(dr => ({ ...dr, blocks: [...dr.blocks, { name, variant: '' }] }))
                      setNewBlock(null)
                    }}>+ {d}</span>
                </Pill>
              ))}
          </div>
        )}

        {dirty && (
          <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end', alignItems: 'center' }}>
            <div style={{ flex: 1 }} />
            <Btn sm ghost disabled={busy} onClick={() => setDraft(toRecipe(comp))}><X size={11} strokeWidth={2} /> {tr('usd.comp.cancel')}</Btn>
            <Btn sm primary disabled={busy || invalid} onClick={() => void run(() => api.saveUsdComponent(project, comp.name, draft))}>
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
        {comp.files.length === 0 && <span className="lbl" style={{ fontSize: 11, color: 'var(--ink-4)' }}>-</span>}
      </div>

      <SkeletonInfo project={project} name={comp.name} />

      <SecTitle>{tr('usd.lib.usedBy')}</SecTitle>
      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
        {comp.used_by.length === 0 && <span className="lbl" style={{ fontSize: 11, color: 'var(--ink-4)' }}>{tr('usd.lib.unused')}</span>}
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
  // Nothing to pick when the component has a single on / off link.
  const variantSetsOf = (i: UsdAssemblyInfo['instances'][number]) => {
    const sets = Object.entries(componentOf(i)?.variant_sets ?? {})
    const choices = sets.some(([, v]) => v.join() !== 'off,on')
    return sets.length > 1 || choices ? sets : []
  }
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
          <span className="lbl" style={{ fontSize: 11, color: 'var(--err)' }}>{tr('usd.lib.brokenCount', { n: asm.broken })}</span>
        )}
        <div style={{ flex: 1 }} />
        <Btn sm ghost onClick={() => navigate('/projects', { state: { openPath: asm.file.replace(/[\\/][^\\/]+$/, '') } })}>
          <FolderOpen size={11} strokeWidth={2} /> {tr('usd.lib.openFolder')}
        </Btn>
        {asm.class && (
          <Btn sm ghost onClick={() => navigate('/production', {
            state: { openFavorite: { project, class: asm.class, name: asm.name, task: 'USD' } },
          })}>
            <ClipboardList size={11} strokeWidth={2} /> {tr('usd.lib.openProduction')}
          </Btn>
        )}
        <OpenInMenu project={project} relPath={projectRelPath(project, asm.file)} />
        <Btn sm ghost onClick={() => copy(asm.file, tr('usd.lib.copied'))} title={asm.file}>
          <Copy size={11} strokeWidth={2} />
        </Btn>
      </div>
      {asm.legacy && (
        <span className="lbl" style={{ fontSize: 11, color: 'var(--warn)' }}>{tr('usd.lib.legacy')}</span>
      )}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
        <span className="lbl" style={{ fontSize: 11, color: 'var(--ink-4)' }} title={asm.layout ?? undefined}>
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
        {asm.instances.length === 0 && <span className="lbl" style={{ fontSize: 11, color: 'var(--ink-4)' }}>{tr('usd.lib.noInstance')}</span>}
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
                <span className="lbl" style={{ fontSize: 11, color: 'var(--ink-4)' }}>{tr('usd.lib.notComponent')}</span>
              )}
              <span className="lbl" style={{ fontSize: 11, color: 'var(--ink-3)', width: 40, textAlign: 'right' }}>
                {i.follows_last ? tr('usd.lib.followLast') : (i.asset_path.match(/_(v\d+)\//)?.[1] ?? tr('usd.lib.frozen'))}
              </span>
              {/* ADR 0023/0024: a variant set per toggled link (on / off) or per block (its variants);
                  an instance may override the component default. */}
              {variantSetsOf(i).map(([set, variants]) => {
                const label = componentOf(i)?.files.find(f => f.id === set)?.label ?? set
                return (
                  <select key={set} value={i.variants?.[set] ?? ''} disabled={busy}
                    title={`${tr('usd.lib.variant')} ${label}`}
                    onChange={e => void edit([{ op: 'set_variant', name, department: set, variant: e.target.value }])}
                    style={{ ...selectStyle, width: 110, fontFamily: 'var(--mono)' }}>
                    <option value="">{label} ·</option>
                    {variants.map(v => <option key={v} value={v}>{label} {v}</option>)}
                  </select>
                )
              })}
              {i.broken && (
                <span className="lbl" style={{ fontSize: 11, color: 'var(--err)', display: 'flex', alignItems: 'center', gap: 4 }}>
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
          {asm.instances.length === 0 && <span className="lbl" style={{ fontSize: 11, color: 'var(--ink-4)' }}>-</span>}
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
  if (versions.length === 0) return <span className="lbl" style={{ fontSize: 11, color: 'var(--ink-4)' }}>-</span>
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      {[...versions].reverse().map(v => (
        <div key={v} className="card" style={{ padding: '5px 10px', display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ ...mono, color: v === current ? 'var(--accent-hi)' : 'var(--ink-2)' }}>{v}</span>
          {v === current && <span className="lbl" style={{ fontSize: 11, color: 'var(--accent-hi)' }}>{tr('usd.versions.current')}</span>}
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
      {error && <span className="lbl" style={{ fontSize: 11, color: 'var(--err)' }}>{error}</span>}
      {!error && !compat && <span className="lbl" style={{ fontSize: 11, color: 'var(--ink-4)' }}>...</span>}
      {compat && !info && <span className="lbl" style={{ fontSize: 11, color: 'var(--ink-4)' }}>{tr('usd.crowd.noSkeleton')}</span>}
      {info && (<>
        <span style={{ ...mono, color: 'var(--ink-2)' }}>
          {tr('usd.crowd.signature')} {info.signature} · {info.joint_count} {tr('usd.crowd.joints')}
        </span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap' }}>
          <span className="cap" style={{ marginRight: 4 }}>{tr('usd.crowd.sameRig')}</span>
          {info.compatible.length === 0 && <span className="lbl" style={{ fontSize: 11, color: 'var(--ink-4)' }}>{tr('usd.crowd.none')}</span>}
          {info.compatible.map(a => <Pill key={a}>{a}</Pill>)}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap' }}>
          <span className="cap" style={{ marginRight: 4 }}>{tr('usd.crowd.clips')}</span>
          {clips.length === 0 && <span className="lbl" style={{ fontSize: 11, color: 'var(--ink-4)' }}>{tr('usd.crowd.none')}</span>}
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

  if (!file) return <span className="lbl" style={{ fontSize: 11, color: 'var(--ink-4)' }}>{tr('usd.comp.empty')}</span>
  if (error) return <span className="lbl" style={{ fontSize: 11, color: 'var(--err)' }}>{error}</span>
  if (!comp) return <span className="lbl" style={{ fontSize: 11, color: 'var(--ink-4)' }}>...</span>
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div className="card" style={{ padding: '6px 10px', display: 'flex', flexDirection: 'column', gap: 2 }}>
        {comp.tree ? <PrimRow node={comp.tree} depth={0} /> : <span className="lbl" style={{ fontSize: 11 }}>-</span>}
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
        {node.type && <span className="lbl" style={{ fontSize: 11, color: 'var(--ink-3)' }}>{node.type}</span>}
        {node.kind && <Pill>{node.kind}</Pill>}
        {node.purpose && node.purpose !== 'default' && (
          <span className="lbl" style={{ fontSize: 11, color: 'var(--ink-4)' }}>{node.purpose}</span>
        )}
        {vsets.map(([name, v]) => (
          <span key={name} className="lbl" style={{ fontSize: 11, color: 'var(--accent-hi)' }}>
            {name} = {v.selection || '-'} ({v.variants.length})
          </span>
        ))}
        {node.arcs.map((a, i) => (
          <span key={i} className="lbl" title={a.asset} style={{ fontSize: 11, color: 'var(--ink-4)' }}>
            {a.arc} {a.asset.split('/').pop()}
          </span>
        ))}
        {node.instanceable && (
          <span className="lbl" style={{ fontSize: 11, color: 'var(--ink-4)' }}>{tr('usd.comp.instanced')}</span>
        )}
      </div>
      {node.children.map(c => <PrimRow key={c.path} node={c} depth={depth + 1} />)}
      {node.truncated && !node.instanceable && (
        <span className="lbl" style={{ fontSize: 11, color: 'var(--ink-4)', paddingLeft: (depth + 1) * 14 }}>
          {tr('usd.comp.more')}
        </span>
      )}
    </>
  )
}
