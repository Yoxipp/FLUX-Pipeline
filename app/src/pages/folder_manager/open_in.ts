// "Open in" targets of the Folder Manager right-click menu: every currently-CONNECTED
// DCC that can import the clicked file. Plain functions (no view state) so every
// explorer view shares them.

import { toast } from 'sonner'
import { api } from '../../api/client'
import type { LoadTargets } from '../../api/client'
import { readActiveInstancePort } from '../../hooks/useActiveInstances'
import type { DccStatusMap } from '../../types'
import { USD_EXTS, trNow } from './shared'
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
// Marvelous import_api: meshes, its own project / garment / avatar / fabric files, DXF patterns.
export const MARVELOUS_IMPORT_EXTS = new Set(['.obj', '.fbx', '.abc', '.glb', '.gltf', '.zprj', '.zpac', '.avt', '.zfab', '.dxf'])

const isOffline = (msg: string) => /urlopen|refused|connect|actively refused|WinError/i.test(msg)
const errMsg = (e: unknown) => (e instanceof Error ? e.message : trNow('Erreur inconnue', 'Unknown error'))

async function openInHoudini(project: string, rel_path: string, name: string) {
  // DCC imports can take a while (big USD stages): keep a spinner toast until done.
  const id = toast.loading(trNow(`Import de ${name} dans Houdini…`, `Importing ${name} into Houdini…`))
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
      toast.success(trNow(`${name} : path mis à jour sur le node sélectionné`, `${name}: path updated on the selected node`), { id })
    } else if (res.result?.resolved_path) {
      toast.success(trNow(`${name} importé dans Houdini`, `${name} imported into Houdini`), { id })
    } else {
      toast.warning(trNow(`Node créé mais fichier non résolu pour ${name} : clique ↺ Resolve dans le node`, `Node created but file not resolved for ${name}: click ↺ Resolve in the node`), { id })
    }
  } catch (e) {
    const msg = errMsg(e)
    toast.error(isOffline(msg)
      ? trNow('Houdini non connecté : lance le serveur FLUX dans Houdini', 'Houdini not connected: start the FLUX server in Houdini')
      : trNow(`Import Houdini échoué : ${msg}`, `Houdini import failed: ${msg}`), { id })
  }
}

async function importHoudiniLop(project: string, rel_path: string, name: string, mode: LopMode) {
  const label = LOP_MODE_LABELS[mode]
  const id = toast.loading(trNow(`${label} de ${name} dans Houdini…`, `${label} of ${name} in Houdini…`))
  try {
    const res = await api.houdiniImportLop(project, rel_path, mode)
    const r = res.result
    const added = r?.mode?.endsWith('_added')
    toast.success(added
      ? trNow(`${name} ajouté à ${r?.node_path} (entrée ${r?.entry})`, `${name} added to ${r?.node_path} (entry ${r?.entry})`)
      : trNow(`${name} : ${label} LOP créé (${r?.node_path})`, `${name}: ${label} LOP created (${r?.node_path})`), { id })
  } catch (e) {
    const msg = errMsg(e)
    toast.error(isOffline(msg)
      ? trNow('Houdini non connecté : lance le serveur FLUX dans Houdini', 'Houdini not connected: start the FLUX server in Houdini')
      : trNow(`Import LOP échoué : ${msg}`, `LOP import failed: ${msg}`), { id })
  }
}

async function openInMaya(project: string, rel_path: string, name: string, mode: 'import' | 'proxy' = 'import') {
  const id = toast.loading(trNow(`Import de ${name} dans Maya…`, `Importing ${name} into Maya…`))
  try {
    await api.importFileInMaya(project, rel_path, readActiveInstancePort('Maya') ?? undefined, mode)
    toast.success(trNow(`${name} importé dans Maya`, `${name} imported into Maya`), { id })
  } catch (e) {
    const msg = errMsg(e)
    toast.error(msg.includes('répond pas')
      ? trNow('Maya non connecté : ouvre Maya avec le bridge FLUX actif (commandPort 7001)', 'Maya not connected: open Maya with the FLUX bridge active (commandPort 7001)')
      : trNow(`Import Maya échoué : ${msg}`, `Maya import failed: ${msg}`), { id })
  }
}

async function openInNuke(project: string, rel_path: string, name: string) {
  const id = toast.loading(trNow(`Import de ${name} dans Nuke…`, `Importing ${name} into Nuke…`))
  try {
    await api.nukeImportPath(project, rel_path)
    toast.success(`${name} → Nuke (Read)`, { id })
  } catch (e) {
    toast.error(trNow(`Import Nuke échoué : ${errMsg(e)}`, `Nuke import failed: ${errMsg(e)}`), { id })
  }
}

export async function openInMarvelous(project: string, rel_path: string, name: string) {
  const id = toast.loading(trNow(`Import de ${name} dans Marvelous…`, `Importing ${name} into Marvelous…`))
  try {
    await api.importInMarvelous(project, rel_path)
    toast.success(trNow(`${name} importé dans Marvelous`, `${name} imported into Marvelous`), { id })
  } catch (e) {
    toast.error(trNow(`Import Marvelous échoué : ${errMsg(e)}`, `Marvelous import failed: ${errMsg(e)}`), { id })
  }
}

async function openInPhotoshop(project: string, rel_path: string, name: string) {
  const id = toast.loading(trNow(`Ouverture de ${name} dans Photoshop…`, `Opening ${name} in Photoshop…`))
  try {
    await api.photoshopOpen(project, rel_path)
    toast.success(trNow(`${name} ouvert dans Photoshop`, `${name} opened in Photoshop`), { id })
  } catch (e) {
    toast.error(trNow(`Ouverture Photoshop échouée : ${errMsg(e)}`, `Photoshop open failed: ${errMsg(e)}`), { id })
  }
}

async function deleteLegacy(project: string, rel_path: string, name: string, onDone: () => void) {
  try {
    const res = await api.deleteUsdLegacy(project, rel_path)
    toast.success(trNow(`${name} deplace dans le backup du projet`, `${name} moved to the project backup`), { description: res.backup })
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
      const label = t.primary ? t.label : trNow('couche seule', 'layer only')
      if (houdini) {
        targets.push({ dcc: `Houdini : ${label}`, onClick: () => void openInHoudini(project, t.rel_path, item.name) })
      }
      if (maya) {
        targets.push({ dcc: trNow(`Maya : ${label} (aplati)`, `Maya: ${label} (flattened)`), onClick: () => void openInMaya(project, t.rel_path, item.name) })
        if (t.primary) {
          targets.push({ dcc: trNow(`Maya : ${label} (proxy USD, variantes)`, `Maya: ${label} (USD proxy, variants)`), onClick: () => void openInMaya(project, t.rel_path, item.name, 'proxy') })
        }
      }
    }
    if (lt.legacy) {
      targets.push({ dcc: trNow('Ancien fichier : supprimer (backup)', 'Old file: delete (backup)'), onClick: () => void deleteLegacy(project, rel, item.name, onChanged) })
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
  if (dccStatus['Marvelous']?.connected && MARVELOUS_IMPORT_EXTS.has(ext)) {
    targets.push({ dcc: 'Marvelous', onClick: () => void openInMarvelous(project, rel, item.name) })
  }
  // Photoshop is external COM (no scan entry); offer it for raster/PSD files.
  if (PS_OPEN_EXTS.has(ext)) {
    targets.push({ dcc: 'Photoshop', onClick: () => void openInPhotoshop(project, rel, item.name) })
  }
  return targets
}
