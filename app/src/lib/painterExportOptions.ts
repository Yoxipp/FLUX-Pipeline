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
    ] },
  { key: 'bit_depth', label: 'Bit depth', type: 'enum', default: '8', tier: 'common',
    choices: [
      // Painter bitDepth values: 8, 16, 16f, 32f (a plain "32" is not one of them).
      { value: '8',   label: '8 bit' },
      { value: '16',  label: '16 bit' },
      { value: '16f', label: '16 bit float' },
      { value: '32f', label: '32 bit float' },
    ] },
  { key: 'size', label: 'Taille', type: 'enum', default: '', tier: 'common',
    choices: [
      { value: '',     label: 'Taille du texture set' },
      { value: '512',  label: '512' },
      { value: '1024', label: '1K (1024)' },
      { value: '2048', label: '2K (2048)' },
      { value: '4096', label: '4K (4096)' },
      { value: '8192', label: '8K (8192)' },
    ] },
  { key: 'padding', label: 'Dilatation (padding)', type: 'enum', default: 'infinite', tier: 'advanced',
    choices: [
      { value: 'infinite',    label: 'Infinie' },
      { value: 'passthrough', label: 'Aucune' },
      { value: 'transparent', label: 'Transparente' },
      { value: 'color',       label: 'Couleur' },
      { value: 'diffusion',   label: 'Diffusion' },
    ] },
  { key: 'dilation', label: 'Distance de dilatation (px)', type: 'int', default: 16, tier: 'advanced',
    hint: 'Pour Transparente, Couleur et Diffusion' },
  { key: 'conform_tx', label: 'Conform .tx (Karma)', type: 'bool', default: true, tier: 'common' },
]

// Build the default value map.
export function defaultPainterOptions(): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const o of PAINTER_OPTIONS) out[o.key] = o.default
  return out
}
