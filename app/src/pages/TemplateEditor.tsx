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

// TASK options that are NOT real TASK(=TYPE) tokens but must appear in the selector.
// The project's TYPE token keys are appended after these at runtime.
const TASK_EXTRAS = ['DEFAULT', 'SEQ', 'SHOT', 'ENV', 'FX']

// Software a preset/scene can target (frontend DCC keys, same set as the launcher).
const SOFTS: { key: string; name: string }[] = [
  { key: 'maya', name: 'Maya' },
  { key: 'houdini', name: 'Houdini' },
  { key: 'nuke', name: 'Nuke' },
  { key: 'zbrush', name: 'ZBrush' },
  { key: 'substance_painter', name: 'Painter' },
  { key: 'substance_designer', name: 'Designer' },
  { key: 'mari', name: 'Mari' },
  { key: 'marvelous', name: 'Marvelous' },
  { key: 'photoshop', name: 'Photoshop' },
]

// Guess the target SOFT from a file extension (only a suggestion; user can override).
const _SOFT_BY_EXT: Record<string, string> = {
  hip: 'houdini', hipnc: 'houdini', hiplc: 'houdini', hda: 'houdini', otl: 'houdini',
  bgeo: 'houdini', geo: 'houdini',
  ma: 'maya', mb: 'maya',
  nk: 'nuke',
  zpr: 'zbrush', ztl: 'zbrush', zbr: 'zbrush',
  spp: 'substance_painter',
  sbs: 'substance_designer', sbsar: 'substance_designer',
  mra: 'mari',
  zprj: 'marvelous',
  psd: 'photoshop',
}
function inferSoftFromFile(file: string | null): string {
  if (!file) return ''
  const ext = file.toLowerCase().split('.').pop() ?? ''
  return _SOFT_BY_EXT[ext] ?? ''
}

// ── one preset row ─────────────────────────────────────────────────────────────
function PresetRow({
  project, preset, taskOptions, onChange,
}: {
  project: string
  preset: Preset
  taskOptions: string[]
  onChange: (presets: Preset[]) => void
}) {
  const { t } = useI18n()
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(preset.name)

  const link = async () => {
    // Accept ANY file type (a preset can be a .hip, .ma, .nk, .usda, .zpr…), not
    // just the exe/app default the picker uses for DCC executable paths.
    const src = await window.electronAPI?.openFile?.([{ name: 'Tous les fichiers', extensions: ['*'] }])
    if (!src) return
    try {
      const r = await api.linkPreset(project, preset.id, src)
      let presets = r.presets
      // Auto-suggest the SOFT from the file extension when none is set yet. This is
      // only a suggestion — the user can override it via the SOFT selector.
      const guess = inferSoftFromFile(r.preset.file)
      if (guess && !r.preset.soft) {
        const r2 = await api.setPresetMeta(project, preset.id, r.preset.task ?? '', guess)
        presets = r2.presets
      }
      onChange(presets); toast.success(t('te.linkOk'))
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
  // Assign the TASK token (or DEFAULT) and target SOFT. Both are sent together;
  // the changed one is passed, the other keeps its current value.
  const setMeta = async (task: string, soft: string) => {
    try { const r = await api.setPresetMeta(project, preset.id, task, soft); onChange(r.presets); toast.success(t('te.metaOk')) }
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
        <div style={{ fontSize: 12, marginTop: 2, color: preset.file ? 'var(--accent-hi)' : 'var(--ink-4)' }}>
          {preset.file ? preset.file : t('te.slotEmpty')}
        </div>
        {/* TASK token (or DEFAULT) + target SOFT — greyed placeholder inside the box */}
        <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
          <select
            value={preset.task ?? ''}
            onChange={(e) => void setMeta(e.target.value, preset.soft ?? '')}
            style={{ ...metaSelect, flex: 1, color: preset.task ? 'var(--ink)' : 'var(--ink-4)' }}
          >
            <option value="" style={{ color: 'var(--ink-4)' }}>{t('te.task')}</option>
            {taskOptions.map((tk) => <option key={tk} value={tk} style={{ color: 'var(--ink)' }}>{tk}</option>)}
          </select>
          <select
            value={preset.soft ?? ''}
            onChange={(e) => void setMeta(preset.task ?? '', e.target.value)}
            style={{ ...metaSelect, flex: 1, color: preset.soft ? 'var(--ink)' : 'var(--ink-4)' }}
          >
            <option value="" style={{ color: 'var(--ink-4)' }}>{t('te.soft')}</option>
            {SOFTS.map((s) => <option key={s.key} value={s.key} style={{ color: 'var(--ink)' }}>{s.name}</option>)}
          </select>
        </div>
      </div>
      <button onClick={link} style={btnGhost}>{t('te.link')}</button>
      {preset.file && <button onClick={unlink} style={btnGhost}>{t('te.unlink')}</button>}
      <button onClick={remove} title={t('te.remove')} style={{ ...btnGhost, color: 'var(--err)' }}>×</button>
    </div>
  )
}

// ── one preset shipped by FLUX (read-only) ───────────────────────────────────────
// Sequence render scene (ADR 0036): launched from the launcher's New Scene menu
// (Houdini > SEQ), FLUX builds <SEQ>_render.hip when missing and opens it.
function BuiltinRow({ preset }: { preset: Preset }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 10, padding: '10px 12px',
      background: 'var(--paper-2)', border: '1px solid var(--rule)', borderRadius: 8, boxShadow: 'var(--shadow-xs)',
    }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 600 }}>{preset.name}</div>
        <div style={{ fontSize: 12, marginTop: 2, color: preset.exists ? 'var(--accent-hi)' : 'var(--ink-4)' }}>
          {preset.file}
        </div>
        <div style={{ fontSize: 11, marginTop: 6, color: 'var(--ink-3)' }}>
          {preset.task} · Houdini · un FLUX Shot et un ROP Karma par shot. Launcher : Houdini, New Scene, {preset.task}.
        </div>
      </div>
      <span style={{ fontSize: 11, color: 'var(--ink-3)', border: '1px solid var(--rule)', borderRadius: 5, padding: '2px 6px' }}>
        FLUX
      </span>
    </div>
  )
}

