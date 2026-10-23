// icons.ts — lucide icon name (from the node registry, `icon=`) -> component.
// A static table keeps tree-shaking; an unknown name falls back to the family icon.
// Canonical lucide 0.390.0 names only (checked in node_modules). Every icon of the FLUX
// registry is listed (P6a: event, bridge, session, dcc nodes included).

import {
  Archive, ArrowDownUp, ArrowRightLeft, AtSign, Ban, Bell, Box, Boxes, Braces, Cable, Calculator, Calendar,
  CalendarClock, CalendarDays, CaseSensitive, Circle, CircleDashed, Clapperboard, Component, Copy, Cpu, Crosshair,
  Database, FileArchive, FileCode, FileInput, FileJson, FileOutput, FilePlus, FileSearch, FileText, Film, Flame,
  FolderInput, FolderKanban, FolderOpen, FolderPlus, FolderTree, Gauge, GitBranch, GitMerge, Globe, Hash, HeartPulse,
  History, Hourglass, ImageDown, Info, KeyRound, Layers, Link, List, ListChecks, ListFilter, ListOrdered, ListPlus,
  ListStart, ListTree, LogIn, LogOut, Mailbox, Merge, MousePointerClick, PackageCheck, PackagePlus, PackageSearch,
  Palette, PenLine, Pencil, Play, Plug, Radar, Radio, RefreshCcw, RefreshCw, Repeat, Repeat1, Replace, Rocket, Route,
  Save, SaveAll, Scale, ScanSearch, Scissors, ScrollText, Search, ShieldCheck, Shrink, SlidersHorizontal, Split,
  SquareFunction, SquareTerminal, Tags, Terminal, ToggleLeft, Trash2, Type, Variable, Video, Waypoints, Workflow,
  Zap, type LucideIcon,
} from 'lucide-react'
import { FAMILY_INFO } from './families'
import type { Family } from './types'

const ICONS: Record<string, LucideIcon> = {
  Archive, ArrowDownUp, ArrowRightLeft, AtSign, Ban, Bell, Box, Boxes, Braces, Cable, Calculator, Calendar,
  CalendarClock, CalendarDays, CaseSensitive, Circle, CircleDashed, Clapperboard, Component, Copy, Cpu, Crosshair,
  Database, FileArchive, FileCode, FileInput, FileJson, FileOutput, FilePlus, FileSearch, FileText, Film, Flame,
  FolderInput, FolderKanban, FolderOpen, FolderPlus, FolderTree, Gauge, GitBranch, GitMerge, Globe, Hash, HeartPulse,
  History, Hourglass, ImageDown, Info, KeyRound, Layers, Link, List, ListChecks, ListFilter, ListOrdered, ListPlus,
  ListStart, ListTree, LogIn, LogOut, Mailbox, Merge, MousePointerClick, PackageCheck, PackagePlus, PackageSearch,
  Palette, PenLine, Pencil, Play, Plug, Radar, Radio, RefreshCcw, RefreshCw, Repeat, Repeat1, Replace, Rocket, Route,
  Save, SaveAll, Scale, ScanSearch, Scissors, ScrollText, Search, ShieldCheck, Shrink, SlidersHorizontal, Split,
  SquareFunction, SquareTerminal, Tags, Terminal, ToggleLeft, Trash2, Type, Variable, Video, Waypoints, Workflow,
  Zap,
}

export function iconFor(name: string | undefined, family: Family): LucideIcon {
  return (name && ICONS[name]) || ICONS[FAMILY_INFO[family].icon] || Workflow
}
