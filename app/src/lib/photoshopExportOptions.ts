// photoshopExportOptions.ts — declarative per-format export option schema for
// Photoshop (V6 B6). Same shape and renderer as the other DCC option libs.
//
// Photoshop is driven from outside over COM (photoshop-python-api). The backend
// (photoshop_export.save_options_for_ext) only carries through save-option fields
// that are real for the format, so the schema here exposes just those: JPEG quality
// and PSB maximize-compatibility. PSD / PNG / TIFF / TGA save with native defaults
// and take no options. EXR is intentionally absent: Photoshop cannot write it
// natively, so it is not in the Photoshop format list.

import type { ExportOption } from './mayaExportOptions'

export type { ExportOption }

// ── JPEG — quality 1..12 ──────────────────────────────────────────────────────
const JPG: ExportOption[] = [
  { key: 'quality', label: 'Qualité (1-12)', type: 'int', default: 12, tier: 'common' },
]

// ── PSB — large-document format ───────────────────────────────────────────────
const PSB: ExportOption[] = [
  { key: 'maximizeCompatibility', label: 'Compatibilité maximale', type: 'bool', default: true, tier: 'common' },
]

// Map an extension to its schema (formats without a real field return []).
export function photoshopSchemaForExt(ext: string): ExportOption[] {
  switch (ext.toLowerCase()) {
    case '.jpg':
    case '.jpeg': return JPG
    case '.psb':  return PSB
    default:      return []
  }
}

// Build the default value map for a format.
export function defaultPhotoshopOptions(ext: string): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const o of photoshopSchemaForExt(ext)) out[o.key] = o.default
  return out
}
