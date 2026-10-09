// version.ts — FLUX display version (x.x.xxx) for the running app.
//
// Single source of truth: package.json "fluxVersion", bumped by scripts/build.cjs together
// with "version" (semver 0.8.3, what app.getVersion() returns), backend APP_VERSION and
// scripts/flux_version.nsh. package.json ships inside app.asar, so it is read at runtime.
// Fallback: app.getVersion() normalised to x.x.xxx.

import { app } from 'electron'
import path from 'path'
import fs from 'fs'

export type Version = [number, number, number]

/** Parse "0.4.0" / "0.4.000" into [0, 4, 0], or null if not x.y.z. */
export function parseVersion(text: string): Version | null {
  const m = /^(\d+)\.(\d+)\.(\d+)$/.exec(String(text).trim())
  return m ? [Number(m[1]), Number(m[2]), Number(m[3])] : null
}

/** Negative if a < b, 0 if equal, positive if a > b. Numeric: 0.8.001 > 0.8.000 == 0.8.0. */
export function compareVersions(a: Version, b: Version): number {
  for (let i = 0; i < 3; i++) {
    if (a[i] !== b[i]) return a[i] - b[i]
  }
  return 0
}

/** [0, 8, 1] -> "0.8.001". */
export function formatVersion(v: Version): string {
  return `${v[0]}.${v[1]}.${String(v[2]).padStart(3, '0')}`
}

let cached: Version | null | undefined

/** Running FLUX version, numeric. fluxVersion wins over the semver "version". */
export function currentVersion(): Version | null {
  if (cached !== undefined) return cached
  let fromPkg: Version | null = null
  try {
    const pkg = JSON.parse(fs.readFileSync(path.join(app.getAppPath(), 'package.json'), 'utf8'))
    fromPkg = typeof pkg.fluxVersion === 'string' ? parseVersion(pkg.fluxVersion) : null
  } catch {
    fromPkg = null
  }
  cached = fromPkg ?? parseVersion(app.getVersion())
  return cached
}

/** Running FLUX version as x.x.xxx (ex: 0.8.003). */
export function displayVersion(): string {
  const v = currentVersion()
  return v ? formatVersion(v) : app.getVersion()
}
