// usdPresetOptions.ts — options of each USD preset FLUX writes itself (2026-09-26,
// ADR 0034). One preset = one department, so only the options that make sense for it
// are shown: model never offers skeletons or materials, anim never offers UVs, etc.
// The values travel as `options` to POST /dcc/maya/export-usd (keys read by
// backend/dcc/maya/maya_usd_presets.py). "custom" is not here: Maya writes the file
// with every mayaUSDExport option (lib/mayaExportOptions.ts, USD schema).

import type { ExportOption } from './mayaExportOptions'

export type UsdPreset = 'model' | 'rig' | 'anim' | 'look'

const MODEL: ExportOption[] = [
  { key: 'uv',      label: 'UV',                     type: 'bool', default: true, tier: 'common' },
  { key: 'normals', label: 'Normales (hard edges)',  type: 'bool', default: true, tier: 'common',
    hint: 'Normales par face-vertex : les arêtes dures restent dures dans USD.' },
  { key: 'subdivision_scheme', label: 'Subdivision', type: 'enum', default: 'none', tier: 'common',
    choices: [{ value: 'none', label: 'Aucune (polys)' }, { value: 'catmullClark', label: 'Catmull-Clark' }] },
  { key: 'color_sets', label: 'Color sets', type: 'bool', default: false, tier: 'advanced' },
]

const RIG: ExportOption[] = [
  { key: 'rest_pose', label: 'Pose neutre', type: 'enum', default: 'bind', tier: 'common',
    choices: [
      { value: 'bind', label: 'Bind pose (skin)' },
      { value: 'zero_ctrls', label: 'Contrôleurs à 0' },
      { value: 'current', label: 'Image courante' },
    ] },
  { key: 'skin', label: 'Poids de skin (boneCapture)', type: 'bool', default: true, tier: 'common' },
  { key: 'max_influences', label: 'Influences max / point (0 = toutes)', type: 'int', default: 0, tier: 'advanced' },
  { key: 'weight_threshold', label: 'Poids minimum', type: 'float', default: 0.0001, tier: 'advanced' },
]

const ANIM: ExportOption[] = [
  { key: 'interpolation', label: 'Interpolation', type: 'enum', default: 'smooth', tier: 'common',
    choices: [{ value: 'smooth', label: 'Smooth (courbes)' }, { value: 'held', label: 'Step (clés tenues)' }] },
  { key: 'translate', label: 'Translations', type: 'enum', default: 'all', tier: 'common',
    choices: [
      { value: 'none', label: 'Aucune (rotations seules)' },
      { value: 'root', label: 'Root motion (auto)' },
      { value: 'all', label: 'Toutes les animées' },
    ] },
  { key: 'reduce', label: "Réduire les clés (sans changer l'anim)", type: 'bool', default: true, tier: 'advanced' },
]

const LOOK: ExportOption[] = []

export const USD_PRESET_SCHEMAS: Record<UsdPreset, ExportOption[]> = {
  model: MODEL, rig: RIG, anim: ANIM, look: LOOK,
}

// Asset / shot TYPE -> preset (the department FLUX writes for that task).
export function presetForTask(task: string, shot = false): UsdPreset | null {
  const t = task.toUpperCase()
  if (shot) return t === 'ANIM' ? 'anim' : null
  if (t === 'GEO') return 'model'
  if (t === 'RIG') return 'rig'
  if (t === 'ANIM') return 'anim'
  if (t === 'SHADING') return 'look'
  return null
}

export function defaultPresetOptions(): Record<UsdPreset, Record<string, unknown>> {
  const out = {} as Record<UsdPreset, Record<string, unknown>>
  for (const [k, schema] of Object.entries(USD_PRESET_SCHEMAS) as [UsdPreset, ExportOption[]][]) {
    out[k] = Object.fromEntries(schema.map(o => [o.key, o.default]))
  }
  return out
}

// The attributes each preset writes, as USD names them and as Houdini reads them
// (SideFX: SOP Import / USD Skin Import). `rename` = the artist may rename it in the
// file; the skin primvars are fixed (Houdini rebuilds boneCapture from exactly them).
export interface ExportedAttr {
  usd: string              // name in the USD file (default)
  houdini: string          // what it becomes once imported in Houdini SOPs
  what: string
  rename: boolean
  houdiniName?: string     // "Nomenclature Houdini" fills this (when renamable)
  key?: string             // key in options.renames (defaults to `usd`)
}

export function exportedAttrs(preset: UsdPreset, opts: Record<string, unknown>,
                              colorSets: string[] = []): ExportedAttr[] {
  if (preset === 'model') {
    const out: ExportedAttr[] = [
      { usd: 'points', houdini: 'P', what: 'positions', rename: false },
    ]
    if (opts.normals !== false) out.push({ usd: 'normals', houdini: 'N', what: 'normales par face-vertex', rename: false })
    if (opts.uv !== false) out.push({ usd: 'primvars:st', houdini: 'uv', what: 'UV', rename: true, houdiniName: 'uv', key: 'st' })
    if (opts.color_sets) {
      for (const cs of colorSets) {
        out.push({ usd: `primvars:${cs}`, houdini: cs, what: 'color set', rename: true, houdiniName: 'Cd', key: cs })
      }
    }
    return out
  }
  if (preset === 'rig') {
    const out: ExportedAttr[] = [
      { usd: 'Skeleton.joints', houdini: 'name (points du squelette)', what: 'joints', rename: false },
      { usd: 'Skeleton.restTransforms', houdini: 'transform (pose de repos)', what: 'pose neutre', rename: false },
    ]
    if (opts.skin !== false) {
      out.push({ usd: 'primvars:skel:jointIndices + jointWeights', houdini: 'boneCapture',
                 what: 'poids de skin (USD Skin Import / UsdSkel Character Import)', rename: false })
    }
    return out
  }
  if (preset === 'anim') {
    return [
      { usd: 'SkelAnimation.rotations', houdini: 'transform (joints animés)', what: 'rotations', rename: false },
      ...(opts.translate && opts.translate !== 'none'
        ? [{ usd: 'SkelAnimation.translations', houdini: 'P (joints)', what: 'translations', rename: false }]
        : []),
    ]
  }
  return [{ usd: 'material:binding', houdini: 'shop_materialpath', what: 'assignations', rename: false }]
}