// ── page ───────────────────────────────────────────────────────────────────────
export function TemplateEditor() {
  const { t } = useI18n()
  const [projects, setProjects] = useState<string[]>([])
  const [project, setProject] = useState('')
  const [presets, setPresets] = useState<Preset[]>([])
  const [builtins, setBuiltins] = useState<Preset[]>([])   // shipped by FLUX, read-only
  const [taskOptions, setTaskOptions] = useState<string[]>(TASK_EXTRAS)
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
    if (!proj) { setPresets([]); setBuiltins([]); setTaskOptions(TASK_EXTRAS); return }
    setLoading(true)
    try {
      const [pr, tk] = await Promise.all([api.listPresets(proj, true), api.getTokens(proj).catch(() => null)])
      setPresets(pr.presets.filter((p) => !p.builtin))
      setBuiltins(pr.presets.filter((p) => p.builtin))
      // TASK options = the fixed extras + the project's real TASK(=TYPE) token keys.
      const typeKeys = tk ? Object.keys(tk.tokens?.TYPE ?? {}) : []
      setTaskOptions([...TASK_EXTRAS, ...typeKeys.filter((k) => !TASK_EXTRAS.includes(k))])
    }
    catch (e) { toast.error(e instanceof Error ? e.message : 'error') }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { void load(project) }, [project, load])

  // Apply an updated preset list AND notify the rest of the app (the launcher's
  // "New Scene" buttons recolour when a soft gains/loses a linked preset).
  const applyPresets = useCallback((next: Preset[]) => {
    setPresets(next)
    window.dispatchEvent(new Event('flux:refresh'))
  }, [])

  const add = async () => {
    try { const r = await api.addPreset(project); applyPresets(r.presets) }
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
          <PresetRow key={p.id} project={project} preset={p} taskOptions={taskOptions} onChange={applyPresets} />
        ))}
      </div>

      {builtins.length > 0 && (
        <>
          <div style={{ margin: '22px 0 8px', fontSize: 11, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--ink-4)' }}>
            Livrés par FLUX
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {builtins.map((p) => <BuiltinRow key={p.id} preset={p} />)}
          </div>
        </>
      )}
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
const metaSelect: React.CSSProperties = {
  font: 'inherit', fontSize: 11, color: 'var(--ink)', background: 'var(--paper)',
  border: '1px solid var(--rule)', borderRadius: 5, padding: '3px 6px', cursor: 'pointer',
}
