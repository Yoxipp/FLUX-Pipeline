// zbrushExportOptions.ts — declarative per-format export option schema for ZBrush.
//
// Same shape and renderer as mayaExportOptions / houdiniExportOptions: the
// Publisher renders these via <ExportOptions> in the right panel, and threads the
// chosen values to api.publishZBrush, which the bridge plugin maps onto ZBrush's
// export sliders (Tool:Export:* / FBX ExportImport plugin).
//
// Keys and defaults reproduce the previous hand-written ZBrush options EXACTLY, so
// moving them to the generic renderer never changes an existing publish:
//   OBJ: uvs, normals, materials, groups, flip_v, scope (default selected)
//   FBX: fbx_version, scope (default all), animation, materials
//   ZTL: no options.

import type { ExportOption } from './mayaExportOptions'

export type { ExportOption }

// ── OBJ — Tool:Export:* sliders ───────────────────────────────────────────────
const OBJ: ExportOption[] = [
  { key: 'uvs',       label: 'UVs',              type: 'bool', default: true,  tier: 'common' },
  { key: 'normals',   label: 'Normales',         type: 'bool', default: true,  tier: 'common' },
  { key: 'materials', label: 'Matériaux (.mtl)', type: 'bool', default: false, tier: 'common' },
  { key: 'groups',    label: 'Groupes subtools', type: 'bool', default: false, tier: 'common' },
  { key: 'scope', label: 'Scope', type: 'enum', default: 'selected', tier: 'common',
    choices: [
      { value: 'selected', label: 'Selected' },
      { value: 'visible',  label: 'Visible' },
      { value: 'all',      label: 'All' },
    ] },
  { key: 'flip_v', label: 'Flip V', type: 'bool', default: false, tier: 'advanced' },
]

// ── FBX — FBX ExportImport plugin ─────────────────────────────────────────────
const FBX: ExportOption[] = [
  { key: 'fbx_version', label: 'Version FBX', type: 'enum', default: '2019', tier: 'common',
    choices: [
      { value: '2019', label: '2019' },
      { value: '2020', label: '2020' },
      { value: '2022', label: '2022' },
    ] },
  { key: 'scope', label: 'Scope', type: 'enum', default: 'all', tier: 'common',
    choices: [
      { value: 'all',      label: 'All' },
      { value: 'selected', label: 'Selected' },
      { value: 'visible',  label: 'Visible' },
    ] },
  { key: 'animation', label: 'Animation', type: 'bool', default: false, tier: 'common' },
  { key: 'materials', label: 'Matériaux', type: 'bool', default: true,  tier: 'common' },
]

// Map an extension to its schema (.ztl has no export options).
export function zbrushSchemaForExt(ext: string): ExportOption[] {
  switch (ext.toLowerCase()) {
    case '.obj': return OBJ
    case '.fbx': return FBX
    default:     return []
  }
}

// Build the default value map for a format.
export function defaultZbrushOptions(ext: string): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const o of zbrushSchemaForExt(ext)) out[o.key] = o.default
  return out
}
