// painterExportOptions.ts — export option schema for Substance 3D Painter (V6 B2).
//
// Painter publish is token-driven (class/task/name/instance from the composer) and
// uses the shared format picker as the map file_format. The options below fill the
// remaining typed fields of /dcc/substance/publish: the export preset, the bit
// depth, and whether to chain .tx conform (texture_conform) after export.
//
// The preset name must exist in the installed Painter; the common shipping presets
// are offered. conform_tx chains the existing OpenImageIO .tx conform so Karma stops
// re-mipping at render time (see memory flux-v5-texture-conform-t0).

import type { ExportOption } from './mayaExportOptions'

export type { ExportOption }

export const PAINTER_OPTIONS: ExportOption[] = [
  { key: 'preset', label: 'Export preset', type: 'enum', default: 'PBR Metallic Roughness', tier: 'common',
    choices: [
      { value: 'PBR Metallic Roughness',            label: 'PBR Metallic Roughness' },
      { value: 'PBR Specular Glossiness',           label: 'PBR Specular Glossiness' },
      { value: 'Arnold (AiStandard)',               label: 'Arnold (AiStandard)' },
      { value: 'Unreal Engine 4 (Packed)',          label: 'Unreal Engine 4 (Packed)' },
      { value: 'USD Preview Surface Metallic',      label: 'USD Preview Surface' },
    ] },
  { key: 'bit_depth', label: 'Bit depth', type: 'enum', default: '8', tier: 'common',
    choices: [
      { value: '8',  label: '8 bit' },
      { value: '16', label: '16 bit' },
      { value: '32', label: '32 bit' },
    ] },
  { key: 'conform_tx', label: 'Conform .tx (Karma)', type: 'bool', default: false, tier: 'common' },
]

// Build the default value map.
export function defaultPainterOptions(): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const o of PAINTER_OPTIONS) out[o.key] = o.default
  return out
}
