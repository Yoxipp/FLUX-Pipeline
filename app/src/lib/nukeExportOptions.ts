// nukeExportOptions.ts — declarative per-format export option schema for Nuke.
//
// Same shape and renderer as mayaExportOptions / zbrushExportOptions: the Publisher
// renders these via <ExportOptions> in the right panel and threads the chosen values
// to api.publishNuke. The backend (nuke_publish.build_write_export_code) applies each
// key straight onto the temporary Write node's knob, so the KEYS here are the real
// Nuke Write knob names (datatype, compression...). Unknown knobs are skipped in
// Nuke, so a value that does not exist on a given version never aborts the render.
//
// "colorspace" is handled apart: it is a separate argument of publish_from_nuke
// (project default = "color_picking"), so the Publisher pulls it out of the values
// map and sends it as a top-level field. It still lives in the schema so the user
// can pick it like any other option.
//
// .mov has no options here: its codec knob name varies a lot across Nuke versions,
// so we leave it at the node default rather than show controls that may not apply.
// .nk saves the whole comp (scriptSaveAs) and takes no options either.

import type { ExportOption } from './mayaExportOptions'

export type { ExportOption }

// Colorspaces offered for every rendered format. Defaults to the project's Write
// colorspace (see .nuke/init.py). "colorspace" is extracted to a top-level payload
// field by the Publisher, not passed as a Write knob.
const COLORSPACE: ExportOption = {
  key: 'colorspace', label: 'Colorspace', type: 'enum', default: 'color_picking', tier: 'common',
  choices: [
    { value: 'color_picking', label: 'color_picking (défaut projet)' },
    { value: 'rendering',     label: 'rendering' },
    { value: 'scene_linear',  label: 'scene_linear' },
    { value: 'raw',           label: 'raw' },
  ],
}

// ── EXR — Write knobs: datatype, compression, autocrop ────────────────────────
const EXR: ExportOption[] = [
  COLORSPACE,
  { key: 'datatype', label: 'Profondeur', type: 'enum', default: '32 bit float', tier: 'common',
    choices: [
      { value: '16 bit half',  label: '16 bit half' },
      { value: '32 bit float', label: '32 bit float' },
    ] },
  { key: 'compression', label: 'Compression', type: 'enum', default: 'Zip (16 scanlines)', tier: 'common',
    choices: [
      { value: 'none',                     label: 'none' },
      { value: 'Zip (1 scanline)',         label: 'Zip (1 scanline)' },
      { value: 'Zip (16 scanlines)',       label: 'Zip (16 scanlines)' },
      { value: 'PIZ Wavelet (32 scanlines)', label: 'PIZ' },
      { value: 'RLE',                      label: 'RLE' },
      { value: 'DWAA',                     label: 'DWAA' },
      { value: 'DWAB',                     label: 'DWAB' },
    ] },
  { key: 'autocrop', label: 'Autocrop', type: 'bool', default: false, tier: 'advanced' },
]

// ── DPX — Write knobs: datatype, bigEndian, transfer ──────────────────────────
const DPX: ExportOption[] = [
  COLORSPACE,
  { key: 'datatype', label: 'Profondeur', type: 'enum', default: '10 bit', tier: 'common',
    choices: [
      { value: '8 bit',  label: '8 bit' },
      { value: '10 bit', label: '10 bit' },
      { value: '12 bit', label: '12 bit' },
      { value: '16 bit', label: '16 bit' },
    ] },
  { key: 'bigEndian', label: 'Big endian', type: 'bool', default: false, tier: 'advanced' },
]

// ── TIFF — Write knobs: datatype, compression ─────────────────────────────────
const TIF: ExportOption[] = [
  COLORSPACE,
  { key: 'datatype', label: 'Profondeur', type: 'enum', default: '16 bit', tier: 'common',
    choices: [
      { value: '8 bit',        label: '8 bit' },
      { value: '16 bit',       label: '16 bit' },
      { value: '32 bit float', label: '32 bit float' },
    ] },
  { key: 'compression', label: 'Compression', type: 'enum', default: 'Deflate', tier: 'common',
    choices: [
      { value: 'none',     label: 'none' },
      { value: 'PackBits', label: 'PackBits' },
      { value: 'LZW',      label: 'LZW' },
      { value: 'Deflate',  label: 'Deflate' },
    ] },
]

// ── PNG — Write knobs: datatype ───────────────────────────────────────────────
const PNG: ExportOption[] = [
  COLORSPACE,
  { key: 'datatype', label: 'Profondeur', type: 'enum', default: '8 bit', tier: 'common',
    choices: [
      { value: '8 bit',  label: '8 bit' },
      { value: '16 bit', label: '16 bit' },
    ] },
]

// ── MOV — colorspace only (codec knob name is version-specific) ───────────────
const MOV: ExportOption[] = [COLORSPACE]

// Map an extension to its schema (.nk saves the whole comp, no options).
export function nukeSchemaForExt(ext: string): ExportOption[] {
  switch (ext.toLowerCase()) {
    case '.exr': return EXR
    case '.dpx': return DPX
    case '.tif': return TIF
    case '.png': return PNG
    case '.mov': return MOV
    default:     return []
  }
}

// Build the default value map for a format.
export function defaultNukeOptions(ext: string): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const o of nukeSchemaForExt(ext)) out[o.key] = o.default
  return out
}
