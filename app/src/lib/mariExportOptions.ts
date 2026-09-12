// mariExportOptions.ts — export option schema for Mari (V6 B7).
//
// Like Painter, Mari publish is token-driven and uses the shared format picker as
// the channel file_format. Mari's /dcc/mari/publish has no preset or bit depth, so
// the only option is whether to chain .tx conform (texture_conform) after export.

import type { ExportOption } from './mayaExportOptions'

export type { ExportOption }

export const MARI_OPTIONS: ExportOption[] = [
  { key: 'conform_tx', label: 'Conform .tx (Karma)', type: 'bool', default: false, tier: 'common' },
]

// Build the default value map.
export function defaultMariOptions(): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const o of MARI_OPTIONS) out[o.key] = o.default
  return out
}
