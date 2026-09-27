// "Open in" targets of the Folder Manager right-click menu: every currently-CONNECTED
// DCC that can import the clicked file. Plain functions (no view state) so every
// explorer view shares them.

import { toast } from 'sonner'
import { api } from '../../api/client'
import type { LoadTargets } from '../../api/client'
import { readActiveInstancePort } from '../../hooks/useActiveInstances'
import type { DccStatusMap } from '../../types'
import { USD_EXTS } from './shared'
import type { ExplorerItem } from './shared'

// Files a Houdini LOP loads directly (USD + Houdini's USD file format plugins).
const LOP_IMPORT_EXTS = new Set(['.usd', '.usda', '.usdc', '.usdz', '.abc', '.bgeo', '.sc', '.geo', '.obj',
                                 '.fbx', '.vdb', '.gltf', '.glb', '.ply', '.stl'])
const LOP_MODE_LABELS = { reference: 'Reference', payload: 'Payload', sublayer: 'Sublayer' } as const
type LopMode = keyof typeof LOP_MODE_LABELS

const MAYA_IMPORT_EXTS = new Set(['.obj', '.fbx', '.ma', '.mb', '.abc', '.usd', '.usda', '.usdc', '.usdz'])

// Nuke Read supports image/plate formats; Photoshop opens raster/PSD files.
const NUKE_IMPORT_EXTS = new Set(['.exr', '.png', '.jpg', '.jpeg', '.tif', '.tiff', '.dpx', '.mov', '.psd', '.hdr', '.tga'])
const PS_OPEN_EXTS     = new Set(['.psd', '.psb', '.png', '.jpg', '.jpeg', '.tif', '.tiff', '.bmp', '.gif'])

const isOffline = (msg: string) => /urlopen|refused|connect|actively refused|WinError/i.test(msg)
const errMsg = (e: unknown) => (e instanceof Error ? e.message : 'Erreur inconnue')

async function openInHoudini(project: string, rel_path: string, name: string) {
  // DCC imports can take a while (big USD stages): keep a spinner toast until done.
  const id = toast.loading(`Import de ${name} dans Houdini…`)
  try {
    const tok = await api.getFluxTokensFromPath(project, rel_path)
    const res = await api.createFluxImporterNode({
      project,
      flux_class:    tok.CLASS,
      flux_type:     tok.TYPE,
      flux_name:     tok.NAME,
      flux_instance: tok.INSTANCE,
      flux_iter:     'LAST',
      rel_path,   // exact file selected → used to re-path a selected node
    })
    // Node is created but resolve can still find nothing (asset missing for these
    // tokens, or FLUX unreachable from Houdini) — warn instead of a false success.
    if (res.result?.mode === 'replaced') {
      toast.success(`${name} : path mis à jour sur le node sélectionné`, { id })
    } else if (res.result?.resolved_path) {
      toast.success(`${name} importé dans Houdini`, { id })
    } else {
      toast.warning(`Node créé mais fichier non résolu pour ${name} : clique ↺ Resolve dans le node`, { id })
    }
  } catch (e) {
    const msg = errMsg(e)
    toast.error(isOffline(msg)
      ? 'Houdini non connecté : lance le serveur FLUX dans Houdini'
      : `Import Houdini échoué : ${msg}`, { id })
  }
}

async function importHoudiniLop(project: string, rel_path: string, name: string, mode: LopMode) {
  const label = LOP_MODE_LABELS[mode]
  const id = toast.loading(`${label} de ${name} dans Houdini…`)
  try {
    const res = await api.houdiniImportLop(project, rel_path, mode)
    const r = res.result
    const added = r?.mode?.endsWith('_added')
    toast.success(added
      ? `${name} ajouté à ${r?.node_path} (entrée ${r?.entry})`
      : `${name} : ${label} LOP créé (${r?.node_path})`, { id })
  } catch (e) {
    const msg = errMsg(e)
    toast.error(isOffline(msg)
      ? 'Houdini non connecté : lance le serveur FLUX dans Houdini'
      : `Import LOP échoué : ${msg}`, { id })
  }
}

async function openInMaya(project: string, rel_path: string, name: string, mode: 'import' | 'proxy' = 'import') {
  const id = toast.loading(`Import de ${name} dans Maya…`)
  try {
    await api.importFileInMaya(project, rel_path, readActiveInstancePort('Maya') ?? undefined, mode)
    toast.success(`${name} importé dans Maya`, { id })
  } catch (e) {
    const msg = errMsg(e)
    toast.error(msg.includes('répond pas')
      ? 'Maya non connecté : ouvre Maya avec le bridge FLUX actif (commandPort 7001)'
      : `Import Maya échoué : ${msg}`, { id })
  }
}

