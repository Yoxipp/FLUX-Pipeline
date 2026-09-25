// designerExportOptions.ts — export option schema for Substance 3D Designer.
//
// Designer publish is token-driven like Painter (class/task/name/instance from the
// composer); the shared format picker gives the map file format. The options below
// fill the typed fields of /dcc/designer/bridge/publish: what to publish (maps,
// cooked .sbsar, source .sbs), the graph output size and bit depth, and .tx conform.

import type { ExportOption } from './mayaExportOptions'

export type { ExportOption }

export const DESIGNER_OPTIONS: ExportOption[] = [
  { key: 'maps',  label: 'Maps des outputs', type: 'bool', default: true,  tier: 'common' },
  { key: 'sbsar', label: '.sbsar (cooke)',   type: 'bool', default: false, tier: 'common' },
  { key: 'sbs',   label: '.sbs (source)',    type: 'bool', default: false, tier: 'common',
    hint: 'La derniere version sauvee du package' },
  { key: 'size', label: 'Taille', type: 'enum', default: '', tier: 'common', dependsOn: 'maps',
    choices: [
      { value: '',     label: 'Taille du graph' },
      { value: '512',  label: '512' },
      { value: '1024', label: '1K (1024)' },
      { value: '2048', label: '2K (2048)' },
      { value: '4096', label: '4K (4096)' },
      { value: '8192', label: '8K (8192)' },
    ] },
  { key: 'bit_depth', label: 'Bit depth', type: 'enum', default: '', tier: 'common', dependsOn: 'maps',
    choices: [
      { value: '',    label: 'Format du graph' },
      { value: '8',   label: '8 bit' },
      { value: '16',  label: '16 bit' },
      { value: '16f', label: '16 bit float' },
      { value: '32f', label: '32 bit float' },
    ] },
  { key: 'conform_tx', label: 'Conform .tx (Karma)', type: 'bool', default: false, tier: 'common', dependsOn: 'maps' },
]

export function defaultDesignerOptions(): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const o of DESIGNER_OPTIONS) out[o.key] = o.default
  return out
}
