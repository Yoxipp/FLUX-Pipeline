// marvelousExportOptions.ts — export option schema for Marvelous Designer.
//
// The format comes from the shared picker (.abc / .obj / .fbx / .usd / .glb / .zprj);
// these options go to the bridge as ImportExportOption fields (only the ones the
// installed Marvelous knows are applied) plus "also publish the .zprj source".

import type { ExportOption } from './mayaExportOptions'

export type { ExportOption }

export const MARVELOUS_OPTIONS: ExportOption[] = [
  { key: 'garment',       label: 'Vetements',          type: 'bool',  default: true,  tier: 'common' },
  { key: 'avatar',        label: 'Avatar',             type: 'bool',  default: false, tier: 'common' },
  { key: 'single_object', label: 'Un seul objet',      type: 'bool',  default: false, tier: 'common' },
  { key: 'thick',         label: 'Epaisseur',          type: 'bool',  default: false, tier: 'common' },
  { key: 'unified_uv',    label: 'UV unifiees',        type: 'bool',  default: false, tier: 'advanced' },
  { key: 'scale',         label: 'Echelle',            type: 'float', default: 1.0,   tier: 'advanced',
    hint: 'Multiplie les unites exportees (cm par defaut dans Marvelous)' },
  { key: 'with_zprj',     label: 'Publier aussi le .zprj', type: 'bool', default: true, tier: 'common' },
]

export function defaultMarvelousOptions(): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const o of MARVELOUS_OPTIONS) out[o.key] = o.default
  return out
}