async function openInNuke(project: string, rel_path: string, name: string) {
  const id = toast.loading(`Import de ${name} dans Nuke…`)
  try {
    await api.nukeImportPath(project, rel_path)
    toast.success(`${name} → Nuke (Read)`, { id })
  } catch (e) {
    toast.error(`Import Nuke échoué : ${errMsg(e)}`, { id })
  }
}

async function openInPhotoshop(project: string, rel_path: string, name: string) {
  const id = toast.loading(`Ouverture de ${name} dans Photoshop…`)
  try {
    await api.photoshopOpen(project, rel_path)
    toast.success(`${name} ouvert dans Photoshop`, { id })
  } catch (e) {
    toast.error(`Ouverture Photoshop échouée : ${errMsg(e)}`, { id })
  }
}

async function deleteLegacy(project: string, rel_path: string, name: string, onDone: () => void) {
  try {
    const res = await api.deleteUsdLegacy(project, rel_path)
    toast.success(`${name} deplace dans le backup du projet`, { description: res.backup })
    onDone()
  } catch (e) {
    toast.error(e instanceof Error ? e.message : String(e))
  }
}

export function buildOpenInTargets(args: {
  project:     string
  subpath:     string[]
  items:       ExplorerItem[]
  dccStatus:   DccStatusMap
  loadTargets: { name: string; lt: LoadTargets } | null
  onChanged:   () => void   // a file moved on disk (legacy file backed up)
}): { dcc: string; onClick: () => void }[] {
  const { project, subpath, items, dccStatus, loadTargets, onChanged } = args
  if (items.length !== 1) return []
  const item = items[0]
  if (item.isDir) return []
  const rel = [...subpath, item.name].join('/')
  const ext = '.' + (item.name.split('.').pop() ?? '').toLowerCase()
  const houdini = !!dccStatus['Houdini']?.connected
  const maya    = !!dccStatus['Maya']?.connected
  const targets: { dcc: string; onClick: () => void }[] = []
  // V4 (ADR 0019 points 5 and 7): a USD file opens what the pipeline loads (the asset,
  // the decor or the shot), the department layer alone comes second, an old file never.
  const lt = loadTargets?.name === item.name ? loadTargets.lt : null
  // Houdini LOP: this exact file as Reference / Payload / Sublayer, into the
  // selected LOP of that kind or a new one (any USD-readable format).
  const lopTargets = houdini && LOP_IMPORT_EXTS.has(ext)
    ? (Object.keys(LOP_MODE_LABELS) as LopMode[]).map(mode => ({
        dcc: `Houdini LOP : ${LOP_MODE_LABELS[mode]}`,
        onClick: () => void importHoudiniLop(project, rel, item.name, mode),
      }))
    : []
  if (USD_EXTS.has(ext) && lt) {
    for (const t of lt.targets) {
      const label = t.primary ? t.label : 'couche seule'
      if (houdini) {
        targets.push({ dcc: `Houdini : ${label}`, onClick: () => void openInHoudini(project, t.rel_path, item.name) })
      }
      if (maya) {
        targets.push({ dcc: `Maya : ${label} (aplati)`, onClick: () => void openInMaya(project, t.rel_path, item.name) })
        if (t.primary) {
          targets.push({ dcc: `Maya : ${label} (proxy USD, variantes)`, onClick: () => void openInMaya(project, t.rel_path, item.name, 'proxy') })
        }
      }
    }
    if (lt.legacy) {
      targets.push({ dcc: 'Ancien fichier : supprimer (backup)', onClick: () => void deleteLegacy(project, rel, item.name, onChanged) })
    } else {
      targets.push(...lopTargets)
    }
    return targets
  }
  if (houdini) {
    targets.push({ dcc: 'Houdini', onClick: () => void openInHoudini(project, rel, item.name) })
  }
  targets.push(...lopTargets)
  if (maya && MAYA_IMPORT_EXTS.has(ext)) {
    targets.push({ dcc: 'Maya', onClick: () => void openInMaya(project, rel, item.name) })
  }
  if (dccStatus['Nuke']?.connected && NUKE_IMPORT_EXTS.has(ext)) {
    targets.push({ dcc: 'Nuke', onClick: () => void openInNuke(project, rel, item.name) })
  }
  // Photoshop is external COM (no scan entry); offer it for raster/PSD files.
  if (PS_OPEN_EXTS.has(ext)) {
    targets.push({ dcc: 'Photoshop', onClick: () => void openInPhotoshop(project, rel, item.name) })
  }
  return targets
}
