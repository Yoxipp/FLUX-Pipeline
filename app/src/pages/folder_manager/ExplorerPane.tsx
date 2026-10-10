// ExplorerPane — one explorer view of the Folder Manager (B2, 2026-09-28).
//
// A view owns its navigation (history, path bar, search), its folder listing, its
// selection, its right-click menu and its item modals. Everything else (saved lists,
// clipboard, undo, drag payload, cross-view refresh) comes from FolderManagerContext,
// so the page can show 1, 2 or 4 views, each browsing on its own, and items can be
// dragged from one view to another.

import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react'
import { toast } from 'sonner'
import { ChevronLeft, ChevronRight, Copy, Lock, Search, X } from 'lucide-react'
import { api } from '../../api/client'
import type { LoadTargets } from '../../api/client'
import { useProject } from '../../ProjectContext'
import { useSessionState } from '../../hooks/useSessionState'
import { FileSvg, FolderSvg, getExt, parseVersionMeta } from './icons'
import { ContextMenu, DeleteModal, MoveModal, RenameModal } from './ItemModals'
import { buildOpenInTargets } from './open_in'
import {
  TILE_SIZES, USD_EXTS, currentItemKey, resolveOpenPath, sameNav, savedKey, trNow, useFolderManager,
} from './shared'
import { useTr } from '../../i18n'
import type { ExplorerItem, FindResult, NavLevel, PaneReport } from './shared'

interface CtxMenu { x: number; y: number; items: ExplorerItem[] }

export interface PaneHandle {
  navigateTo: (level: NavLevel) => void
  // Token Finder results (computed by the page) shown in this view.
  showFind:   (label: string, results: FindResult[] | null, loading: boolean) => void
}

interface Props {
  paneId:     number
  active:     boolean
  framed:     boolean                 // several views: draw a frame, accent on the active one
  initialNav: NavLevel                // where a brand-new view starts
  onFocus:    (paneId: number) => void
  onReport:   (paneId: number, r: PaneReport) => void
}

const sameSub = (a: string[], b: string[]) => a.join('/') === b.join('/')

// B3: last listing of each folder visited this session (all views). A folder opens
// at once from it, then the real listing replaces it (stale-while-revalidate).
const listingCache = new Map<string, ExplorerItem[]>()
const navKey = (n: NavLevel) => (n.kind === 'root' ? '' : `${n.project}/${n.subpath.join('/')}`)

