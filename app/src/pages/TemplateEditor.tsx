// TemplateEditor.tsx — manage a project's reusable "presets" (template library).
//
// RETAKES-3: link/unlink/rename preset slots stored in <project>/template/, and drop
// a preset's file into any folder of the project. Presets also surface as quick-drop
// buttons in the folder manager (Projects.tsx). Storage is the template/ folder from
// RETAKES-2. Flat design, no glow, no em dash (see project memory).

import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
import { api } from '../api/client'
import { useI18n } from '../i18n'
import type { Preset } from '../types'

interface BrowseNode { name: string; path: string }

// ── folder picker modal (browse the project tree, pick a destination) ──────────
function DropModal({
  project, onClose, onPick,
}: {
  project: string
  onClose: () => void
  onPick: (subpath: string) => void
}) {
  const { t } = useI18n()
  const [stack, setStack] = useState<string[]>([])
  const [folders, setFolders] = useState<BrowseNode[]>([])
  const [loading, setLoading] = useState(false)

  const sub = stack.join('/')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const r = await api.browseProject(project, sub || undefined)
      setFolders(r.folders ?? [])
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'browse failed')
    } finally {
      setLoading(false)
    }
  }, [project, sub])

  useEffect(() => { void load() }, [load])

  return (
    <div onClick={onClose} style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,.45)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50,
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        width: 460, maxHeight: '70vh', background: 'var(--paper)', color: 'var(--ink)',
        border: '1px solid var(--rule)', borderRadius: 10, boxShadow: 'var(--shadow-sm)',
        display: 'flex', flexDirection: 'column', overflow: 'hidden',
      }}>
        <div style={{ padding: '12px 14px', borderBottom: '1px solid var(--rule)', fontWeight: 600 }}>
          {t('te.dropInto')}
        </div>
        {/* breadcrumb */}
        <div style={{ padding: '8px 14px', display: 'flex', gap: 6, flexWrap: 'wrap', fontSize: 12, color: 'var(--ink-3)' }}>
          <button onClick={() => setStack([])} style={crumbBtn}>{project}</button>
          {stack.map((seg, i) => (
            <span key={i} style={{ display: 'flex', gap: 6 }}>
              <span>/</span>
              <button onClick={() => setStack(stack.slice(0, i + 1))} style={crumbBtn}>{seg}</button>
            </span>
          ))}
        </div>
        <div style={{ flex: 1, overflowY: 'auto', padding: '4px 8px' }}>
          {loading && <div style={{ padding: 12, color: 'var(--ink-3)' }}>…</div>}
          {!loading && folders.length === 0 && (
            <div style={{ padding: 12, color: 'var(--ink-4)', fontSize: 13 }}>—</div>
          )}
          {folders.map((f) => (
            <button key={f.path} onClick={() => setStack([...stack, f.name])} style={{
              display: 'block', width: '100%', textAlign: 'left', padding: '7px 10px',
              background: 'transparent', border: 'none', color: 'var(--ink)', cursor: 'pointer',
              borderRadius: 6, fontSize: 13,
            }}>📁 {f.name}</button>
          ))}
        </div>
        <div style={{ padding: '10px 14px', borderTop: '1px solid var(--rule)', display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button onClick={onClose} style={btnGhost}>×</button>
          <button onClick={() => onPick(sub)} style={btnAccent}>{t('te.dropInto')} {sub ? `/${sub}` : `/`}</button>
        </div>
      </div>
    </div>
  )
}

