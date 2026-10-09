// updater.ts — launch-time check for a newer FLUX installer in <FLUX_ROOT>/FLUX_UPDATE.
//
// The team shares installers by dropping FLUX-Setup-x.x.xxx.exe into the workspace's
// FLUX_UPDATE folder. At launch, if the highest one is newer than the running app,
// FLUX asks the user whether to update. Yes: the installer is started detached and
// FLUX quits (the NSIS installer needs the app closed). No: FLUX starts normally and
// asks again on the next launch.
//
// Implicit coupling with the backend (keep in sync):
//   * config.json location  -> backend/core/paths.py get_config_json_path()
//   * "FLUX_UPDATE" dir name -> backend/core/constants.py FLUX_ROOT_DIRS
//   * installer file name   -> scripts/electron-builder.yml nsis.artifactName (+ build.cjs)
// Read directly here instead of through the API: the backend takes seconds to start
// and the check must run before it.

import { app, dialog, type NativeImage } from 'electron'
import { spawn } from 'child_process'
import path from 'path'
import fs from 'fs'
import { compareVersions, currentVersion, displayVersion, formatVersion, parseVersion, type Version } from './version'

const UPDATE_DIR_NAME = 'FLUX_UPDATE'
const INSTALLER_RE = /^FLUX-Setup-(\d+)\.(\d+)\.(\d+)\.exe$/i
// A workspace on OneDrive or a network share can be slow or offline: never let the
// check delay FLUX opening for more than this.
const LIST_TIMEOUT_MS = 3_000

// Version helpers live in version.ts (shared with the renderer IPC); re-exported here.
export { parseVersion, compareVersions, formatVersion, type Version }

export interface InstallerCandidate {
  path: string
  version: Version
  label: string   // display form x.x.xxx
}

/** Highest-versioned FLUX installer among *fileNames* (in *dir*), or null. */
export function pickLatestInstaller(dir: string, fileNames: string[]): InstallerCandidate | null {
  let best: InstallerCandidate | null = null
  for (const name of fileNames) {
    const m = INSTALLER_RE.exec(name)
    if (!m) continue
    const version: Version = [Number(m[1]), Number(m[2]), Number(m[3])]
    if (!best || compareVersions(version, best.version) > 0) {
      best = { path: path.join(dir, name), version, label: formatVersion(version) }
    }
  }
  return best
}

/** Same location as backend/core/paths.py get_config_json_path(). */
function configJsonPath(): string {
  if (app.isPackaged) return path.join(app.getPath('appData'), 'FluxPipeline', 'config.json')
  return path.join(__dirname, '..', 'config.json')   // dev: project root
}

function readWorkspace(): string | null {
  try {
    const data = JSON.parse(fs.readFileSync(configJsonPath(), 'utf8'))
    return typeof data.workspace === 'string' && data.workspace ? data.workspace : null
  } catch {
    return null   // first launch (no config yet) or unreadable: nothing to check
  }
}

async function listWithTimeout(dir: string): Promise<string[]> {
  const timeout = new Promise<string[]>((resolve) => setTimeout(() => resolve([]), LIST_TIMEOUT_MS))
  const listing = fs.promises.readdir(dir).catch(() => [] as string[])
  return Promise.race([listing, timeout])
}

/** Return the newer installer available in FLUX_UPDATE, or null. Never throws. */
export async function findNewerInstaller(): Promise<InstallerCandidate | null> {
  const current = currentVersion()
  const workspace = readWorkspace()
  if (!current || !workspace) return null
  const dir = path.join(workspace, UPDATE_DIR_NAME)
  const latest = pickLatestInstaller(dir, await listWithTimeout(dir))
  return latest && compareVersions(latest.version, current) > 0 ? latest : null
}

/**
 * Ask the user to update when a newer installer is in FLUX_UPDATE.
 * Resolves true when the installer was started: the caller must quit FLUX.
 */
export async function promptUpdateAtLaunch(icon?: NativeImage): Promise<boolean> {
  // Dev runs from sources: no installer to replace them, unless forced for testing.
  if (!app.isPackaged && process.env.FLUX_UPDATE_CHECK !== '1') return false

  let candidate: InstallerCandidate | null = null
  try {
    candidate = await findNewerInstaller()
  } catch (err) {
    console.warn('[Update] check failed:', err)
    return false
  }
  if (!candidate) return false

  const { response } = await dialog.showMessageBox({
    type: 'info',
    icon: icon && !icon.isEmpty() ? icon : undefined,
    title: 'Mise a jour FLUX',
    message: `Une nouvelle version de FLUX est disponible : ${candidate.label}`,
    detail: `Version installee : ${displayVersion()}\n\n`
      + 'Mettre a jour ferme FLUX et lance l\'installeur. '
      + 'Vos preferences et projets ne sont pas touches.',
    buttons: ['Mettre a jour', 'Plus tard'],
    defaultId: 0,
    cancelId: 1,
    noLink: true,
  })
  if (response !== 0) return false

  try {
    const child = spawn(candidate.path, [], { detached: true, stdio: 'ignore' })
    // Surface a launch failure (file removed, blocked by antivirus) instead of
    // quitting FLUX with nothing started.
    await new Promise<void>((resolve, reject) => {
      child.once('error', reject)
      child.once('spawn', () => resolve())
    })
    child.unref()
    return true
  } catch (err) {
    console.error('[Update] installer launch failed:', err)
    await dialog.showMessageBox({
      type: 'error',
      title: 'Mise a jour FLUX',
      message: 'Impossible de lancer l\'installeur.',
      detail: `${candidate.path}\n\n${String(err)}\n\nFLUX demarre avec la version actuelle.`,
      noLink: true,
    })
    return false
  }
}