export const ExplorerPane = forwardRef<PaneHandle, Props>(function ExplorerPane(
  { paneId, active, framed, initialNav, onFocus, onReport }, ref,
) {
  const fm = useFolderManager()
  const { tr } = useTr()
  const { project: activeProject, refreshProjects } = useProject()

  // Session-kept (U3): coming back to the Folder Manager reopens the same folder.
  // View 0 keeps the historical keys, so the single view behaves as before.
  const key = paneId === 0 ? 'fm' : `fm.pane${paneId}`
  const [navStack, setNavStack] = useSessionState<NavLevel[]>(`${key}.navStack`, () => [initialNav])
  const [navIdx, setNavIdx]     = useSessionState(`${key}.navIdx`, 0)
  const nav = navStack[Math.min(navIdx, navStack.length - 1)]

  const [items, setItems]                 = useState<ExplorerItem[]>([])
  const [selectedNames, setSelectedNames] = useState<Set<string>>(new Set())
  const [hoveredName, setHoveredName]     = useState<string | null>(null)
  const [loading, setLoading]             = useState(false)

  // Search (this view) + Token Finder results pushed by the page
  const [searchQuery, setSearchQuery]     = useState('')
  const [searchResults, setSearchResults] = useState<FindResult[] | null>(null)
  const [findLoading, setFindLoading]     = useState(false)
  const [resultLabel, setResultLabel]     = useState('')

  // Editable / copy-paste path bar
  const [editingPath, setEditingPath] = useState(false)
  const [pathDraft, setPathDraft]     = useState('')
  const [pathError, setPathError]     = useState('')

  // Drag & drop highlights
  const [dragOverName, setDragOverName] = useState<string | null>(null)
  const [dragOverBc, setDragOverBc]     = useState<number | null>(null)
  const [dragOverUp, setDragOverUp]     = useState(false)
  const [dragOverPane, setDragOverPane] = useState(false)

  const [locks, setLocks] = useState<Set<string>>(new Set())  // locked rel paths, current project

  // Context menu & item modals
  const [ctxMenu, setCtxMenu]             = useState<CtxMenu | null>(null)
  // V4: what "Ouvrir dans..." loads for the right-clicked USD file (asset first, layer second).
  const [loadTargets, setLoadTargets]     = useState<{ name: string; lt: LoadTargets } | null>(null)
  const [deleteConfirm, setDeleteConfirm] = useState<ExplorerItem[] | null>(null)
  const [deleteError, setDeleteError]     = useState('')
  const [renameTarget, setRenameTarget]   = useState<ExplorerItem | null>(null)
  const [moveTarget, setMoveTarget]       = useState<ExplorerItem[] | null>(null)

  const lastClickedRef = useRef<string | null>(null)

  const navProject = nav.kind === 'inside' ? nav.project : ''
  const breadcrumb: string[] = nav.kind === 'root' ? [tr('PROJETS', 'PROJECTS')] : [tr('PROJETS', 'PROJECTS'), nav.project, ...nav.subpath]
  const canBack    = navIdx > 0
  const canForward = navIdx < navStack.length - 1

  // ── Report to the page (right panel, active project, presets) ────────────────

  useEffect(() => { onReport(paneId, { nav, selectedNames, items }) }, [paneId, nav, selectedNames, items, onReport])

  // ── Navigation ──────────────────────────────────────────────────────────────

  const resetView = () => {
    setSelectedNames(new Set())
    setSearchResults(null)
    setSearchQuery('')
    lastClickedRef.current = null
  }

  const navigateTo = useCallback((level: NavLevel) => {
    if (sameNav(level, nav)) { setSearchResults(null); return }   // already there: no duplicate history entry
    setNavStack(prev => [...prev.slice(0, navIdx + 1), level])
    setNavIdx(i => i + 1)
    resetView()
  }, [nav, navIdx, setNavStack, setNavIdx])

  const goBack = useCallback(() => {
    if (navIdx > 0) { setNavIdx(i => i - 1); resetView() }
  }, [navIdx, setNavIdx])

  const goForward = useCallback(() => {
    if (navIdx < navStack.length - 1) { setNavIdx(i => i + 1); resetView() }
  }, [navIdx, navStack.length, setNavIdx])

  const navigateToBreadcrumb = useCallback((segIdx: number) => {
    if (segIdx === 0) navigateTo({ kind: 'root' })
    else if (nav.kind === 'inside')
      navigateTo({ kind: 'inside', project: nav.project, subpath: nav.subpath.slice(0, segIdx - 1) })
  }, [nav, navigateTo])

  useImperativeHandle(ref, () => ({
    navigateTo,
    showFind: (label, results, isLoading) => {
      setResultLabel(label)
      setSearchResults(results)
      setFindLoading(isLoading)
    },
  }), [navigateTo])

  // ── Listing ─────────────────────────────────────────────────────────────────

  // Another folder: clear the grid first. Same folder (reload after a write): keep it
  // on screen until the new listing arrives. A late answer for an older folder is dropped.
  const loadedNavRef = useRef<NavLevel | null>(null)
  const loadSeqRef   = useRef(0)

  const loadItems = useCallback(async () => {
    const seq = ++loadSeqRef.current
    if (!loadedNavRef.current || !sameNav(loadedNavRef.current, nav)) {
      setItems(listingCache.get(navKey(nav)) ?? [])
      loadedNavRef.current = nav
    }
    setLoading(true)
    try {
      let next: ExplorerItem[]
      if (nav.kind === 'root') {
        const d = await api.getProjects()
        void refreshProjects()  // keep the shared context list in sync
        next = d.projects.map(name => ({ name, isDir: true }))
      } else {
        const subpath = nav.subpath.join('/')
        const d = await api.browseProject(nav.project, subpath || undefined, fm.showSetup)
        next = [
          ...d.folders.map(f => ({ name: f.name, isDir: true })),
          ...(d.files ?? []).map(f => ({ name: f.name, isDir: false, legacy: !!f.legacy })),
        ]
      }
      listingCache.set(navKey(nav), next)
      if (seq !== loadSeqRef.current) return
      setItems(next)
      // A reload after a write elsewhere keeps the selection of what still exists.
      const names = new Set(next.map(i => i.name))
      setSelectedNames(prev => {
        const kept = [...prev].filter(n => names.has(n))
        return kept.length === prev.size ? prev : new Set(kept)
      })
    } catch {
      if (seq === loadSeqRef.current) setItems([])
    } finally {
      if (seq === loadSeqRef.current) setLoading(false)
    }
  }, [nav, fm.showSetup])  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { void loadItems() }, [loadItems, fm.fsTick])

  // Folder locks of the browsed project
  useEffect(() => {
    if (!navProject) { setLocks(new Set()); return }
    api.getLocks(navProject).then(d => setLocks(new Set(d.locked))).catch(() => setLocks(new Set()))
  }, [navProject, fm.fsTick])

  const lockRelOf = useCallback((item: ExplorerItem): string =>
    (nav.kind === 'inside' ? [...nav.subpath, item.name] : [item.name]).join('/'), [nav])

  const isItemLocked = useCallback((item: ExplorerItem): boolean =>
    nav.kind === 'inside' && locks.has(lockRelOf(item)), [nav, locks, lockRelOf])

  const toggleLock = useCallback(async (item: ExplorerItem) => {
    if (nav.kind !== 'inside') return
    const willLock = !locks.has(lockRelOf(item))
    try {
      const d = await api.setLock(nav.project, nav.subpath, item.name, willLock)
      setLocks(new Set(d.locked))
      fm.bumpFs()   // other views of the same project redraw the lock badge
      toast.success(willLock
        ? trNow(`"${item.name}" verrouillé`, `"${item.name}" locked`)
        : trNow(`"${item.name}" déverrouillé`, `"${item.name}" unlocked`))
    } catch (e) {
      toast.error(trNow(`Verrou : ${e instanceof Error ? e.message : 'échec'}`, `Lock: ${e instanceof Error ? e.message : 'failed'}`))
    }
  }, [nav, locks, lockRelOf, fm])

  const isItemArchived = useCallback((item: ExplorerItem): boolean => {
    const k = currentItemKey(item, nav)
    return fm.archived.some(s => savedKey(s) === k)
  }, [fm.archived, nav])

  const isItemFavorited = useCallback((item: ExplorerItem): boolean => {
    const k = currentItemKey(item, nav)
    return fm.favorites.some(s => savedKey(s) === k)
  }, [fm.favorites, nav])

  // ── Path bar (copy / paste-to-navigate) ─────────────────────────────────────

  // Absolute Windows/POSIX path of the current location, on the Flux drive.
  const currentAbsPath = useCallback((): string => {
    const ws = fm.workspace
    if (!ws) return ''
    const sep = ws.includes('\\') ? '\\' : '/'
    const base = [ws.replace(/[\\/]+$/, ''), 'DOSSIER_PROJETS']
    if (nav.kind === 'inside') base.push(nav.project, ...nav.subpath)
    return base.join(sep)
  }, [fm.workspace, nav])

  // Parse a pasted/typed path → NavLevel. Accepts:
  //  - absolute Windows (C:\…\DOSSIER_PROJETS\PROJ\sub) or UNC/POSIX under the workspace
  //  - relative "PROJ/sub" or "DOSSIER_PROJETS/PROJ/sub" (both separators)
  const parsePathToNav = useCallback((raw: string): NavLevel | null => {
    const s = raw.trim().replace(/^["']+|["']+$/g, '')
    if (!s) return null
    const ws = fm.workspace ?? ''
    const isAbs = /^[a-zA-Z]:[\\/]/.test(s) || s.startsWith('\\\\') || s.startsWith('/')
    if (isAbs) return ws ? resolveOpenPath(s, ws) : null
    let norm = s.replace(/\\/g, '/').replace(/^\/+|\/+$/g, '')
    const mk = 'DOSSIER_PROJETS/'
    const idx = norm.toUpperCase().indexOf(mk)
    if (idx !== -1) norm = norm.slice(idx + mk.length)
    const parts = norm.split('/').filter(Boolean)
    if (parts.length && (parts[0].toUpperCase() === 'PROJETS' || parts[0].toUpperCase() === 'PROJECTS')) parts.shift()  // breadcrumb prefix
    if (parts.length === 0) return { kind: 'root' }
    const [project, ...subpath] = parts
    return { kind: 'inside', project, subpath }
  }, [fm.workspace])

  const commitPathValue = useCallback(async (raw: string) => {
    const target = parsePathToNav(raw)
    if (!target) { setPathError(trNow('Chemin invalide (hors du workspace FLUX ?)', 'Invalid path (outside the FLUX workspace?)')); return }
    if (target.kind === 'root') { setEditingPath(false); setPathError(''); navigateTo({ kind: 'root' }); return }
    try {
      await api.browseProject(target.project, target.subpath.join('/') || undefined)  // throws on 404
      setEditingPath(false); setPathError(''); navigateTo(target)
    } catch {
      setPathError(trNow('Chemin introuvable dans le workspace FLUX', 'Path not found in the FLUX workspace'))
    }
  }, [parsePathToNav, navigateTo])

  const copyText = (text: string, ok: string) => {
    navigator.clipboard.writeText(text).then(() => toast.success(ok), () => toast.error(trNow('Copie impossible', 'Copy failed')))
  }

  const copyCurrentPath = useCallback(() => {
    const p = currentAbsPath()
    if (p) copyText(p, trNow('Chemin copié', 'Path copied'))
  }, [currentAbsPath])

  const startEditPath = useCallback(() => {
    setPathDraft(currentAbsPath())
    setPathError('')
    setEditingPath(true)
  }, [currentAbsPath])

  const pasteNavigate = useCallback(async () => {
    try {
      const txt = await navigator.clipboard.readText()
      if (txt.trim()) void commitPathValue(txt)
    } catch { /* clipboard blocked */ }
  }, [commitPathValue])

  // ── Search (folder / file names under the usual roots of the project) ───────

  const handleSearch = useCallback(async (query: string) => {
    if (!query.trim()) { setSearchResults(null); return }
    const proj = navProject || activeProject
    if (!proj) return
    setFindLoading(true)
    setSearchResults([])
    setResultLabel(`«${query}»`)
    const results: FindResult[] = []
    const q = query.toLowerCase()
    const tokens = await api.getTokens(proj).then(d => d.tokens).catch(() => ({} as Record<string, Record<string, string>>))
    const classBasePaths = Object.values(tokens.CLASS ?? {})
      .filter(p => !p.includes('{seq}'))
      .map(p => p.split('/'))
    const pathsToSearch: string[][] = [[], ['assets'], ['shot'], ['comp'], ['lighting'], ...classBasePaths]
    const pushIfUnique = (r: FindResult) => {
      if (!results.some(x => x.subpath.join('/') === r.subpath.join('/'))) results.push(r)
    }
    for (const basePath of pathsToSearch) {
      try {
        const d = await api.browseProject(proj, basePath.join('/') || undefined)
        for (const folder of d.folders) {
          if (folder.name.toLowerCase().includes(q)) {
            const subpath = [...basePath, folder.name]
            pushIfUnique({ label: folder.name, pathStr: subpath.join(' / '), project: proj, subpath, isDir: true })
          }
        }
        for (const file of d.files ?? []) {
          if (file.name.toLowerCase().includes(q)) {
            const subpath = [...basePath, file.name]
            pushIfUnique({ label: file.name, pathStr: subpath.join(' / '), project: proj, subpath, isDir: false })
          }
        }
      } catch { /* folder missing in this project */ }
    }
    results.sort((a, b) => {
      const aL = a.label.toLowerCase(), bL = b.label.toLowerCase()
      if (aL === q && bL !== q) return -1
      if (bL === q && aL !== q) return 1
      if (aL.startsWith(q) && !bL.startsWith(q)) return -1
      if (bL.startsWith(q) && !aL.startsWith(q)) return 1
      return aL.localeCompare(bL)
    })
    setSearchResults(results)
    setFindLoading(false)
  }, [navProject, activeProject])

  // ── Item actions ────────────────────────────────────────────────────────────

  const handleDoubleClick = useCallback((item: ExplorerItem) => {
    if (!item.isDir) return
    fm.addToRecents(item, nav)
    if (nav.kind === 'root') navigateTo({ kind: 'inside', project: item.name, subpath: [] })
    else navigateTo({ kind: 'inside', project: nav.project, subpath: [...nav.subpath, item.name] })
  }, [nav, navigateTo, fm])

  const handleRightClick = useCallback((e: React.MouseEvent, item: ExplorerItem) => {
    e.preventDefault()
    e.stopPropagation()
    // If item already in multi-selection → ctx applies to all selected; else single
    const newSel = selectedNames.has(item.name) && selectedNames.size > 1
      ? selectedNames
      : new Set([item.name])
    setSelectedNames(newSel)
    const ctxItems = items.filter(it => newSel.has(it.name))
    setCtxMenu({ x: e.clientX, y: e.clientY, items: ctxItems })
    setLoadTargets(null)
    const one = ctxItems.length === 1 ? ctxItems[0] : null
    if (one && !one.isDir && nav.kind === 'inside' && USD_EXTS.has('.' + (one.name.split('.').pop() ?? '').toLowerCase())) {
      const rel = [...nav.subpath, one.name].join('/')
      api.getLoadTargets(nav.project, rel)
        .then(lt => setLoadTargets({ name: one.name, lt }))
        .catch(() => setLoadTargets(null))
    }
  }, [selectedNames, items, nav])

  const handleRename = useCallback(async (item: ExplorerItem, newName: string) => {
    if (nav.kind !== 'inside') return
    await api.patchItem(nav.project, nav.subpath, item.name, newName)
    fm.pushUndo({ label: trNow(`renommage "${item.name}"`, `rename "${item.name}"`), actions: [{ kind: 'rename', project: nav.project, sub: nav.subpath, oldName: item.name, newName }] })
    fm.renameSaved(currentItemKey(item, nav), newName)
    setRenameTarget(null)
    fm.bumpFs()
  }, [nav, fm])

  const handleMove = useCallback(async (targets: ExplorerItem[], newSubpath: string[]) => {
    if (nav.kind !== 'inside') return
    await fm.transfer(
      { project: nav.project, subpath: nav.subpath, names: targets.map(t => t.name) },
      { project: nav.project, subpath: newSubpath }, 'move')
    setMoveTarget(null)
  }, [nav, fm])

  const handleDelete = useCallback(async (targets: ExplorerItem[]) => {
    if (nav.kind !== 'inside') return
    setDeleteConfirm(null)
    setDeleteError('')
    try {
      for (const item of targets) {
        await api.deleteItem(nav.project, nav.subpath, item.name)
        fm.forgetSaved([currentItemKey(item, nav)], true)
      }
      setSelectedNames(new Set())
    } catch (e) {
      setDeleteError(e instanceof Error ? e.message : trNow('Erreur lors de la suppression', 'Delete failed'))
    } finally {
      fm.bumpFs()
    }
  }, [nav, fm])

  const handleCopyPath = useCallback((item: ExplorerItem) => {
    const ws = fm.workspace
    if (!ws) return
    const sep = ws.includes('\\') ? '\\' : '/'
    const parts = nav.kind === 'root'
      ? [ws, 'DOSSIER_PROJETS', item.name]
      : [ws, 'DOSSIER_PROJETS', nav.project, ...nav.subpath, item.name]
    copyText(parts.join(sep), trNow('Chemin copié', 'Path copied'))
  }, [nav, fm.workspace])

  // Copy the path as $FLUX/DOSSIER_PROJETS/... — pasteable directly in any
  // Houdini string parm (the flux.json / autostart sets $FLUX to the pipe root).
  const handleCopyHoudiniPath = useCallback((item: ExplorerItem) => {
    const parts = nav.kind === 'root'
      ? ['$FLUX', 'DOSSIER_PROJETS', item.name]
      : ['$FLUX', 'DOSSIER_PROJETS', nav.project, ...nav.subpath, item.name]
    copyText(parts.join('/'), trNow('Chemin Houdini copié', 'Houdini path copied'))
  }, [nav])

  // ── Clipboard (copy / cut / paste) ──────────────────────────────────────────

  const copySelection = useCallback(() => {
    if (nav.kind !== 'inside' || selectedNames.size === 0) return
    const sel = items.filter(i => selectedNames.has(i.name))
    fm.setClipboard({ op: 'copy', project: nav.project, subpath: nav.subpath, items: sel })
    toast.success(trNow(`${sel.length} élément(s) copié(s)`, `${sel.length} item(s) copied`))
  }, [nav, selectedNames, items, fm])

  const cutSelection = useCallback(() => {
    if (nav.kind !== 'inside' || selectedNames.size === 0) return
    const sel = items.filter(i => selectedNames.has(i.name))
    const cuttable = sel.filter(i => !isItemLocked(i))
    if (cuttable.length < sel.length) toast.error(trNow(`${sel.length - cuttable.length} verrouillé(s) : non coupé(s)`, `${sel.length - cuttable.length} locked: not cut`))
    if (cuttable.length === 0) return
    fm.setClipboard({ op: 'cut', project: nav.project, subpath: nav.subpath, items: cuttable })
  }, [nav, selectedNames, items, isItemLocked, fm])

  const selectAll = useCallback(() => {
    setSelectedNames(new Set(items.filter(i => !isItemArchived(i)).map(i => i.name)))
  }, [items, isItemArchived])

  const pasteClipboard = useCallback(async () => {
    const clip = fm.clipboard
    if (!clip || nav.kind !== 'inside') return
    const ok = await fm.transfer(
      { project: clip.project, subpath: clip.subpath, names: clip.items.map(i => i.name) },
      { project: nav.project, subpath: nav.subpath },
      clip.op === 'cut' ? 'move' : 'copy')
    if (clip.op === 'cut' && ok > 0) fm.setClipboard(null)
  }, [nav, fm])

  // Keyboard: only the active view reacts (guarded against inputs, modals, path bar).
  useEffect(() => {
    if (!active) return
    const h = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null
      const typing = !!t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)
      if (typing || editingPath) return
      if (renameTarget || moveTarget || deleteConfirm) return
      if (e.key === 'Delete') {
        if (selectedNames.size === 0 || nav.kind !== 'inside') return
        const targets = items.filter(it => selectedNames.has(it.name))
        if (targets.some(isItemLocked)) { toast.error(trNow('Élément verrouillé : déverrouillez d’abord', 'Item locked: unlock it first')); return }
        if (targets.length > 0) setDeleteConfirm(targets)
        return
      }
      if (t && t.closest && t.closest('[data-flux-pathbar]')) return  // path bar owns its own Ctrl+C/V
      if (!(e.ctrlKey || e.metaKey)) return
      const k = e.key.toLowerCase()
      if (k === 'c') copySelection()
      else if (k === 'x') cutSelection()
      else if (k === 'v') { e.preventDefault(); void pasteClipboard() }
      else if (k === 'a') { e.preventDefault(); selectAll() }
      else if (k === 'z') { e.preventDefault(); void fm.undoLast() }
    }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [active, copySelection, cutSelection, pasteClipboard, selectAll, editingPath, renameTarget, moveTarget,
      deleteConfirm, selectedNames, items, nav, isItemLocked, fm])

  // Close context menu on outside click / Escape
  useEffect(() => {
    if (!ctxMenu) return
    const h = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent) { if (e.key === 'Escape') setCtxMenu(null) }
      else setCtxMenu(null)
    }
    document.addEventListener('mousedown', h)
    document.addEventListener('keydown', h)
    return () => { document.removeEventListener('mousedown', h); document.removeEventListener('keydown', h) }
  }, [ctxMenu])

  // ── Drag & drop (within this view and between views) ────────────────────────

  const onItemDragStart = (e: React.DragEvent, item: ExplorerItem) => {
    if (nav.kind !== 'inside') { e.preventDefault(); return }   // projects are not moved
    const names = selectedNames.has(item.name) && selectedNames.size > 0 ? [...selectedNames] : [item.name]
    if (!selectedNames.has(item.name)) setSelectedNames(new Set([item.name]))
    const locked = new Set(names.filter(n => locks.has([...nav.subpath, n].join('/'))))
    fm.dragRef.current = { paneId, project: nav.project, subpath: nav.subpath, names, locked }
    e.dataTransfer.effectAllowed = 'copyMove'
    e.dataTransfer.setData('text/plain', names.join('\n'))
  }

  const acceptDrag = (e: React.DragEvent): boolean => {
    if (!fm.dragRef.current || nav.kind !== 'inside') return false
    e.preventDefault()
    e.dataTransfer.dropEffect = e.ctrlKey ? 'copy' : 'move'
    return true
  }

  // Ctrl held at drop = copy, else move (like the Windows explorer).
  const dropInto = (e: React.DragEvent, destSub: string[]) => {
    e.preventDefault(); e.stopPropagation()
    const p = fm.dragRef.current
    fm.dragRef.current = null
    if (!p || nav.kind !== 'inside') return
    // A folder dropped onto itself is skipped (the rest of the selection still goes in).
    const names = p.project === nav.project
      ? p.names.filter(n => !sameSub([...p.subpath, n], destSub))
      : p.names
    void fm.transfer({ project: p.project, subpath: p.subpath, names, locked: p.locked },
                     { project: nav.project, subpath: destSub }, e.ctrlKey ? 'copy' : 'move')
  }

  // Dropping on the view itself = into the folder it shows (only useful from another view).
  const fromOtherPlace = () => {
    const p = fm.dragRef.current
    return !!p && nav.kind === 'inside' && !(p.project === nav.project && sameSub(p.subpath, nav.subpath))
  }

  // ── Render ──────────────────────────────────────────────────────────────────

  const navBtn = (ok: boolean): React.CSSProperties => ({ width: 24, height: 24, border: '1px solid var(--rule-2)', borderRadius: 5, display: 'flex', alignItems: 'center', justifyContent: 'center', color: ok ? 'var(--ink-2)' : 'var(--ink-4)', boxShadow: 'var(--shadow-xs)', cursor: ok ? 'pointer' : 'default', opacity: ok ? 1 : 0.4, flexShrink: 0, transition: 'background 0.1s, border-color 0.1s, color 0.1s' })
  const upDroppable = nav.kind === 'inside' && nav.subpath.length >= 1
  const tile = TILE_SIZES[fm.tileSize]
  const clipboard = fm.clipboard

  return (
    <div
      onMouseDownCapture={() => { if (!active) onFocus(paneId) }}
      style={{
        flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, minHeight: 0, overflow: 'hidden',
        ...(framed ? { border: `1px solid ${active ? 'var(--accent)' : 'var(--rule)'}`, borderRadius: 6, background: 'var(--paper)' } : {}),
      }}
    >
      {/* Barre de navigation de la vue : retour / suivant, chemin, recherche */}
      <div style={{ padding: '6px 8px', borderBottom: '1px solid var(--rule)', background: 'var(--paper-2)', flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 4 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {/* Retour — clic: historique ; déposer ici: monter d'un niveau */}
          <div
            onClick={canBack ? goBack : undefined}
            onDragOver={upDroppable ? (e => { if (acceptDrag(e) && !dragOverUp) setDragOverUp(true) }) : undefined}
            onDragLeave={upDroppable ? (() => setDragOverUp(false)) : undefined}
            onDrop={upDroppable ? (e => { setDragOverUp(false); dropInto(e, (nav.kind === 'inside' ? nav.subpath : []).slice(0, -1)) }) : undefined}
            title={upDroppable ? tr('Retour · déposer ici pour monter d’un niveau', 'Back · drop here to move up one level') : tr('Retour', 'Back')}
            style={{ ...navBtn(canBack || upDroppable), ...(dragOverUp ? { borderColor: 'var(--accent)', background: 'var(--accent-soft)', color: 'var(--accent-hi)' } : {}) }}
          >
            <ChevronLeft size={13} strokeWidth={2} />
          </div>
          <div onClick={canForward ? goForward : undefined} title={tr('Suivant', 'Forward')} style={navBtn(canForward)}>
            <ChevronRight size={13} strokeWidth={2} />
          </div>

          {/* Path bar — breadcrumb (clic pour naviguer) OU champ éditable (Ctrl+V pour naviguer vers un chemin) */}
          {editingPath ? (
            <input
              autoFocus
              value={pathDraft}
              onChange={e => { setPathDraft(e.target.value); if (pathError) setPathError('') }}
              onKeyDown={e => {
                if (e.key === 'Enter') void commitPathValue(pathDraft)
                else if (e.key === 'Escape') { setEditingPath(false); setPathError('') }
              }}
              onBlur={() => { if (!pathError) setEditingPath(false) }}
              spellCheck={false}
              placeholder={tr('Coller un chemin (C:\\… ou PROJET/sous-dossier) puis Entrée', 'Paste a path (C:\\… or PROJECT/subfolder) then Enter')}
              style={{ flex: 1, minWidth: 0, height: 24, border: '1px solid ' + (pathError ? 'var(--err)' : 'var(--accent)'), padding: '0 8px', background: 'var(--bg-deep)', borderRadius: 5, boxShadow: 'var(--shadow-inset)', fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink)', outline: 'none' }}
            />
          ) : (
            <div
              data-flux-pathbar
              tabIndex={0}
              title={tr('Cliquer pour éditer · Ctrl+C copier le chemin · Ctrl+V coller un chemin pour y naviguer', 'Click to edit · Ctrl+C copy the path · Ctrl+V paste a path to go there')}
              onClick={startEditPath}
              onKeyDown={e => {
                if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'c') { e.preventDefault(); copyCurrentPath() }
                else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'v') { e.preventDefault(); void pasteNavigate() }
              }}
              style={{ flex: 1, minWidth: 0, display: 'flex', alignItems: 'center', gap: 2, fontFamily: 'var(--mono)', fontSize: 11, height: 24, border: '1px solid var(--rule)', padding: '0 4px 0 8px', background: 'var(--bg-deep)', borderRadius: 5, boxShadow: 'var(--shadow-inset)', overflow: 'hidden', cursor: 'text', outline: 'none' }}
            >
              <div style={{ flex: 1, minWidth: 0, display: 'flex', alignItems: 'center', gap: 2, overflow: 'hidden' }}>
                {breadcrumb.map((seg, i) => {
                  const isLast = i === breadcrumb.length - 1
                  const droppable = !isLast && i >= 1 && nav.kind === 'inside'
                  return (
                    <span key={i} style={{ display: 'flex', alignItems: 'center', gap: 2, flexShrink: isLast ? 0 : 1, minWidth: isLast ? 'auto' : 0 }}>
                      {i > 0 && <ChevronRight size={9} strokeWidth={1.5} color="var(--ink-4)" style={{ flexShrink: 0 }} />}
                      <span
                        onClick={!isLast ? (e) => { e.stopPropagation(); navigateToBreadcrumb(i) } : undefined}
                        onDragOver={droppable ? (e => { if (acceptDrag(e) && dragOverBc !== i) setDragOverBc(i) }) : undefined}
                        onDragLeave={droppable ? (() => setDragOverBc(prev => (prev === i ? null : prev))) : undefined}
                        onDrop={droppable && nav.kind === 'inside' ? (e => { setDragOverBc(null); dropInto(e, nav.subpath.slice(0, i - 1)) }) : undefined}
                        style={{ color: dragOverBc === i ? 'var(--accent-hi)' : isLast ? 'var(--ink)' : 'var(--ink-3)', background: dragOverBc === i ? 'var(--accent-soft)' : 'transparent', borderRadius: 3, padding: dragOverBc === i ? '0 3px' : 0, fontWeight: isLast ? 600 : 400, cursor: !isLast ? 'pointer' : 'text', whiteSpace: 'nowrap', overflow: isLast ? 'visible' : 'hidden', textOverflow: 'ellipsis', flexShrink: isLast ? 0 : 1 }}
                      >
                        {seg}
                      </span>
                    </span>
                  )
                })}
              </div>
              <div
                onClick={e => { e.stopPropagation(); copyCurrentPath() }}
                title={tr('Copier le chemin', 'Copy path')}
                style={{ flexShrink: 0, width: 18, height: 18, display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: 4, color: 'var(--ink-4)', cursor: 'pointer' }}
                onMouseEnter={e => { e.currentTarget.style.background = 'var(--accent-soft)'; e.currentTarget.style.color = 'var(--accent-hi)' }}
                onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--ink-4)' }}
              >
                <Copy size={11} strokeWidth={1.75} />
              </div>
            </div>
          )}

          {/* Search */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 5, border: '1px solid var(--rule-2)', padding: '0 6px', height: 24, flex: '0 1 150px', minWidth: 70, background: 'var(--bg-deep)', borderRadius: 5, boxShadow: 'var(--shadow-inset)' }}>
            <Search size={10} strokeWidth={2} color="var(--ink-4)" style={{ flexShrink: 0 }} />
            <input
              value={searchQuery}
              onChange={e => { setSearchQuery(e.target.value); if (!e.target.value) setSearchResults(null) }}
              onKeyDown={e => { if (e.key === 'Enter') void handleSearch(searchQuery) }}
              placeholder={tr('Rechercher…', 'Search…')}
              style={{ flex: 1, minWidth: 0, background: 'transparent', border: 'none', outline: 'none', fontSize: 11, color: 'var(--ink-2)', fontFamily: 'var(--sans)' }}
            />
            {searchQuery && (
              <X size={9} strokeWidth={2} color="var(--ink-4)" style={{ flexShrink: 0, cursor: 'pointer' }}
                onClick={() => { setSearchQuery(''); setSearchResults(null) }}
              />
            )}
          </div>
        </div>

        {/* Erreur de chemin (coller/naviguer) */}
        {pathError && (
          <div style={{ fontFamily: 'var(--mono)', fontSize: 10.5, color: 'var(--err)', padding: '0 2px' }}>
            {pathError}
          </div>
        )}
      </div>

      {/* Contenu : résultats de recherche ou dossier courant. Déposer ici = dans ce dossier. */}
      <div
        style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, outline: dragOverPane ? '1px dashed var(--accent)' : 'none', outlineOffset: -3 }}
        onClick={() => { if (searchResults === null) setSelectedNames(new Set()) }}
        onDragOver={e => { if (fromOtherPlace() && acceptDrag(e) && !dragOverPane) setDragOverPane(true) }}
        onDragLeave={e => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragOverPane(false) }}
        onDrop={e => { setDragOverPane(false); if (fromOtherPlace() && nav.kind === 'inside') dropInto(e, nav.subpath) }}
      >
        {searchResults !== null ? (
          <>
            <div style={{ padding: '7px 12px', borderBottom: '1px solid var(--rule)', flexShrink: 0, display: 'flex', alignItems: 'center', gap: 8, background: 'var(--paper-2)' }}>
              <div style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-2)', flex: 1 }}>
                <span style={{ color: 'var(--ink-4)', fontSize: 10.5 }}>{tr('RÉSULTATS · ', 'RESULTS · ')}</span>
                {resultLabel && <span style={{ color: 'var(--ink-2)', fontWeight: 600 }}>{resultLabel} · </span>}
                {findLoading
                  ? tr('Recherche…', 'Searching…')
                  : searchResults.length === 0
                    ? tr('Aucun résultat', 'No results')
                    : tr(`${searchResults.length} trouvé${searchResults.length > 1 ? 's' : ''}`, `${searchResults.length} found`)}
              </div>
              <div
                onClick={e => { e.stopPropagation(); setSearchResults(null) }}
                style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer', color: 'var(--ink-4)', fontSize: 10.5, fontFamily: 'var(--mono)', padding: '2px 6px', borderRadius: 4, border: '1px solid var(--rule-2)' }}
              >
                <X size={9} strokeWidth={2} /> Fermer
              </div>
            </div>
            <div style={{ flex: 1, overflowY: 'auto', padding: '6px 8px' }}>
              {searchResults.length === 0 && !findLoading ? (
                <div style={{ padding: '20px 12px', textAlign: 'center', color: 'var(--ink-4)', fontSize: 11, fontStyle: 'italic' }}>
                  Aucun dossier correspondant
                </div>
              ) : searchResults.map((r, i) => (
                <div
                  key={i}
                  onClick={e => { e.stopPropagation(); navigateTo({ kind: 'inside', project: r.project, subpath: r.subpath }) }}
                  style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 8px', borderRadius: 6, cursor: 'pointer', marginBottom: 2, border: '1px solid transparent', transition: 'background 0.08s' }}
                  onMouseEnter={e => (e.currentTarget.style.background = 'var(--accent-soft)')}
                  onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                >
                  <FolderSvg size={24} />
                  <div style={{ minWidth: 0 }}>
                    <div title={r.label} style={{ fontSize: 11, fontWeight: 500, color: 'var(--ink)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{r.label}</div>
                    <div style={{ fontSize: 10.5, fontFamily: 'var(--mono)', color: 'var(--ink-4)', marginTop: 1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{r.project} / {r.pathStr}</div>
                  </div>
                </div>
              ))}
            </div>
          </>
        ) : loading && items.length === 0 ? (
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--ink-4)', fontSize: 11, fontStyle: 'italic' }}>
            {tr('Chargement…', 'Loading…')}
          </div>
        ) : items.length === 0 ? (
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--ink-4)', fontSize: 11, fontStyle: 'italic' }}>
            {tr('Vide', 'Empty')}
          </div>
        ) : (
          <div style={{ flex: 1, padding: '10px 12px', overflowY: 'auto', minHeight: 0 }}>
            {deleteError && (
              <div style={{ marginBottom: 8, padding: '6px 10px', borderRadius: 5, background: 'rgba(var(--err-rgb),0.1)', border: '1px solid var(--err)', fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--err)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span>{deleteError}</span>
                <X size={10} strokeWidth={2} style={{ cursor: 'pointer', flexShrink: 0 }} onClick={() => setDeleteError('')} />
              </div>
            )}
            <div style={{ display: 'grid', gridTemplateColumns: `repeat(auto-fill, minmax(${tile.col}px, 1fr))`, gap: `${tile.gap}px`, alignContent: 'start' }}>
              {items.filter(item => !isItemArchived(item)).map((item, i) => {
                const isSel     = selectedNames.has(item.name)
                const isHovered = hoveredName === item.name
                const isDropTarget = item.isDir && dragOverName === item.name
                const isCut = clipboard?.op === 'cut' && nav.kind === 'inside' &&
                  clipboard.project === nav.project &&
                  clipboard.subpath.join('/') === nav.subpath.join('/') &&
                  clipboard.items.some(ci => ci.name === item.name)
                const locked = isItemLocked(item)
                return (
                  <div
                    key={i}
                    onClick={e => {
                      e.stopPropagation()
                      if (e.shiftKey && lastClickedRef.current) {
                        const names   = items.map(it => it.name)
                        const lastIdx = names.indexOf(lastClickedRef.current)
                        const curIdx  = names.indexOf(item.name)
                        if (lastIdx !== -1 && curIdx !== -1) {
                          const lo = Math.min(lastIdx, curIdx)
                          const hi = Math.max(lastIdx, curIdx)
                          setSelectedNames(new Set(names.slice(lo, hi + 1)))
                          return
                        }
                      }
                      if (e.ctrlKey || e.metaKey) {
                        setSelectedNames(prev => {
                          const next = new Set(prev)
                          if (next.has(item.name)) next.delete(item.name)
                          else next.add(item.name)
                          return next
                        })
                        lastClickedRef.current = item.name
                        return
                      }
                      lastClickedRef.current = item.name
                      setSelectedNames(new Set([item.name]))
                    }}
                    onDoubleClick={e => { e.stopPropagation(); handleDoubleClick(item) }}
                    onContextMenu={e => handleRightClick(e, item)}
                    onMouseEnter={() => setHoveredName(item.name)}
                    onMouseLeave={() => setHoveredName(null)}
                    draggable
                    onDragStart={e => onItemDragStart(e, item)}
                    onDragEnd={() => { fm.dragRef.current = null }}
                    onDragOver={item.isDir ? (e => { if (acceptDrag(e)) { e.stopPropagation(); if (dragOverName !== item.name) setDragOverName(item.name) } }) : undefined}
                    onDragLeave={item.isDir ? (() => setDragOverName(prev => (prev === item.name ? null : prev))) : undefined}
                    onDrop={item.isDir ? (e => { setDragOverName(null); setDragOverPane(false); dropInto(e, [...(nav.kind === 'inside' ? nav.subpath : []), item.name]) }) : undefined}
                    style={{ position: 'relative', display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '8px 4px 6px', borderRadius: 6, background: (isDropTarget || isSel) ? 'var(--accent-soft)' : 'transparent', border: isDropTarget ? '1px dashed var(--accent)' : isSel ? '1px solid var(--accent)' : '1px solid transparent', opacity: isCut ? 0.45 : 1, gap: 5, cursor: 'default', userSelect: 'none', transition: 'background 0.08s, opacity 0.12s' }}
                  >
                    {/* Checkbox multi-sélection */}
                    {(isHovered || isSel) && (
                      <div
                        onClick={e => {
                          e.stopPropagation()
                          setSelectedNames(prev => {
                            const next = new Set(prev)
                            if (next.has(item.name)) next.delete(item.name)
                            else next.add(item.name)
                            return next
                          })
                        }}
                        style={{ position: 'absolute', top: 4, left: 4, width: 14, height: 14, borderRadius: 3, border: `1.5px solid ${isSel ? 'var(--accent)' : 'var(--ink-4)'}`, background: isSel ? 'var(--accent)' : 'rgba(0,0,0,0.25)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1 }}
                      >
                        {isSel && <span style={{ color: 'white', fontSize: 10, fontWeight: 700, lineHeight: 1 }}>✓</span>}
                      </div>
                    )}
                    {locked && (
                      <div
                        title={tr('Verrouillé', 'Locked')}
                        style={{ position: 'absolute', top: 4, right: 4, width: 15, height: 15, borderRadius: 3, background: 'var(--paper-2)', border: '1px solid var(--accent)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--accent-hi)', zIndex: 1, boxShadow: 'var(--shadow-xs)' }}
                      >
                        <Lock size={9} strokeWidth={2} />
                      </div>
                    )}
                    {(() => {
                      const meta = parseVersionMeta(item.name)
                      return item.isDir
                        ? <FolderSvg size={tile.folder} selected={isSel} version={meta.version} format={meta.format} />
                        : <FileSvg   size={tile.file} selected={isSel} ext={getExt(item.name)} version={meta.version} />
                    })()}
                    {/* Full name, no truncation: long publish names wrap entirely */}
                    <div title={item.name} style={{ fontSize: tile.font, textAlign: 'center', color: isSel ? 'var(--ink)' : 'var(--ink-2)', fontWeight: isSel ? 500 : 400, wordBreak: 'break-all', lineHeight: 1.3, maxWidth: '100%' }}>
                      {item.name}
                    </div>
                    {item.legacy && (
                      <span title={tr("Ancien fichier du Constructeur : plus propose a l'import (clic droit pour le supprimer)", 'Old Builder file: no longer offered for import (right-click to delete it)')}
                        style={{ fontSize: 10.5, padding: '1px 6px', borderRadius: 999, border: '1px solid var(--rule-2)', color: 'var(--ink-3)', background: 'var(--paper-2)' }}>
                        {tr('ancien', 'old')}
                      </span>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </div>

      {/* Context menu overlay */}
      {ctxMenu && (
        <ContextMenu
          x={ctxMenu.x}
          y={ctxMenu.y}
          isFavorited={isItemFavorited(ctxMenu.items[0])}
          isArchived={isItemArchived(ctxMenu.items[0])}
          locked={ctxMenu.items.some(isItemLocked)}
          canEdit={nav.kind === 'inside'}
          canDelete={nav.kind === 'inside'}
          count={ctxMenu.items.length}
          onFavorite={() => ctxMenu.items.forEach(it => fm.toggleFavorite(it, nav))}
          onArchive={() => ctxMenu.items.forEach(it => fm.toggleArchived(it, nav))}
          onToggleLock={nav.kind === 'inside' && ctxMenu.items.length === 1
            ? () => void toggleLock(ctxMenu.items[0])
            : undefined}
          onRename={() => setRenameTarget(ctxMenu.items[0])}
          onMove={() => setMoveTarget(ctxMenu.items)}
          onDelete={() => setDeleteConfirm(ctxMenu.items)}
          onCopyPath={ctxMenu.items.length === 1 ? () => handleCopyPath(ctxMenu.items[0]) : undefined}
          onCopyHoudiniPath={ctxMenu.items.length === 1 ? () => handleCopyHoudiniPath(ctxMenu.items[0]) : undefined}
          openInTargets={nav.kind === 'inside'
            ? buildOpenInTargets({ project: nav.project, subpath: nav.subpath, items: ctxMenu.items,
                                   dccStatus: fm.dccStatus, loadTargets, onChanged: fm.bumpFs })
            : []}
          onClose={() => setCtxMenu(null)}
        />
      )}

      {deleteConfirm && (
        <DeleteModal
          items={deleteConfirm}
          onConfirm={() => void handleDelete(deleteConfirm)}
          onCancel={() => setDeleteConfirm(null)}
        />
      )}

      {renameTarget && (
        <RenameModal
          item={renameTarget}
          onConfirm={newName => handleRename(renameTarget, newName)}
          onCancel={() => setRenameTarget(null)}
        />
      )}

      {moveTarget && nav.kind === 'inside' && (
        <MoveModal
          items={moveTarget}
          project={nav.project}
          currentSubpath={nav.subpath}
          onConfirm={newSubpath => handleMove(moveTarget, newSubpath)}
          onCancel={() => setMoveTarget(null)}
        />
      )}
    </div>
  )
})
