// Folder Manager shared types and helpers, used by the page (Projects.tsx) and by
// each explorer view (ExplorerPane.tsx). B2 (2026-09-28): several views side by side.

import { createContext, useContext } from 'react'
import type { MutableRefObject } from 'react'
import type { DccStatusMap } from '../../types'

// ── Types ─────────────────────────────────────────────────────────────────────

export type NavLevel =
  | { kind: 'root' }
  | { kind: 'inside'; project: string; subpath: string[] }

// Tile size for the explorer grid. Bigger tiles = larger icons + more room for
// the label below. Persisted per-browser in localStorage.
export type TileSize = 'sm' | 'md' | 'lg'

export const TILE_SIZES: Record<TileSize, { col: number; folder: number; file: number; font: number; gap: number }> = {
  sm: { col: 64,  folder: 30, file: 26, font: 9,  gap: 3 },
  md: { col: 80,  folder: 40, file: 34, font: 10, gap: 4 },
  lg: { col: 116, folder: 58, file: 50, font: 12, gap: 6 },
}

export interface ExplorerItem { name: string; isDir: boolean; legacy?: boolean }

export const USD_EXTS = new Set(['.usd', '.usda', '.usdc', '.usdz'])

// FR/EN pick for code outside React (toasts, menu builders). LanguageProvider keeps
// <html lang> in sync with the UI language, so this follows useTr() without a hook.
export const trNow = (fr: string, en: string): string =>
  (typeof document !== 'undefined' && document.documentElement.lang === 'en' ? en : fr)

export interface SavedItem {
  label:   string
  project: string
  subpath: string[]  // subpath within project EXCLUDING item name; [] = project root
  isDir:   boolean
}

export interface FindResult {
  label:   string
  pathStr: string
  project: string
  subpath: string[]
  isDir:   boolean
}

// Clipboard for copy/cut → paste. Scoped to a project + source folder.
export interface Clip { op: 'copy' | 'cut'; project: string; subpath: string[]; items: ExplorerItem[] }

// Reversible file operations, for Ctrl+Z. One user action pushes one UndoOp
// (which may bundle several items). Delete is destructive → never recorded.
export type UndoAction =
  | { kind: 'move';   project: string; fromSub: string[]; toSub: string[]; name: string }
  | { kind: 'rename'; project: string; sub: string[]; oldName: string; newName: string }
  | { kind: 'copy';   project: string; sub: string[]; name: string }   // undo = delete the created copy
export interface UndoOp { label: string; actions: UndoAction[] }

// Items being dragged, shared by every view so a drop can land in another one.
export interface DragPayload {
  paneId:  number
  project: string
  subpath: string[]
  names:   string[]
  locked:  Set<string>   // locked names: copied, never moved
}

// Source / destination of a move or a copy (drag & drop, paste, "Déplacer").
export interface TransferSource { project: string; subpath: string[]; names: string[]; locked?: Set<string> }
export interface TransferDest   { project: string; subpath: string[] }

// Views layout, like Houdini's viewport layouts.
export type PaneLayout = 'single' | 'stacked' | 'side' | 'quad'
export const PANE_COUNT: Record<PaneLayout, number> = { single: 1, stacked: 2, side: 2, quad: 4 }

// What a view reports to the page (right panel, active project, presets).
export interface PaneReport {
  nav:           NavLevel
  selectedNames: Set<string>
  items:         ExplorerItem[]
}

// ── Saved-item helpers ────────────────────────────────────────────────────────

export function savedKey(s: SavedItem): string {
  return `${s.project}||${s.subpath.join('/')}||${s.label}`
}

export function itemKey(project: string, subpath: string[], label: string): string {
  return `${project}||${subpath.join('/')}||${label}`
}

export function makeSavedItem(item: ExplorerItem, nav: NavLevel): SavedItem {
  if (nav.kind === 'root') {
    return { label: item.name, project: item.name, subpath: [], isDir: true }
  }
  return { label: item.name, project: nav.project, subpath: nav.subpath, isDir: item.isDir }
}

export function currentItemKey(item: ExplorerItem, nav: NavLevel): string {
  if (nav.kind === 'root') return itemKey(item.name, [], item.name)
  return itemKey(nav.project, nav.subpath, item.name)
}

export function navigateTargetFor(s: SavedItem): NavLevel {
  // Root-level project: project === label && subpath empty
  if (s.project === s.label && s.subpath.length === 0) {
    return { kind: 'inside', project: s.project, subpath: [] }
  }
  if (s.isDir) {
    return { kind: 'inside', project: s.project, subpath: [...s.subpath, s.label] }
  }
  return { kind: 'inside', project: s.project, subpath: s.subpath }
}

// ── Path helpers ──────────────────────────────────────────────────────────────

export function resolveOpenPath(absPath: string, workspace: string): NavLevel | null {
  const norm = (p: string) => p.replace(/\\/g, '/').replace(/\/+$/, '')
  // Projects live at FLUX_ROOT/DOSSIER_PROJETS/<project>/...
  const ws   = norm(workspace) + '/DOSSIER_PROJETS'
  const ap   = norm(absPath)
  if (!ap.toLowerCase().startsWith(ws.toLowerCase())) return null
  const relative = ap.slice(ws.length).replace(/^\//, '')
  const parts    = relative.split('/').filter(Boolean)
  if (parts.length === 0) return null
  const [project, ...subpath] = parts
  return { kind: 'inside', project, subpath }
}

export function sameNav(a: NavLevel, b: NavLevel): boolean {
  if (a.kind !== b.kind) return false
  if (a.kind === 'root' || b.kind === 'root') return true
  return a.project === b.project && a.subpath.join('/') === b.subpath.join('/')
}

// "name.ext" → "name (2).ext" when taken in the destination folder.
export function uniqueName(base: string, existing: Set<string>): string {
  if (!existing.has(base)) return base
  const dot  = base.lastIndexOf('.')
  const stem = dot > 0 ? base.slice(0, dot) : base
  const ext  = dot > 0 ? base.slice(dot) : ''
  let n = 2
  while (existing.has(`${stem} (${n})${ext}`)) n++
  return `${stem} (${n})${ext}`
}

// ── Page-wide state shared by the views ───────────────────────────────────────

export interface FolderManagerShared {
  workspace:     string | null | undefined
  tileSize:      TileSize
  dccStatus:     DccStatusMap
  favorites:     SavedItem[]
  archived:      SavedItem[]
  toggleFavorite: (item: ExplorerItem, nav: NavLevel) => void
  toggleArchived: (item: ExplorerItem, nav: NavLevel) => void
  addToRecents:   (item: ExplorerItem, nav: NavLevel) => void
  forgetSaved:    (keys: string[], alsoArchived?: boolean) => void
  renameSaved:    (oldKey: string, newName: string) => void
  clipboard:     Clip | null
  setClipboard:  (c: Clip | null) => void
  pushUndo:      (op: UndoOp) => void
  undoLast:      () => Promise<void>
  // Bumped after any write on disk: every view reloads its folder.
  fsTick:        number
  bumpFs:        () => void
  // "Setup files" box: show _flux_setup/ and the project's FLUX JSON (off by default).
  showSetup:     boolean
  dragRef:       MutableRefObject<DragPayload | null>
  transfer:      (src: TransferSource, dest: TransferDest, op: 'move' | 'copy') => Promise<number>
}

export const FolderManagerContext = createContext<FolderManagerShared | null>(null)

export function useFolderManager(): FolderManagerShared {
  const ctx = useContext(FolderManagerContext)
  if (!ctx) throw new Error('useFolderManager outside the Folder Manager')
  return ctx
}
