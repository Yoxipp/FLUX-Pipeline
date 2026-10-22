// families.ts — the 10 node families of the Flows editor (03_EDITEUR §2, 02_NODES §1).
// One flat colour (CSS variable --fam-<family>, globals.css) and one lucide icon per family.

import type { Family } from './types'

export const FAMILIES: Family[] = [
  'event', 'data', 'logic', 'operator', 'action', 'flux', 'session', 'dcc', 'bridge', 'subflow',
]

export interface FamilyInfo {
  color: string       // CSS value, e.g. "var(--fam-event)"
  icon:  string       // lucide name (resolved by icons.ts)
  fr:    string
  en:    string
}

export const FAMILY_INFO: Record<Family, FamilyInfo> = {
  event:    { color: 'var(--fam-event)',    icon: 'Zap',        fr: 'Evenements', en: 'Events' },
  data:     { color: 'var(--fam-data)',     icon: 'Database',   fr: 'Data',       en: 'Data' },
  logic:    { color: 'var(--fam-logic)',    icon: 'Split',      fr: 'Logique',    en: 'Logic' },
  operator: { color: 'var(--fam-operator)', icon: 'Calculator', fr: 'Operateurs', en: 'Operators' },
  action:   { color: 'var(--fam-action)',   icon: 'Terminal',   fr: 'Actions',    en: 'Actions' },
  flux:     { color: 'var(--fam-flux)',     icon: 'Workflow',   fr: 'FLUX',       en: 'FLUX' },
  session:  { color: 'var(--fam-session)',  icon: 'Plug',       fr: 'Instances',  en: 'Instances' },
  dcc:      { color: 'var(--fam-dcc)',      icon: 'Cpu',        fr: 'DCC',        en: 'DCC' },
  bridge:   { color: 'var(--fam-bridge)',   icon: 'Cable',      fr: 'Bridges',    en: 'Bridges' },
  subflow:  { color: 'var(--fam-subflow)',  icon: 'Boxes',      fr: 'Sous-flow',  en: 'Subflow' },
}

// Header fill of a node: the family colour, faint, over the panel colour.
export const familyHeaderBg = (f: Family): string =>
  `color-mix(in oklch, ${FAMILY_INFO[f].color} 16%, var(--paper-2))`
