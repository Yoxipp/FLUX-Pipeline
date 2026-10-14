// OpenInMenu.tsx — "Ouvrir dans >" for a project file, outside the Folder Manager
// (Production tab: the assembled USD of an asset, the publishes of a task; the maintainer
// 2026-09-26). Same targets as the Folder Manager's context menu: for a USD file,
// what the pipeline loads first (the asset / decor / shot, GET /dcc/load-targets),
// the layer alone second; then every CONNECTED DCC that can import the file.

import { useEffect, useRef, useState } from 'react'
import { ExternalLink } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '../../api/client'
import type { LoadTargets } from '../../api/client'
import { useDccStatus } from '../../hooks/useDccStatus'
import { readActiveInstancePort } from '../../hooks/useActiveInstances'

const USD_EXTS = new Set(['.usd', '.usda', '.usdc', '.usdz'])
const LOP_IMPORT_EXTS = new Set(['.usd', '.usda', '.usdc', '.usdz', '.abc', '.bgeo', '.sc', '.geo', '.obj',
                                 '.fbx', '.vdb', '.gltf', '.glb', '.ply', '.stl'])
const MAYA_IMPORT_EXTS = new Set(['.obj', '.fbx', '.ma', '.mb', '.abc', '.usd', '.usda', '.usdc', '.usdz'])
const NUKE_IMPORT_EXTS = new Set(['.exr', '.png', '.jpg', '.jpeg', '.tif', '.tiff', '.dpx', '.mov', '.psd', '.hdr', '.tga'])
const PS_OPEN_EXTS = new Set(['.psd', '.psb', '.png', '.jpg', '.jpeg', '.tif', '.tiff', '.bmp', '.gif'])
const LOP_MODES = { reference: 'Reference', payload: 'Payload', sublayer: 'Sublayer' } as const

/** Project-relative path of a stored path ("$FLUX/DOSSIER_PROJETS/<project>/..." or absolute). */
export function projectRelPath(project: string, stored: string): string {
  const p = (stored || '').replace(/\\/g, '/')
  const marker = `/${project}/`
  const i = p.indexOf(marker)
  return i >= 0 ? p.slice(i + marker.length) : p.replace(/^\/+/, '')
}

function isOffline(msg: string): boolean {
  return /urlopen|refused|connect|actively refused|WinError|répond pas/i.test(msg)
}

async function openInHoudini(project: string, rel: string, name: string) {
  const id = toast.loading(`Import de ${name} dans Houdini…`)
  try {
    const tok = await api.getFluxTokensFromPath(project, rel)
    const res = await api.createFluxImporterNode({
      project, flux_class: tok.CLASS, flux_type: tok.TYPE, flux_name: tok.NAME,
      flux_instance: tok.INSTANCE, flux_iter: 'LAST', rel_path: rel,
    })
    if (res.result?.mode === 'replaced') toast.success(`${name} : path mis à jour sur le node sélectionné`, { id })
    else if (res.result?.resolved_path) toast.success(`${name} importé dans Houdini`, { id })
    else toast.warning(`Node créé mais fichier non résolu pour ${name} : clique Resolve dans le node`, { id })
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e)
    toast.error(isOffline(msg) ? 'Houdini non connecté : lance le serveur FLUX dans Houdini' : `Import Houdini échoué : ${msg}`, { id })
  }
}

async function openInHoudiniLop(project: string, rel: string, name: string, mode: keyof typeof LOP_MODES) {
  const id = toast.loading(`${LOP_MODES[mode]} de ${name} dans Houdini…`)
  try {
    const r = (await api.houdiniImportLop(project, rel, mode)).result
    toast.success(r?.mode?.endsWith('_added')
      ? `${name} ajouté à ${r?.node_path} (entrée ${r?.entry})`
      : `${name} : ${LOP_MODES[mode]} LOP créé (${r?.node_path})`, { id })
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e)
    toast.error(isOffline(msg) ? 'Houdini non connecté : lance le serveur FLUX dans Houdini' : `Import LOP échoué : ${msg}`, { id })
  }
}

async function openInMaya(project: string, rel: string, name: string, mode: 'import' | 'proxy' = 'import') {
  const id = toast.loading(`Import de ${name} dans Maya…`)
  try {
    await api.importFileInMaya(project, rel, readActiveInstancePort('Maya') ?? undefined, mode)
    toast.success(`${name} importé dans Maya`, { id })
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e)
    toast.error(isOffline(msg) ? 'Maya non connecté : ouvre Maya avec le bridge FLUX actif' : `Import Maya échoué : ${msg}`, { id })
  }
}

async function simple(label: string, name: string, run: () => Promise<unknown>) {
  const id = toast.loading(`${name} → ${label}…`)
  try {
    await run()
    toast.success(`${name} → ${label}`, { id })
  } catch (e) {
    toast.error(`${label} : ${e instanceof Error ? e.message : String(e)}`, { id })
  }
}

interface Target { label: string; run: () => void }

