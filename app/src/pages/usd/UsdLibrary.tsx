// UsdLibrary.tsx — default view of the USD assembler (USD_ASSEMBLER_V2 A2): everything
// already published in the project. Left: components (ADR 0018) and assemblies, with
// search. Right: detail (layers, versions, used by, instances, broken links).
// Backend contracts: GET /usd/library, POST /usd/component/refresh.

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Box, Boxes, RefreshCw, Copy, AlertTriangle, Search, Pencil, Check, X, Trash2, Pin as PinIcon, FolderOpen, ClipboardList } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { Btn, SecTitle, Pill } from '../../components/shared/ui'
import { api } from '../../api/client'
import type { UsdAssemblyInfo, UsdComponentInfo, UsdLibrary as Library, UsdSlotPin, UsdSlotRef } from '../../api/client'
import { useI18n } from '../../i18n'

type Tab = 'components' | 'assemblies'
type Selection = { tab: Tab; name: string } | null

const SLOT_ORDER = ['model', 'skel', 'look']

const stateColor: Record<UsdComponentInfo['state'], string> = {
  ok: 'var(--ok)', stale: 'var(--warn)', missing: 'var(--ink-3)', incomplete: 'var(--ink-4)',
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
  const [busy, setBusy] = useState<string | null>(null)

  const load = useCallback(() => {
    if (!project) { setLib(null); return }
    setLoading(true)
    api.getUsdLibrary(project)
      .then(setLib)
      .catch(e => { setLib(null); toast.error(e instanceof Error ? e.message : String(e)) })
      .finally(() => setLoading(false))
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

  async function refresh(name: string, pins?: Record<string, UsdSlotPin | null>) {
    if (!project) return
    setBusy(name)
    try {
      const res = await api.refreshUsdComponent(project, name, pins)
      if (res.changed) toast.success(tr('usd.lib.generated', { name, version: res.version ?? '' }))
      else toast.info(tr('usd.lib.unchanged'))
      load()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
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
            <Pill active={tab === 'components'} onClick={() => setTab('components')} style={{ cursor: 'pointer' }}>
              {tr('usd.lib.components')} {lib ? lib.components.length : ''}
            </Pill>
            <Pill active={tab === 'assemblies'} onClick={() => setTab('assemblies')} style={{ cursor: 'pointer' }}>
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
              sub={`${SLOT_ORDER.filter(s => c.slots[s] || c.published[s]).join(' · ') || '-'}${c.used_by.length ? `  ·  ${c.used_by.length} asm` : ''}`}
            />
          ))}
          {tab === 'assemblies' && assemblies.map(a => (
            <ListRow key={a.file} active={sel?.tab === 'assemblies' && sel.name === a.name}
              onClick={() => setSel({ tab: 'assemblies', name: a.name })}
              icon={<Boxes size={12} strokeWidth={1.75} />}
              title={a.name}
              meta={a.broken > 0 ? <AlertTriangle size={11} strokeWidth={2} color="var(--err)" /> : null}
              sub={`${a.instances.length} ${tr('usd.lib.instances').toLowerCase()}`}
            />
          ))}
          {lib && (tab === 'components' ? components : assemblies).length === 0 && (
            <div className="lbl" style={{ padding: '8px 6px', fontSize: 10, color: 'var(--ink-4)' }}>{tr('usd.lib.empty')}</div>
          )}
        </div>
      </div>

      {/* ── right: detail ──────────────────────────────────────────────────── */}
      <div style={{ flex: 1, minWidth: 0, overflowY: 'auto', padding: '14px 20px 20px' }}>
        {selComponent ? (
          <ComponentDetail project={project} comp={selComponent} busy={busy === selComponent.name}
            onRefresh={pins => refresh(selComponent.name, pins)} onOpenAssembly={n => goTo('assemblies', n)} />
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

// Inline editor of one component slot: pick the publish (task, instance, version).
// Version "latest" keeps following that task's LAST; a vNNN freezes the slot.
function SlotEditor({ project, name, slot, current, busy, onApply, onCancel }: {
  project: string; name: string; slot: string; current: UsdSlotRef | undefined; busy: boolean
  onApply: (pin: UsdSlotPin | null) => void; onCancel: () => void
}) {
  const { t: tr } = useI18n()
  const [tasks, setTasks] = useState<string[]>([])
  const [task, setTask] = useState(current?.pin?.task ?? current?.task ?? '')
  const [instances, setInstances] = useState<string[]>([])
  const [instance, setInstance] = useState(current?.pin?.instance ?? '')
  const [versions, setVersions] = useState<string[]>([])
  const [version, setVersion] = useState(current?.pin?.version ?? 'latest')

  useEffect(() => {
    api.getUsdTasks(project, name).then(d => setTasks(d.tasks)).catch(() => setTasks([]))
  }, [project, name])
  useEffect(() => {
    if (!task) { setInstances([]); setVersions([]); return }
    api.getUsdInstances(project, name, task).then(d => setInstances(d.instances)).catch(() => setInstances([]))
    api.getUsdLayers(project, name, task)
      .then(d => setVersions(Object.entries(d.versions)
        .filter(([label, info]) => label !== 'LAST' && info.layers.includes(slot))
        .map(([label]) => label)
        .sort((a, b) => Number(b.slice(1)) - Number(a.slice(1)))))
      .catch(() => setVersions([]))
  }, [project, name, task, slot])

  const taskOpts = task && !tasks.includes(task) ? [task, ...tasks] : tasks
  return (
    <div style={{ gridColumn: '1 / -1', display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', padding: '6px 0', borderTop: '1px solid var(--rule)', borderBottom: '1px solid var(--rule)' }}>
      <span className="cap">{tr('usd.col.task')}</span>
      <select value={task} onChange={e => { setTask(e.target.value); setVersion('latest') }} style={{ ...selectStyle, width: 90 }}>
        <option value="">-</option>
        {taskOpts.map(t => <option key={t} value={t}>{t}</option>)}
      </select>
      <span className="cap">{tr('usd.col.instance')}</span>
      <select value={instance} onChange={e => setInstance(e.target.value)} style={{ ...selectStyle, width: 90 }}>
        <option value="">{tr('usd.lib.anyInstance')}</option>
        {instances.map(i => <option key={i} value={i}>{i}</option>)}
      </select>
      <span className="cap">{tr('usd.col.version')}</span>
      <select value={version} onChange={e => setVersion(e.target.value)} style={{ ...selectStyle, width: 110, fontFamily: 'var(--mono)' }}>
        <option value="latest">{tr('usd.lib.followLatest')}</option>
        {versions.map(v => <option key={v} value={v}>{v}</option>)}
      </select>
      <div style={{ flex: 1 }} />
      <Btn sm primary disabled={busy || !task} onClick={() => onApply({ task, instance, version })}>
        <Check size={11} strokeWidth={2} /> {tr('usd.lib.apply')}
      </Btn>
      {current?.pin && !current.pin.exclude && (
        <Btn sm disabled={busy} onClick={() => onApply(null)} title={tr('usd.lib.autoHint')}>{tr('usd.lib.auto')}</Btn>
      )}
      {slot !== 'model' && (
        <Btn sm ghost disabled={busy} onClick={() => onApply({ exclude: true })}>
          <Trash2 size={11} strokeWidth={2} /> {tr('usd.lib.removeSlot')}
        </Btn>
      )}
      <Btn sm ghost disabled={busy} onClick={onCancel}><X size={11} strokeWidth={2} /></Btn>
    </div>
  )
}

function ComponentDetail({ project, comp, busy, onRefresh, onOpenAssembly }: {
  project: string; comp: UsdComponentInfo; busy: boolean
  onRefresh: (pins?: Record<string, UsdSlotPin | null>) => Promise<void>
  onOpenAssembly: (name: string) => void
}) {
  const { t: tr } = useI18n()
  const navigate = useNavigate()
  const [editing, setEditing] = useState<string | null>(null)
  useEffect(() => { setEditing(null) }, [comp.name])
  // Asset folder = parent of <NAME_path>/usd. Production opens on the model task.
  const assetDir = comp.dir.replace(/[\\/]usd[\\/]?$/i, '')
  const task = comp.published.model?.task ?? comp.published.skel?.task ?? 'GEO'
  const slots = SLOT_ORDER
  const canGenerate = comp.state === 'missing' || comp.state === 'stale'
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxWidth: 820 }}>
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
            state: { openFavorite: { project, class: comp.class, name: comp.name, task } },
          })}>
            <ClipboardList size={11} strokeWidth={2} /> {tr('usd.lib.openProduction')}
          </Btn>
        )}
        {comp.last && (
          <Btn sm ghost onClick={() => copy(comp.last as string, tr('usd.lib.copied'))} title={comp.last}>
            <Copy size={11} strokeWidth={2} /> {tr('usd.lib.copyPath')}
          </Btn>
        )}
        {canGenerate && (
          <Btn sm primary disabled={busy} onClick={() => void onRefresh()}>
            <RefreshCw size={11} strokeWidth={2} style={busy ? { animation: 'spin 1s linear infinite' } : undefined} />
            {comp.state === 'missing' ? tr('usd.lib.generate') : tr('usd.lib.update')}
          </Btn>
        )}
      </div>

      <SecTitle>{tr('usd.lib.slots')}</SecTitle>
      <div className="card" style={{ padding: '6px 10px' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '70px 1fr 1fr 110px', gap: '6px 10px', alignItems: 'center' }}>
          <span className="cap">{tr('usd.lib.col.slot')}</span>
          <span className="cap">{tr('usd.lib.col.inComponent')}</span>
          <span className="cap">{tr('usd.lib.col.published')}</span>
          <span />
          {slots.map(s => {
            const inC = comp.slots[s], pub = comp.published[s]
            const excluded = !!inC?.pin?.exclude
            const pinned = !!inC?.pin && !excluded
            const differs = !pinned && !excluded && !!pub && (!inC || inC.version !== pub.version || inC.task !== pub.task)
            const cells = [
              <span key={`${s}-n`} style={{ fontSize: 11, color: 'var(--ink-2)' }}>{s}</span>,
              <span key={`${s}-c`} style={{ ...mono, color: excluded ? 'var(--ink-4)' : 'var(--ink-2)', display: 'flex', alignItems: 'center', gap: 6 }}>
                {excluded ? tr('usd.lib.removed') : inC ? `${inC.task} ${inC.version}` : '-'}
                {pinned && (
                  <span className="lbl" title={tr('usd.lib.pinnedHint')} style={{ fontSize: 9, color: 'var(--accent-hi)', display: 'flex', alignItems: 'center', gap: 3 }}>
                    <PinIcon size={9} strokeWidth={2} /> {inC?.pin?.version === 'latest' ? tr('usd.lib.pinnedTask') : tr('usd.lib.frozen')}
                  </span>
                )}
              </span>,
              <span key={`${s}-p`} style={{ ...mono, color: differs ? stateColor.stale : 'var(--ink-3)' }}>{pub ? `${pub.task} ${pub.version}` : '-'}</span>,
              <div key={`${s}-a`} style={{ display: 'flex', justifyContent: 'flex-end' }}>
                {comp.version && editing !== s && (
                  <Btn sm ghost onClick={() => setEditing(s)}>
                    <Pencil size={10} strokeWidth={2} /> {inC ? tr('usd.lib.changeLink') : tr('usd.lib.addSlot')}
                  </Btn>
                )}
              </div>,
            ]
            if (editing === s) {
              cells.push(
                <SlotEditor key={`${s}-e`} project={project} name={comp.name} slot={s} current={inC} busy={busy}
                  onCancel={() => setEditing(null)}
                  onApply={pin => { void onRefresh({ [s]: pin }).then(() => setEditing(null)) }} />,
              )
            }
            return cells
          })}
        </div>
      </div>

      <SecTitle>{tr('usd.lib.versions')}</SecTitle>
      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
        {comp.versions.length === 0 && <span className="lbl" style={{ fontSize: 10, color: 'var(--ink-4)' }}>-</span>}
        {[...comp.versions].reverse().map(v => (
          <Pill key={v} active={v === comp.version}><span style={mono}>{v}</span></Pill>
        ))}
      </div>

      <SecTitle>{tr('usd.lib.usedBy')}</SecTitle>
      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
        {comp.used_by.length === 0 && <span className="lbl" style={{ fontSize: 10, color: 'var(--ink-4)' }}>{tr('usd.lib.unused')}</span>}
        {comp.used_by.map(a => (
          <Pill key={a} onClick={() => onOpenAssembly(a)} style={{ cursor: 'pointer' }}>
            <Boxes size={10} strokeWidth={2} /> {a}
          </Pill>
        ))}
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
  const [editing, setEditing] = useState<string | null>(null)
  const [target, setTarget] = useState('')
  const [version, setVersion] = useState('LAST')
  const [busy, setBusy] = useState(false)
  useEffect(() => { setEditing(null) }, [asm.file])

  const linkable = components.filter(c => c.versions.length > 0)
  const targetVersions = linkable.find(c => c.name === target)?.versions ?? []

  function startEdit(prim: string, component: string | null, followsLast: boolean, assetPath: string) {
    setEditing(prim)
    setTarget(component ?? linkable[0]?.name ?? '')
    const m = followsLast ? null : assetPath.match(/_(v\d+)\//)
    setVersion(m ? m[1] : 'LAST')
  }

  async function apply(prim: string) {
    setBusy(true)
    try {
      await api.relinkUsdInstance(project, asm.file, prim, target, version)
      toast.success(tr('usd.lib.relinked', { name: prim.split('/').pop() ?? prim, target: `${target} ${version}` }))
      setEditing(null)
      onChanged()
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxWidth: 820 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <Boxes size={15} strokeWidth={1.75} color="var(--ink-3)" />
        <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--ink)' }}>{asm.name}</span>
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

      <SecTitle>{tr('usd.lib.instances')}</SecTitle>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {asm.instances.length === 0 && <span className="lbl" style={{ fontSize: 10, color: 'var(--ink-4)' }}>{tr('usd.lib.noInstance')}</span>}
        {asm.instances.map(i => (
          <div key={`${i.prim}|${i.asset_path}`} className="card" style={{
            padding: '6px 10px', display: 'flex', flexDirection: 'column', gap: 6,
            borderColor: i.broken ? 'var(--err)' : undefined,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
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
              {i.broken && (
                <span className="lbl" style={{ fontSize: 9.5, color: 'var(--err)', display: 'flex', alignItems: 'center', gap: 4 }}>
                  <AlertTriangle size={10} strokeWidth={2} /> {tr('usd.lib.broken')}
                </span>
              )}
              {editing !== i.prim && (
                <Btn sm ghost disabled={linkable.length === 0} onClick={() => startEdit(i.prim, i.component, i.follows_last, i.asset_path)}>
                  <Pencil size={10} strokeWidth={2} /> {tr('usd.lib.changeLink')}
                </Btn>
              )}
            </div>
            {editing === i.prim && (
              <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', borderTop: '1px solid var(--rule)', paddingTop: 6 }}>
                <span className="cap">{tr('usd.lib.components')}</span>
                <select value={target} onChange={e => { setTarget(e.target.value); setVersion('LAST') }} style={{ ...selectStyle, width: 160 }}>
                  {linkable.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}
                </select>
                <span className="cap">{tr('usd.col.version')}</span>
                <select value={version} onChange={e => setVersion(e.target.value)} style={{ ...selectStyle, width: 110, fontFamily: 'var(--mono)' }}>
                  <option value="LAST">{tr('usd.lib.followLast')}</option>
                  {[...targetVersions].reverse().map(v => <option key={v} value={v}>{v}</option>)}
                </select>
                <div style={{ flex: 1 }} />
                <Btn sm primary disabled={busy || !target} onClick={() => void apply(i.prim)}>
                  <Check size={11} strokeWidth={2} /> {tr('usd.lib.apply')}
                </Btn>
                <Btn sm ghost disabled={busy} onClick={() => setEditing(null)}><X size={11} strokeWidth={2} /></Btn>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