// ── one preset row ─────────────────────────────────────────────────────────────
function PresetRow({
  project, preset, onChange,
}: {
  project: string
  preset: Preset
  onChange: (presets: Preset[]) => void
}) {
  const { t } = useI18n()
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(preset.name)
  const [dropOpen, setDropOpen] = useState(false)

  const link = async () => {
    const src = await window.electronAPI?.openFile?.()
    if (!src) return
    try {
      const r = await api.linkPreset(project, preset.id, src)
      onChange(r.presets); toast.success(t('te.linkOk'))
    } catch (e) { toast.error(`${t('te.err')}: ${e instanceof Error ? e.message : ''}`) }
  }
  const unlink = async () => {
    try { const r = await api.unlinkPreset(project, preset.id); onChange(r.presets) }
    catch (e) { toast.error(e instanceof Error ? e.message : 'error') }
  }
  const rename = async () => {
    setEditing(false)
    if (name.trim() === preset.name || !name.trim()) { setName(preset.name); return }
    try { const r = await api.renamePreset(project, preset.id, name.trim()); onChange(r.presets) }
    catch (e) { setName(preset.name); toast.error(e instanceof Error ? e.message : 'error') }
  }
  const remove = async () => {
    try { const r = await api.deletePreset(project, preset.id); onChange(r.presets) }
    catch (e) { toast.error(e instanceof Error ? e.message : 'error') }
  }
  const drop = async (subpath: string) => {
    setDropOpen(false)
    try { const r = await api.dropPreset(project, preset.id, subpath); toast.success(`${t('te.dropOk')}: ${r.name}`) }
    catch (e) { toast.error(`${t('te.err')}: ${e instanceof Error ? e.message : ''}`) }
  }

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 10, padding: '10px 12px',
      background: 'var(--paper-2)', border: '1px solid var(--rule)', borderRadius: 8, boxShadow: 'var(--shadow-xs)',
    }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        {editing ? (
          <input
            autoFocus value={name} onChange={(e) => setName(e.target.value)}
            onBlur={rename} onKeyDown={(e) => { if (e.key === 'Enter') rename(); if (e.key === 'Escape') { setEditing(false); setName(preset.name) } }}
            style={{ font: 'inherit', color: 'var(--ink)', background: 'var(--paper)', border: '1px solid var(--accent)', borderRadius: 5, padding: '2px 6px', width: '100%' }}
          />
        ) : (
          <button onClick={() => setEditing(true)} title={t('te.rename')} style={{
            background: 'transparent', border: 'none', color: 'var(--ink)', cursor: 'text',
            font: 'inherit', fontWeight: 600, padding: 0,
          }}>{preset.name}</button>
        )}
        <div style={{ fontSize: 12, marginTop: 2, color: preset.file ? 'var(--ok)' : 'var(--ink-4)' }}>
          {preset.file ? `${t('te.linked')} → ${preset.file}` : t('te.slotEmpty')}
        </div>
      </div>
      <button onClick={link} style={btnGhost}>{t('te.link')}</button>
      {preset.file && <button onClick={unlink} style={btnGhost}>{t('te.unlink')}</button>}
      {preset.file && <button onClick={() => setDropOpen(true)} style={btnAccent}>{t('te.dropInto')}</button>}
      <button onClick={remove} title={t('te.remove')} style={{ ...btnGhost, color: 'var(--err)' }}>×</button>
      {dropOpen && <DropModal project={project} onClose={() => setDropOpen(false)} onPick={drop} />}
    </div>
  )
}

// ── page ───────────────────────────────────────────────────────────────────────
export function TemplateEditor() {
  const { t } = useI18n()
  const [projects, setProjects] = useState<string[]>([])
  const [project, setProject] = useState('')
  const [presets, setPresets] = useState<Preset[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    (async () => {
      try {
        const [pl, cur] = await Promise.all([api.getProjects(), api.getCurrentProject()])
        setProjects(pl.projects)
        setProject(cur.project || pl.projects[0] || '')
      } catch { /* ignore */ }
    })()
  }, [])

  const load = useCallback(async (proj: string) => {
    if (!proj) { setPresets([]); return }
    setLoading(true)
    try { const r = await api.listPresets(proj); setPresets(r.presets) }
    catch (e) { toast.error(e instanceof Error ? e.message : 'error') }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { void load(project) }, [project, load])

  const add = async () => {
    try { const r = await api.addPreset(project); setPresets(r.presets) }
    catch (e) { toast.error(e instanceof Error ? e.message : 'error') }
  }

  return (
    <div style={{ padding: 20, color: 'var(--ink)', maxWidth: 760, margin: '0 auto' }}>
      <h1 style={{ fontSize: 20, margin: '0 0 2px' }}>{t('te.title')}</h1>
      <p style={{ margin: '0 0 16px', color: 'var(--ink-3)', fontSize: 13 }}>{t('te.subtitle')}</p>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
        <label style={{ fontSize: 13, color: 'var(--ink-3)' }}>{t('te.project')}</label>
        <select value={project} onChange={(e) => setProject(e.target.value)} style={{
          font: 'inherit', color: 'var(--ink)', background: 'var(--paper-2)',
          border: '1px solid var(--rule)', borderRadius: 6, padding: '4px 8px',
        }}>
          {projects.length === 0 && <option value="">{t('te.noProject')}</option>}
          {projects.map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
        <div style={{ flex: 1 }} />
        <button onClick={add} disabled={!project} style={btnAccent}>+ {t('te.add')}</button>
      </div>

      {loading && <div style={{ color: 'var(--ink-3)' }}>…</div>}
      {!loading && presets.length === 0 && project && (
        <div style={{ color: 'var(--ink-4)', fontSize: 13, padding: '20px 0' }}>{t('te.empty')}</div>
      )}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {presets.map((p) => (
          <PresetRow key={p.id} project={project} preset={p} onChange={setPresets} />
        ))}
      </div>
    </div>
  )
}

// ── shared inline button styles ─────────────────────────────────────────────────
const btnGhost: React.CSSProperties = {
  font: 'inherit', fontSize: 12, color: 'var(--ink-2)', background: 'transparent',
  border: '1px solid var(--rule)', borderRadius: 6, padding: '5px 9px', cursor: 'pointer',
}
const btnAccent: React.CSSProperties = {
  font: 'inherit', fontSize: 12, color: 'var(--paper)', background: 'var(--accent)',
  border: '1px solid var(--accent)', borderRadius: 6, padding: '5px 10px', cursor: 'pointer', fontWeight: 600,
}
const crumbBtn: React.CSSProperties = {
  font: 'inherit', fontSize: 12, color: 'var(--accent)', background: 'transparent',
  border: 'none', padding: 0, cursor: 'pointer',
}
