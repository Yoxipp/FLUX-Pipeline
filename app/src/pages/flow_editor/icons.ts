// icons.ts — lucide icon name (from the node registry, `icon=`) -> component.
// A static table keeps tree-shaking; an unknown name falls back to the family icon.
// Canonical lucide 0.390.0 names only (checked in node_modules).

import {
  ArrowRightLeft, Boxes, Cable, Calculator, Cpu, Database, FileText, FolderPlus, KeyRound,
  Plug, Radio, Split, Terminal, Workflow, Zap, type LucideIcon,
} from 'lucide-react'
import { FAMILY_INFO } from './families'
import type { Family } from './types'

const ICONS: Record<string, LucideIcon> = {
  ArrowRightLeft, Boxes, Cable, Calculator, Cpu, Database, FileText, FolderPlus, KeyRound,
  Plug, Radio, Split, Terminal, Workflow, Zap,
}

export function iconFor(name: string | undefined, family: Family): LucideIcon {
  return (name && ICONS[name]) || ICONS[FAMILY_INFO[family].icon] || Workflow
}