export function OpenInMenu({ project, relPath, label = 'Ouvrir dans', compact = false }: {
  project: string
  relPath: string            // project-relative file path
  label?: string
  compact?: boolean          // icon-only button (publish rows)
}) {
  const dcc = useDccStatus()
  const [open, setOpen] = useState(false)
  const [lt, setLt] = useState<LoadTargets | null>(null)
  const [loading, setLoading] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const name = relPath.split('/').pop() || relPath
  const ext = '.' + (name.split('.').pop() ?? '').toLowerCase()

  useEffect(() => {
    if (!open) return
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [open])

  const toggle = (e: React.MouseEvent) => {
    e.stopPropagation()
    const next = !open
    setOpen(next)
    if (next && USD_EXTS.has(ext) && project && relPath) {
      setLoading(true)
      api.getLoadTargets(project, relPath).then(setLt).catch(() => setLt(null)).finally(() => setLoading(false))
    }
  }

  const houdini = !!dcc['Houdini']?.connected
  const maya = !!dcc['Maya']?.connected
  const targets: Target[] = []
  const lop: Target[] = houdini && LOP_IMPORT_EXTS.has(ext)
    ? (Object.keys(LOP_MODES) as (keyof typeof LOP_MODES)[]).map(m => ({
        label: `Houdini LOP : ${LOP_MODES[m]}`, run: () => void openInHoudiniLop(project, relPath, name, m),
      }))
    : []
  if (USD_EXTS.has(ext) && lt && !lt.legacy) {
    for (const t of lt.targets) {
      const what = t.primary ? t.label : 'couche seule'
      if (houdini) targets.push({ label: `Houdini : ${what}`, run: () => void openInHoudini(project, t.rel_path, name) })
      if (maya) {
        targets.push({ label: `Maya : ${what} (aplati)`, run: () => void openInMaya(project, t.rel_path, name) })
        if (t.primary) targets.push({ label: `Maya : ${what} (proxy USD, variantes)`, run: () => void openInMaya(project, t.rel_path, name, 'proxy') })
      }
    }
    targets.push(...lop)
  } else if (!USD_EXTS.has(ext) || !loading) {
    if (houdini) targets.push({ label: 'Houdini', run: () => void openInHoudini(project, relPath, name) })
    targets.push(...lop)
    if (maya && MAYA_IMPORT_EXTS.has(ext)) targets.push({ label: 'Maya', run: () => void openInMaya(project, relPath, name) })
    if (dcc['Nuke']?.connected && NUKE_IMPORT_EXTS.has(ext)) {
      targets.push({ label: 'Nuke', run: () => void simple('Nuke (Read)', name, () => api.nukeImportPath(project, relPath)) })
    }
    if (PS_OPEN_EXTS.has(ext)) {
      targets.push({ label: 'Photoshop', run: () => void simple('Photoshop', name, () => api.photoshopOpen(project, relPath)) })
    }
  }

  return (
    <div ref={ref} style={{ position: 'relative', display: 'inline-flex' }} onClick={e => e.stopPropagation()}>
      <button onClick={toggle} title={`${label} : ${name}`} disabled={!project || !relPath} style={compact ? _icon : _btn}>
        <ExternalLink size={compact ? 9 : 10} strokeWidth={2} />
        {!compact && <span>{label}</span>}
      </button>
      {open && (
        <div style={{
          position: 'absolute', top: 'calc(100% + 4px)', right: 0, zIndex: 700, minWidth: 220,
          padding: 4, borderRadius: 7, border: '1px solid var(--rule-2)', background: 'var(--paper)',
          boxShadow: 'var(--shadow-md)', fontFamily: 'var(--sans)',
        }}>
          {lt?.message && <div style={{ padding: '4px 8px', fontSize: 10.5, color: 'var(--ink-4)' }}>{lt.message}</div>}
          {loading && <div style={{ padding: '6px 8px', fontSize: 11, color: 'var(--ink-4)' }}>Lecture…</div>}
          {!loading && targets.length === 0 && (
            <div style={{ padding: '6px 8px', fontSize: 11, color: 'var(--ink-4)', lineHeight: 1.45 }}>
              Aucun logiciel connecté pour ce fichier (Houdini, Maya, Nuke, Photoshop).
            </div>
          )}
          {!loading && targets.map(t => (
            <div key={t.label} onClick={() => { setOpen(false); t.run() }}
              style={{ padding: '6px 8px', borderRadius: 5, fontSize: 11, color: 'var(--ink-2)', cursor: 'pointer' }}
              onMouseEnter={e => { e.currentTarget.style.background = 'var(--accent-soft)' }}
              onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}>
              {t.label}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

const _btn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 4, padding: '4px 10px', borderRadius: 6,
  border: '1px solid var(--rule-2)', background: 'var(--paper)', color: 'var(--ink-2)',
  fontFamily: 'var(--sans)', fontSize: 11, cursor: 'pointer',
}
const _icon: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 18, height: 18,
  borderRadius: 4, border: '1px solid var(--rule-2)', background: 'var(--paper-2)', color: 'var(--ink-3)',
  cursor: 'pointer', padding: 0,
}
