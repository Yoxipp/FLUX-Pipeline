import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { toast } from 'sonner'
import { useLocation } from 'react-router-dom'
import {
  Star, LayoutGrid, Clock, Archive,
  HardDrive, X, Trash2, Copy, RotateCcw,
  Grid3x3, Grid2x2, Square, FileDown, Rows2, Columns2, ChevronDown, Check,
} from 'lucide-react'
import * as Menu from '@radix-ui/react-dropdown-menu'
import { FolderIcon } from '../components/shared/ui'
import { PublishNote } from '../components/shared/PublishNote'
import { api } from '../api/client'
import type { Preset } from '../types'
import { useProject } from '../ProjectContext'
import { useSettings } from '../hooks/useSettings'
import { useDccStatus } from '../hooks/useDccStatus'
import { useSessionState } from '../hooks/useSessionState'
import { useTr } from '../i18n'
import { FileSvg, FolderSvg, getExt } from './folder_manager/icons'
import { ExplorerPane } from './folder_manager/ExplorerPane'
import type { PaneHandle } from './folder_manager/ExplorerPane'
import {
  FolderManagerContext, PANE_COUNT, itemKey, makeSavedItem, navigateTargetFor, resolveOpenPath, savedKey, trNow, uniqueName,
} from './folder_manager/shared'
import type {
  Clip, DragPayload, ExplorerItem, FindResult, FolderManagerShared, NavLevel, PaneLayout, PaneReport,
  SavedItem, TileSize, TransferDest, TransferSource, UndoAction, UndoOp,
} from './folder_manager/shared'

// ── Types ─────────────────────────────────────────────────────────────────────

type SidebarTab = 'tous' | 'favoris' | 'recents' | 'archives'

// Tile size, views and the creation forms are page preferences, persisted per browser
// (not part of a work profile, ADR 0043). Ctrl + wheel over the views changes the tile size.
const TILE_SIZE_KEY = 'flux.folderManager.tileSize'
const LAYOUT_KEY = 'flux.folderManager.layout'
const SHOW_SETUP_KEY = 'flux.folderManager.showSetup'

function useLocalPref<T extends string>(key: string, fallback: T, valid: readonly T[]): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const v = localStorage.getItem(key)
      if (v && (valid as readonly string[]).includes(v)) return v as T
    } catch { /* localStorage unavailable */ }
    return fallback
  })
  const change = useCallback((next: T) => {
    setValue(next)
    try { localStorage.setItem(key, next) } catch { /* localStorage unavailable */ }
  }, [key])
  return [value, change]
}

const TILE_ORDER: TileSize[] = ['sm', 'md', 'lg']
const TILE_CHOICES: { id: TileSize; icon: typeof Square; title: string; titleEn: string }[] = [
  { id: 'sm', icon: Grid3x3, title: 'Petites tuiles',  titleEn: 'Small tiles' },
  { id: 'md', icon: Grid2x2, title: 'Tuiles moyennes', titleEn: 'Medium tiles' },
  { id: 'lg', icon: Square,  title: 'Grandes tuiles',  titleEn: 'Large tiles' },
]

const LAYOUTS: { id: PaneLayout; icon: typeof Square; title: string; titleEn: string }[] = [
  { id: 'single',  icon: Square,   title: 'Une vue',               titleEn: 'One view' },
  { id: 'stacked', icon: Rows2,    title: 'Deux vues empilées',    titleEn: 'Two views stacked' },
  { id: 'side',    icon: Columns2, title: 'Deux vues côte à côte', titleEn: 'Two views side by side' },
  { id: 'quad',    icon: Grid2x2,  title: 'Quatre vues',           titleEn: 'Four views' },
]

const EMPTY_REPORT: PaneReport = { nav: { kind: 'root' }, selectedNames: new Set(), items: [] }

type FinderMode = 'asset' | 'shot'

interface TokenSel { category: string; name: string; task: string; instance: string; variante: string; seq: string; shot: string; mode: FinderMode }
const EMPTY_TOKEN_SEL: TokenSel = { category: '', name: '', task: '', instance: '', variante: '', seq: '', shot: '', mode: 'asset' }



// Finder — same fixed lists as the Publisher composer (Category / Task predefined,
// FX is the display label for the FXRIG class). Name/Instance/Variante come from disk.
const FINDER_CATEGORIES = ['CHAR', 'PROPS', 'ENV', 'FX']
const FINDER_CATEGORY_TO_CLASS: Record<string, string> = { CHAR: 'CHAR', PROPS: 'PROPS', ENV: 'ENV', FX: 'FXRIG' }
// One task = one USD department (ADR 0019); MULT is kept on disk for old publishes only.
const FINDER_TASKS = ['GEO', 'SHADING', 'GROOM', 'RIG', 'CFX', 'ANIM']

const SIDEBAR_TABS: { id: SidebarTab; label: string; labelEn: string; icon: typeof Star }[] = [
  { id: 'favoris',  label: 'Favoris',  labelEn: 'Favorites', icon: Star },
  { id: 'tous',     label: 'Home',     labelEn: 'Home',      icon: LayoutGrid },
  { id: 'recents',  label: 'Récents',  labelEn: 'Recent',    icon: Clock },
  { id: 'archives', label: 'Archivés', labelEn: 'Archived',  icon: Archive },
]

// ── Token Finder ──────────────────────────────────────────────────────────────

function TokenFinder({ project, onChange }: {
  project:  string
  onChange: (sel: TokenSel) => void
}) {
  const [mode, setMode] = useState<FinderMode>('asset')
  const [sel, setSel]   = useState<TokenSel>(EMPTY_TOKEN_SEL)
  const [open, setOpen] = useState<number | null>(null)
  const [seqs,  setSeqs]  = useState<string[]>([])
  const [shots, setShots] = useState<string[]>([])
  const [nameSug, setNameSug]         = useState<string[]>([])
  const [instSug, setInstSug]         = useState<string[]>([])
  const [varSug,  setVarSug]          = useState<string[]>([])
  const [shotNameSug, setShotNameSug] = useState<string[]>([])
  const rootRef           = useRef<HTMLDivElement>(null)
  const { tr }            = useTr()

  const cls = FINDER_CATEGORY_TO_CLASS[sel.category] ?? ''

  // SHOT: sequences
  useEffect(() => {
    if (!project || mode !== 'shot') { setSeqs([]); return }
    api.getSequences(project).then(d => setSeqs(d.sequences)).catch(() => setSeqs([]))
  }, [project, mode])

  // SHOT: shots for selected SEQ
  useEffect(() => {
    if (!project || mode !== 'shot' || !sel.seq) { setShots([]); return }
    api.getShots(project, sel.seq).then(d => setShots(d.shots.map(s => s.split('/')[1] ?? s))).catch(() => setShots([]))
  }, [project, mode, sel.seq])

  // ASSET: Name = asset folders under the category class (scanned)
  useEffect(() => {
    if (!project || mode !== 'asset' || !sel.category) { setNameSug([]); return }
    let ok = true
    api.suggestTokens({ project, field: 'name', mode: 'asset', class_token: cls })
      .then(d => { if (ok) setNameSug(d.suggestions) }).catch(() => { if (ok) setNameSug([]) })
    return () => { ok = false }
  }, [project, mode, cls, sel.category])

  // ASSET: Instance = subfolders under name/task (scanned)
  useEffect(() => {
    if (!project || mode !== 'asset' || !sel.category || !sel.name || !sel.task) { setInstSug([]); return }
    let ok = true
    api.suggestTokens({ project, field: 'instance', mode: 'asset', class_token: cls, name: sel.name, type_token: sel.task })
      .then(d => { if (ok) setInstSug(d.suggestions) }).catch(() => { if (ok) setInstSug([]) })
    return () => { ok = false }
  }, [project, mode, cls, sel.category, sel.name, sel.task])

  // SHOT: Name = task folders under shot/seq/shot (scanned)
  useEffect(() => {
    if (!project || mode !== 'shot' || !sel.seq || !sel.shot) { setShotNameSug([]); return }
    let ok = true
    api.suggestTokens({ project, field: 'name', mode: 'shot', seq: sel.seq, shot: sel.shot })
      .then(d => { if (ok) setShotNameSug(d.suggestions) }).catch(() => { if (ok) setShotNameSug([]) })
    return () => { ok = false }
  }, [project, mode, sel.seq, sel.shot])

  // Variante = distinct variantes parsed from published files (both modes, scanned)
  useEffect(() => {
    let ok = true
    if (mode === 'asset') {
      if (!project || !sel.category || !sel.name || !sel.task) { setVarSug([]); return }
      api.suggestTokens({ project, field: 'variante', mode: 'asset', class_token: cls, name: sel.name, type_token: sel.task, instance: sel.instance || 'null' })
        .then(d => { if (ok) setVarSug(d.suggestions) }).catch(() => { if (ok) setVarSug([]) })
    } else {
      if (!project || !sel.seq || !sel.shot || !sel.name) { setVarSug([]); return }
      api.suggestTokens({ project, field: 'variante', mode: 'shot', seq: sel.seq, shot: sel.shot, name: sel.name })
        .then(d => { if (ok) setVarSug(d.suggestions) }).catch(() => { if (ok) setVarSug([]) })
    }
    return () => { ok = false }
  }, [project, mode, cls, sel.category, sel.name, sel.task, sel.instance, sel.seq, sel.shot])

  useEffect(() => {
    if (open === null) return
    const h = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(null)
    }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [open])

  const update = (key: keyof TokenSel, value: string) => {
    const next: TokenSel = { ...sel, [key]: value, mode }
    if (key === 'category') next.name = ''   // asset names depend on the category
    if (key === 'seq')      next.shot = ''
    setSel(next); onChange(next); setOpen(null)
  }
  const clear = (key: keyof TokenSel) => {
    const next: TokenSel = { ...sel, [key]: '', mode }
    if (key === 'category') next.name = ''
    if (key === 'seq')      next.shot = ''
    setSel(next); onChange(next); setOpen(null)
  }

  const switchMode = () => {
    const newMode: FinderMode = mode === 'asset' ? 'shot' : 'asset'
    const reset: TokenSel = { ...EMPTY_TOKEN_SEL, mode: newMode }
    setMode(newMode); setSel(reset); onChange(reset); setOpen(null)
  }

  const MODULES: { key: keyof TokenSel; label: string; opts: string[] }[] = mode === 'asset'
    ? [
        { key: 'category', label: tr('CATÉGORIE', 'CATEGORY'), opts: FINDER_CATEGORIES },
        { key: 'name',     label: 'NAME',      opts: nameSug },
        { key: 'task',     label: 'TASK',      opts: FINDER_TASKS },
        { key: 'instance', label: 'INSTANCE',  opts: instSug },
        { key: 'variante', label: 'VARIANTE',  opts: varSug },
      ]
    : [
        { key: 'seq',      label: 'SEQ',       opts: seqs },
        { key: 'shot',     label: 'SHOT',      opts: shots },
        { key: 'name',     label: 'NAME',      opts: shotNameSug },
        { key: 'variante', label: 'VARIANTE',  opts: varSug },
      ]

  return (
    <div style={{ flex: 1, display: 'flex', alignItems: 'stretch', gap: 4, position: 'relative', overflow: 'visible' }}>
      {/* Mode toggle ASSET / SHOT */}
      <div
        onClick={switchMode}
        style={{ flexShrink: 0, height: 30, padding: '0 9px', display: 'flex', alignItems: 'center', border: '1px solid var(--rule-2)', borderRadius: 5, background: mode === 'shot' ? 'var(--accent-soft)' : 'var(--bg-deep)', cursor: 'pointer', fontSize: 10.5, fontFamily: 'var(--mono)', color: mode === 'shot' ? 'var(--accent-hi)' : 'var(--ink-3)', fontWeight: 600, letterSpacing: '0.08em', userSelect: 'none', boxShadow: 'var(--shadow-xs)' }}
      >
        {mode === 'asset' ? 'ASSET' : 'SHOT'}
      </div>

      <div
        ref={rootRef}
        style={{ flex: 1, display: 'flex', border: '1px solid var(--rule-2)', borderRadius: 5, background: 'var(--bg-deep)', boxShadow: 'var(--shadow-inset)', position: 'relative', overflow: 'visible' }}
      >
      {MODULES.map(({ key, label, opts }, i) => {
        const value  = sel[key]
        const isOpen = open === i
        return (
          <div key={`${mode}-${i}`} style={{ flex: 1, position: 'relative', borderLeft: i > 0 ? '1px solid var(--rule-2)' : 'none' }}>
            <div
              onClick={() => setOpen(isOpen ? null : i)}
              style={{ height: 30, padding: '0 6px', display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 1, cursor: 'pointer', background: value ? 'var(--accent-soft)' : 'transparent', transition: 'background 0.08s', borderRadius: i === 0 ? '4px 0 0 4px' : i === MODULES.length - 1 ? '0 4px 4px 0' : 0 }}
            >
              <span style={{ fontSize: 9, color: 'var(--ink-4)', textTransform: 'uppercase', letterSpacing: '0.1em', lineHeight: 1 }}>{label}</span>
              <span style={{ fontSize: 10.5, fontFamily: 'var(--mono)', color: value ? 'var(--accent-hi)' : 'var(--ink-4)', fontWeight: value ? 600 : 400, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', lineHeight: 1.3 }}>
                {value || '-'}
              </span>
            </div>
            {isOpen && (
              <div style={{ position: 'absolute', top: 'calc(100% + 3px)', left: 0, zIndex: 500, minWidth: 110, background: 'var(--paper)', border: '1px solid var(--rule-2)', borderRadius: 5, boxShadow: 'var(--shadow)', overflow: 'hidden' }}>
                {value && (
                  <div onClick={() => clear(key)} style={{ padding: '5px 8px', fontSize: 10.5, fontFamily: 'var(--mono)', color: 'var(--ink-4)', borderBottom: '1px solid var(--rule)', cursor: 'pointer' }}>
                    {tr('effacer', 'clear')}
                  </div>
                )}
                {opts.length === 0 ? (
                  <div style={{ padding: '6px 8px', fontSize: 10.5, color: 'var(--ink-4)', fontStyle: 'italic' }}>
                    {project ? tr('Vide', 'Empty') : tr('Projet requis', 'Project required')}
                  </div>
                ) : opts.map(o => (
                  <div
                    key={o}
                    onClick={() => update(key, o)}
                    style={{ padding: '5px 8px', fontSize: 10.5, fontFamily: 'var(--mono)', color: o === value ? 'var(--accent-hi)' : 'var(--ink-2)', background: o === value ? 'var(--accent-soft)' : 'transparent', cursor: 'pointer', whiteSpace: 'nowrap' }}
                  >
                    {o}
                  </div>
                ))}
              </div>
            )}
          </div>
        )
      })}
      </div>
    </div>
  )
}

// ── Context Menu ──────────────────────────────────────────────────────────────


// ── Hard-Delete Project Modal (typed confirmation) ────────────────────────────

// Exact, case-sensitive phrase the user must type before a project can be deleted.
const DELETE_PROJECT_PHRASE = 'yes DELETE it'

function DeleteProjectModal({ project, onConfirm, onCancel }: {
  project:   string
  onConfirm: () => void
  onCancel:  () => void
}) {
  const [typed, setTyped] = useState('')
  const match = typed === DELETE_PROJECT_PHRASE
  const { tr } = useTr()

  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onCancel() }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [onCancel])

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)', zIndex: 2000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ background: 'var(--paper)', border: '1px solid var(--rule-2)', borderRadius: 10, padding: '22px 24px', minWidth: 340, maxWidth: 420, boxShadow: 'var(--shadow)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
          <Trash2 size={16} strokeWidth={1.75} color="var(--err)" />
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)' }}>
            {tr(`Supprimer le projet «\u00a0${project}\u00a0» ?`, `Delete project "${project}"?`)}
          </div>
        </div>
        <div style={{ fontSize: 11, color: 'var(--ink-3)', marginBottom: 16, lineHeight: 1.5 }}>
          {tr('Le dossier du projet et tout son contenu seront retirés définitivement du workspace. Cette action est irréversible.',
            'The project folder and all its contents will be permanently removed from the workspace. This cannot be undone.')}
        </div>
        <div style={{ fontSize: 11, color: 'var(--ink-2)', marginBottom: 8, lineHeight: 1.5 }}>
          {tr('Tape', 'Type')}{' '}
          <code style={{ fontFamily: 'var(--mono)', fontSize: 11, background: 'var(--paper-2)', border: '1px solid var(--rule)', borderRadius: 4, padding: '1px 5px', color: 'var(--ink)' }}>
            {DELETE_PROJECT_PHRASE}
          </code>{' '}
          {tr('pour confirmer.', 'to confirm.')}
        </div>
        <input
          autoFocus
          value={typed}
          onChange={e => setTyped(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && match) onConfirm() }}
          placeholder={DELETE_PROJECT_PHRASE}
          spellCheck={false}
          autoCapitalize="off"
          autoCorrect="off"
          style={{
            width: '100%', boxSizing: 'border-box', marginBottom: 20,
            padding: '7px 10px', fontSize: 12, fontFamily: 'var(--mono)',
            background: 'var(--paper-2)', color: 'var(--ink)',
            border: `1px solid ${match ? 'var(--err)' : 'var(--rule-2)'}`, borderRadius: 6, outline: 'none',
          }}
        />
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <div className="btn ghost" onClick={onCancel} style={{ cursor: 'pointer' }}>{tr('Annuler', 'Cancel')}</div>
          <div
            className="btn primary"
            onClick={() => { if (match) onConfirm() }}
            style={{
              cursor: match ? 'pointer' : 'not-allowed',
              background: match ? 'var(--err)' : 'var(--rule-2)',
              borderColor: match ? 'var(--err)' : 'var(--rule-2)',
              opacity: match ? 1 : 0.5,
            }}
          >
            {tr('Supprimer', 'Delete')}
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Archives browser (physical PROJECT/ARCHIVE/ folder, shared) ───────────────
// The "Archivés" tab shows the real on-disk ARCHIVE folder each project holds
// (where Production's delete-as-archive moves entities), not a per-user bookmark
// list. Read-only browsing; "Ouvrir" jumps into the main explorer at that path.
function ArchivesBrowser({ onOpen }: { onOpen: (project: string, subpath: string[]) => void }) {
  const [projects, setProjects] = useState<string[]>([])
  const [cur, setCur]           = useState<{ project: string; sub: string[] } | null>(null)
  const [entries, setEntries]   = useState<ExplorerItem[]>([])
  const [loading, setLoading]   = useState(false)
  const [err, setErr]           = useState('')
  // Permanent-delete selection (only inside a project's ARCHIVE folder).
  const [selected, setSelected]   = useState<Set<string>>(new Set())
  const [confirming, setConfirming] = useState(false)
  const [deleting, setDeleting]   = useState(false)
  const { tr } = useTr()

  useEffect(() => {
    let ok = true
    api.getProjects().then(d => { if (ok) setProjects(d.projects) }).catch(() => { if (ok) setProjects([]) })
    return () => { ok = false }
  }, [])

  useEffect(() => {
    // Reset the delete selection whenever we change folder.
    setSelected(new Set())
    setConfirming(false)
    if (!cur) { setEntries([]); return }
    let ok = true
    setLoading(true); setErr('')
    api.browseProject(cur.project, cur.sub.join('/'))
      .then(d => {
        if (!ok) return
        setEntries([
          ...d.folders.map(f => ({ name: f.name, isDir: true })),
          ...(d.files ?? []).map(f => ({ name: f.name, isDir: false })),
        ])
      })
      .catch(() => { if (ok) { setEntries([]); setErr(trNow('Aucune archive pour ce projet.', 'No archive for this project.')) } })
      .finally(() => { if (ok) setLoading(false) })
    return () => { ok = false }
  }, [cur])

  const _hdr: React.CSSProperties = {
    padding: '7px 12px', borderBottom: '1px solid var(--rule)', flexShrink: 0,
    background: 'var(--paper-2)', fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-4)',
    display: 'flex', alignItems: 'center', gap: 8,
  }
  const _row: React.CSSProperties = {
    display: 'flex', alignItems: 'center', gap: 10, padding: '7px 8px', borderRadius: 6,
    cursor: 'pointer', marginBottom: 2, border: '1px solid transparent',
  }

  // Project list (each project's ARCHIVE root).
  if (!cur) {
    return (
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
        <div style={_hdr}>{tr(`ARCHIVÉS · ${projects.length} projet${projects.length > 1 ? 's' : ''}`, `ARCHIVED · ${projects.length} project${projects.length > 1 ? 's' : ''}`)}</div>
        <div style={{ flex: 1, overflowY: 'auto', padding: '6px 8px' }}>
          {projects.length === 0 ? (
            <div style={{ padding: '20px 12px', textAlign: 'center', color: 'var(--ink-4)', fontSize: 11, fontStyle: 'italic' }}>{tr('Aucun projet', 'No projects')}</div>
          ) : projects.map(p => (
            <div
              key={p}
              onClick={() => setCur({ project: p, sub: ['ARCHIVE'] })}
              style={_row}
              onMouseEnter={e => (e.currentTarget.style.background = 'var(--accent-soft)')}
              onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
            >
              <Archive size={18} strokeWidth={1.75} color="var(--ink-3)" />
              <span style={{ fontSize: 11, color: 'var(--ink)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p}</span>
            </div>
          ))}
        </div>
      </div>
    )
  }

  const goUp = () => {
    if (cur.sub.length <= 1) setCur(null)                                   // back to project list
    else setCur({ project: cur.project, sub: cur.sub.slice(0, -1) })
  }
  const relStr = cur.sub.slice(1).join('/')   // hide the leading "ARCHIVE"

  const toggle = (name: string) => {
    setConfirming(false)
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  // Permanent hard-delete of the selected archive entries (backend is
  // Windows-safe: force_rmtree/force_remove). Two-step confirm before firing.
  const doDelete = async () => {
    if (selected.size === 0 || deleting) return
    setDeleting(true)
    try {
      for (const name of selected) {
        await api.deleteItem(cur.project, cur.sub, name)
      }
      const removed = selected.size
      setSelected(new Set())
      setConfirming(false)
      // Reload the current folder.
      const d = await api.browseProject(cur.project, cur.sub.join('/'))
      setEntries([
        ...d.folders.map(f => ({ name: f.name, isDir: true })),
        ...(d.files ?? []).map(f => ({ name: f.name, isDir: false })),
      ])
      toast.success(tr(`${removed} élément${removed > 1 ? 's' : ''} supprimé${removed > 1 ? 's' : ''}`, `${removed} item${removed > 1 ? 's' : ''} deleted`))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : tr('Suppression échouée', 'Delete failed'))
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <div style={_hdr}>
        <span onClick={goUp} style={{ cursor: 'pointer', color: 'var(--accent-hi)' }}>{tr('‹ Retour', '‹ Back')}</span>
        <span style={{ color: 'var(--ink-2)' }}>{cur.project}</span>
        {relStr && <span style={{ color: 'var(--ink-4)' }}>/ {relStr}</span>}
      </div>
      {selected.size > 0 && (
        <div style={{ flexShrink: 0, display: 'flex', alignItems: 'center', gap: 10, padding: '6px 12px', borderBottom: '1px solid var(--rule)', background: 'var(--paper-2)' }}>
          <span style={{ fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--ink-3)' }}>
            {tr(`${selected.size} sélectionné${selected.size > 1 ? 's' : ''}`, `${selected.size} selected`)}
          </span>
          <span style={{ flex: 1 }} />
          {confirming ? (
            <>
              <span
                onClick={() => !deleting && setConfirming(false)}
                style={{ fontSize: 11, color: 'var(--ink-3)', cursor: 'pointer', padding: '3px 8px' }}
              >{tr('Annuler', 'Cancel')}</span>
              <span
                onClick={doDelete}
                style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--danger, #d05a5a)', cursor: deleting ? 'default' : 'pointer', padding: '3px 8px', border: '1px solid var(--danger, #d05a5a)', borderRadius: 4, opacity: deleting ? 0.6 : 1 }}
              >
                <Trash2 size={11} strokeWidth={1.75} /> {deleting ? tr('Suppression…', 'Deleting…') : tr('Confirmer la suppression définitive', 'Confirm permanent delete')}
              </span>
            </>
          ) : (
            <span
              onClick={() => setConfirming(true)}
              style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--ink-2)', cursor: 'pointer', padding: '3px 8px', border: '1px solid var(--rule-2)', borderRadius: 4 }}
            >
              <Trash2 size={11} strokeWidth={1.75} /> {tr('Supprimer', 'Delete')}
            </span>
          )}
        </div>
      )}
      <div style={{ flex: 1, overflowY: 'auto', padding: '6px 8px' }}>
        {loading ? (
          <div style={{ padding: '20px 12px', textAlign: 'center', color: 'var(--ink-4)', fontSize: 11, fontStyle: 'italic' }}>{tr('Chargement…', 'Loading…')}</div>
        ) : err ? (
          <div style={{ padding: '20px 12px', textAlign: 'center', color: 'var(--ink-4)', fontSize: 11, fontStyle: 'italic' }}>{err}</div>
        ) : entries.length === 0 ? (
          <div style={{ padding: '20px 12px', textAlign: 'center', color: 'var(--ink-4)', fontSize: 11, fontStyle: 'italic' }}>{tr('Vide', 'Empty')}</div>
        ) : entries.map((it, i) => {
          const isSel = selected.has(it.name)
          return (
          <div
            key={i}
            onClick={() => { if (it.isDir) setCur({ project: cur.project, sub: [...cur.sub, it.name] }) }}
            style={{ ..._row, cursor: it.isDir ? 'pointer' : 'default', background: isSel ? 'var(--accent-soft)' : 'transparent', border: isSel ? '1px solid var(--rule-3)' : '1px solid transparent' }}
            onMouseEnter={e => (e.currentTarget.style.background = 'var(--accent-soft)')}
            onMouseLeave={e => (e.currentTarget.style.background = isSel ? 'var(--accent-soft)' : 'transparent')}
          >
            <input
              type="checkbox"
              checked={isSel}
              onClick={e => e.stopPropagation()}
              onChange={() => toggle(it.name)}
              style={{ flexShrink: 0, accentColor: 'var(--accent)', cursor: 'pointer' }}
            />
            {it.isDir ? <FolderSvg size={22} /> : <div style={{ width: 22, textAlign: 'center', color: 'var(--ink-4)', fontSize: 12 }}>·</div>}
            <span style={{ flex: 1, fontSize: 11, color: 'var(--ink)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{it.name}</span>
            <span
              onClick={e => { e.stopPropagation(); onOpen(cur.project, it.isDir ? [...cur.sub, it.name] : cur.sub) }}
              title={tr("Ouvrir dans l'explorateur", 'Open in the explorer')}
              style={{ flexShrink: 0, fontSize: 10.5, fontFamily: 'var(--mono)', color: 'var(--accent-hi)', cursor: 'pointer', padding: '2px 6px', border: '1px solid var(--rule-2)', borderRadius: 4 }}
            >{tr('Ouvrir', 'Open')}</span>
          </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Saved Items List (Favoris / Récents / Archivés) ───────────────────────────

function SavedList({ items, label, emptyMsg, removeLabel, onNavigate, onRemove, onDeleteProject }: {
  items:            SavedItem[]
  label:            string
  emptyMsg:         string
  removeLabel:      string   // ex: "Désarchiver", "Retirer des Favoris", "Retirer"
  onNavigate:       (s: SavedItem) => void
  onRemove:         (s: SavedItem) => void
  onDeleteProject?: (s: SavedItem) => void   // Archives only: hard-delete a project root
}) {
  // A root-level project is identified by project === label && empty subpath.
  const isProjectRoot = (s: SavedItem) => s.project === s.label && s.subpath.length === 0
  const [ctx, setCtx] = useState<{ x: number; y: number; item: SavedItem } | null>(null)
  const { tr } = useTr()

  useEffect(() => {
    if (!ctx) return
    const h = () => setCtx(null)
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [ctx])

  const menuRow = (lbl: string, danger: boolean, cb: () => void) => (
    <div
      onClick={cb}
      style={{ padding: '6px 12px', fontSize: 11, cursor: 'pointer', color: danger ? 'var(--err)' : 'var(--ink-2)', transition: 'background 0.06s' }}
      onMouseEnter={e => { e.currentTarget.style.background = 'var(--accent-soft)' }}
      onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
    >
      {lbl}
    </div>
  )

  return (
    <>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
        <div style={{ padding: '7px 12px', borderBottom: '1px solid var(--rule)', flexShrink: 0, background: 'var(--paper-2)', fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-4)' }}>
          {label} · {items.length === 0 ? emptyMsg : tr(`${items.length} élément${items.length > 1 ? 's' : ''}`, `${items.length} item${items.length > 1 ? 's' : ''}`)}
        </div>
        <div style={{ flex: 1, overflowY: 'auto', padding: '6px 8px' }}>
          {items.length === 0 ? (
            <div style={{ padding: '20px 12px', textAlign: 'center', color: 'var(--ink-4)', fontSize: 11, fontStyle: 'italic' }}>
              {emptyMsg}
            </div>
          ) : items.map((s, i) => (
            <div
              key={i}
              onClick={() => onNavigate(s)}
              onContextMenu={e => { e.preventDefault(); e.stopPropagation(); setCtx({ x: e.clientX, y: e.clientY, item: s }) }}
              style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 8px', borderRadius: 6, cursor: 'pointer', marginBottom: 2, border: '1px solid transparent', transition: 'background 0.08s' }}
              onMouseEnter={e => (e.currentTarget.style.background = 'var(--accent-soft)')}
              onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
            >
              {s.isDir ? <FolderSvg size={24} /> : <FileSvg size={20} ext={getExt(s.label)} />}
              <div style={{ minWidth: 0, flex: 1 }}>
                <div title={s.label} style={{ fontSize: 11, fontWeight: 500, color: 'var(--ink)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{s.label}</div>
                <div style={{ fontSize: 10.5, fontFamily: 'var(--mono)', color: 'var(--ink-4)', marginTop: 1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {s.project}{s.subpath.length > 0 ? ' / ' + s.subpath.join(' / ') : ''}
                </div>
              </div>
              <div
                onClick={e => { e.stopPropagation(); onRemove(s) }}
                style={{ flexShrink: 0, padding: 4, borderRadius: 4, color: 'var(--ink-4)', cursor: 'pointer', opacity: 0.6 }}
                onMouseEnter={e => { e.currentTarget.style.opacity = '1'; e.currentTarget.style.color = 'var(--err)' }}
                onMouseLeave={e => { e.currentTarget.style.opacity = '0.6'; e.currentTarget.style.color = 'var(--ink-4)' }}
              >
                <X size={10} strokeWidth={2} />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Context menu clic-droit */}
      {ctx && (
        <div
          onMouseDown={e => e.stopPropagation()}
          style={{ position: 'fixed', top: ctx.y, left: ctx.x, zIndex: 1000, background: 'var(--paper)', border: '1px solid var(--rule-2)', borderRadius: 7, boxShadow: 'var(--shadow)', minWidth: 170, overflow: 'hidden', paddingBlock: 4 }}
        >
          {menuRow(tr('Ouvrir', 'Open'), false, () => { onNavigate(ctx.item); setCtx(null) })}
          {menuRow(removeLabel, false, () => { onRemove(ctx.item); setCtx(null) })}
          {onDeleteProject && isProjectRoot(ctx.item) && (
            <>
              <div style={{ height: 1, background: 'var(--rule)', margin: '4px 0' }} />
              {menuRow(tr('Supprimer définitivement', 'Delete permanently'), true, () => { onDeleteProject(ctx.item); setCtx(null) })}
            </>
          )}
        </div>
      )}
    </>
  )
}

// ── Composant principal ───────────────────────────────────────────────────────
//
// The page owns what every view shares: sidebar (saved lists, presets, tile size),
// Token Finder, creation tabs, right panel, clipboard, undo and the drag payload.
// Each explorer view (ExplorerPane) browses on its own; the active one (last
// clicked) drives the right panel, the active project and the Token Finder.

export function Projects() {
  // Active project + list come from the shared ProjectContext. Navigating into a
  // project (in the active view) makes it the active project everywhere.
  const { project: activeProject, projects, setProject: setActiveProject, refreshProjects } = useProject()
  const { settings } = useSettings()
  const dccStatus = useDccStatus()
  const location = useLocation()
  const { tr } = useTr()

  // ── Views (B2) ─────────────────────────────────────────────────────────────

  const [layout, changeLayout] = useLocalPref<PaneLayout>(LAYOUT_KEY, 'single', ['single', 'stacked', 'side', 'quad'])
  const [showSetupValue, setShowSetupValue] = useLocalPref(SHOW_SETUP_KEY, 'hidden', ['hidden', 'shown'])
  const showSetup = showSetupValue === 'shown'
  const paneCount = PANE_COUNT[layout]
  const [activePane, setActivePane] = useSessionState('fm.activePane', 0)
  const activeIdx = Math.min(activePane, paneCount - 1)
  const paneRefs = useRef<(PaneHandle | null)[]>([])

  const [reports, setReports] = useState<Record<number, PaneReport>>({})
  const onReport = useCallback((id: number, r: PaneReport) => setReports(prev => ({ ...prev, [id]: r })), [])
  const report = reports[activeIdx] ?? EMPTY_REPORT
  const nav: NavLevel = report.nav
  const navProject: string = nav.kind === 'inside' ? nav.project : ''
  const navigateActive = useCallback((level: NavLevel) => paneRefs.current[activeIdx]?.navigateTo(level), [activeIdx])

  // Deep link from another page (Production, USD, Activity): open in the active view.
  useEffect(() => {
    const openPath = (location.state as { openPath?: string } | null)?.openPath
    if (!openPath || !settings?.workspace) return
    const level = resolveOpenPath(openPath, settings.workspace)
    if (level) navigateActive(level)
  }, [settings?.workspace]) // eslint-disable-line react-hooks/exhaustive-deps

  // Exploring a project makes it the active project everywhere (shared context).
  useEffect(() => {
    if (navProject && navProject !== activeProject) setActiveProject(navProject)
  }, [navProject])  // eslint-disable-line react-hooks/exhaustive-deps

  const [sidebarTab, setSidebarTab] = useSessionState<SidebarTab>('fm.sidebarTab', 'tous')

  // Explorer tile size (small / medium / large), persisted per browser; Ctrl + wheel steps it.
  const [tileSize, changeTileSize] = useLocalPref<TileSize>(TILE_SIZE_KEY, 'md', TILE_ORDER)
  const viewsRef = useRef<HTMLDivElement>(null)
  const tileSizeRef = useRef(tileSize)
  tileSizeRef.current = tileSize
  useEffect(() => {
    const node = viewsRef.current
    if (!node) return
    const wheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return
      e.preventDefault()
      const i = TILE_ORDER.indexOf(tileSizeRef.current) + (e.deltaY < 0 ? 1 : -1)
      if (i >= 0 && i < TILE_ORDER.length) changeTileSize(TILE_ORDER[i])
    }
    node.addEventListener('wheel', wheel, { passive: false })
    return () => node.removeEventListener('wheel', wheel)
  }, [changeTileSize])

  // Preset quick-drop (RETAKES-3): the linked presets of the active view's project.
  const [presets, setPresets]     = useState<Preset[]>([])

  // Saved lists — persisted per-user on the Flux drive (USER/<user>/UserSettings/User.json)
  const [favorites, setFavorites] = useState<SavedItem[]>([])
  const [archived,  setArchived]  = useState<SavedItem[]>([])
  const [recents,   setRecents]   = useState<SavedItem[]>([])
  const savedLoaded = useRef(false)

  const [deleteProjectTarget, setDeleteProjectTarget] = useState<SavedItem | null>(null)

  // Token Finder
  const [tokenSel, setTokenSel]           = useState<TokenSel>(EMPTY_TOKEN_SEL)
  const [projectTokens, setProjectTokens] = useState<Record<string, Record<string, string>>>({})
  const [findLoading, setFindLoading]     = useState(false)

  // Clipboard, undo, drag payload and disk refresh, shared by every view
  const [clipboard, setClipboard] = useState<Clip | null>(null)
  const [undoStack, setUndoStack] = useState<UndoOp[]>([])
  const [fsTick, setFsTick]       = useState(0)
  const bumpFs = useCallback(() => setFsTick(t => t + 1), [])
  const dragRef = useRef<DragPayload | null>(null)

  // ── Persist saved lists ────────────────────────────────────────────────────

  // Load saved lists once from the per-user store
  useEffect(() => {
    api.getUserData().then(d => {
      const fm = (d.folder_manager ?? {}) as { favorites?: SavedItem[]; archived?: SavedItem[]; recents?: SavedItem[] }
      if (Array.isArray(fm.favorites)) setFavorites(fm.favorites)
      if (Array.isArray(fm.archived))  setArchived(fm.archived)
      if (Array.isArray(fm.recents))   setRecents(fm.recents)
    }).catch(() => {}).finally(() => { savedLoaded.current = true })
  }, [])

  // Persist (debounced) after the initial load, so empty state never overwrites the store
  useEffect(() => {
    if (!savedLoaded.current) return
    const t = setTimeout(() => {
      void api.setUserData({ folder_manager: { favorites, archived, recents } }).catch(() => {})
    }, 400)
    return () => clearTimeout(t)
  }, [favorites, archived, recents])

  // ── Saved-list helpers ─────────────────────────────────────────────────────

  const toggleIn = (setter: typeof setFavorites) => (item: ExplorerItem, at: NavLevel) => {
    const s = makeSavedItem(item, at)
    const k = savedKey(s)
    setter(prev => prev.some(x => savedKey(x) === k) ? prev.filter(x => savedKey(x) !== k) : [s, ...prev])
  }
  const toggleFavorite = useCallback(toggleIn(setFavorites), [])  // eslint-disable-line react-hooks/exhaustive-deps
  const toggleArchived = useCallback(toggleIn(setArchived), [])   // eslint-disable-line react-hooks/exhaustive-deps

  const addToRecents = useCallback((item: ExplorerItem, at: NavLevel) => {
    const s = makeSavedItem(item, at)
    const k = savedKey(s)
    setRecents(prev => [s, ...prev.filter(x => savedKey(x) !== k)].slice(0, 20))
  }, [])

  // An item moved or deleted leaves the favorites / recents (and the archives on delete).
  const forgetSaved = useCallback((keys: string[], alsoArchived = false) => {
    const drop = (list: SavedItem[]) => list.filter(s => !keys.includes(savedKey(s)))
    setFavorites(drop)
    setRecents(drop)
    if (alsoArchived) setArchived(drop)
  }, [])

  const renameSaved = useCallback((oldKey: string, newName: string) => {
    const ren = (list: SavedItem[]) => list.map(s => savedKey(s) === oldKey ? { ...s, label: newName } : s)
    setFavorites(ren)
    setRecents(ren)
  }, [])

  const removeFromSaved = useCallback((s: SavedItem, list: 'favorites' | 'archived' | 'recents') => {
    const k = savedKey(s)
    if (list === 'favorites') setFavorites(prev => prev.filter(x => savedKey(x) !== k))
    if (list === 'archived')  setArchived(prev  => prev.filter(x => savedKey(x) !== k))
    if (list === 'recents')   setRecents(prev   => prev.filter(x => savedKey(x) !== k))
  }, [])

  const navigateToSaved = useCallback((s: SavedItem) => {
    navigateActive(navigateTargetFor(s))
    setSidebarTab('tous')
  }, [navigateActive, setSidebarTab])

  // ── Undo + move / copy (drag & drop, paste, "Déplacer") ─────────────────────

  const pushUndo = useCallback((op: UndoOp) => {
    if (op.actions.length === 0) return
    setUndoStack(prev => [...prev, op].slice(-50))
  }, [])

  const undoLast = useCallback(async () => {
    const op = undoStack[undoStack.length - 1]
    if (!op) { toast(trNow('Rien à annuler', 'Nothing to undo')); return }
    setUndoStack(prev => prev.slice(0, -1))
    let ok = 0
    for (const a of [...op.actions].reverse()) {
      try {
        if (a.kind === 'move')        await api.patchItem(a.project, a.toSub, a.name, undefined, a.fromSub)
        else if (a.kind === 'rename') await api.patchItem(a.project, a.sub, a.newName, a.oldName)
        else if (a.kind === 'copy')   await api.deleteItem(a.project, a.sub, a.name)
        ok++
      } catch (e) {
        toast.error(trNow(`Annulation : ${e instanceof Error ? e.message : 'échec'}`, `Undo: ${e instanceof Error ? e.message : 'failed'}`))
      }
    }
    if (ok > 0) { toast.success(trNow(`Annulé : ${op.label}`, `Undone: ${op.label}`)); bumpFs() }
  }, [undoStack, bumpFs])

  // One path for every move / copy, inside a view or from one view to another.
  const transfer = useCallback(async (src: TransferSource, dest: TransferDest, op: 'move' | 'copy'): Promise<number> => {
    if (src.names.length === 0) return 0
    if (src.project !== dest.project) { toast.error(trNow('Déplacement / copie entre projets non supporté', 'Move / copy between projects is not supported')); return 0 }
    const srcKey  = src.subpath.join('/')
    const destKey = dest.subpath.join('/')
    if (op === 'move' && srcKey === destKey) return 0   // same folder → no-op
    // The backend reads an empty destination as "keep the parent": no move to the project root.
    if (op === 'move' && dest.subpath.length === 0) {
      toast.error(trNow('Déplacer à la racine du projet : pas encore possible (copier fonctionne)', 'Moving to the project root is not possible yet (copy works)'))
      return 0
    }
    const into = src.names.find(n => (destKey + '/').startsWith([...src.subpath, n].join('/') + '/'))
    if (into) { toast.error(trNow(`"${into}" ne peut pas aller dans son propre dossier`, `"${into}" cannot go into its own folder`)); return 0 }
    let names = src.names
    if (op === 'move' && src.locked?.size) {
      names = names.filter(n => !src.locked!.has(n))
      if (names.length < src.names.length) toast.error(trNow(`${src.names.length - names.length} verrouillé(s) : non déplacé(s)`, `${src.names.length - names.length} locked: not moved`))
      if (names.length === 0) return 0
    }
    // Copy: free name in the destination ("x (2).ext").
    const existing = new Set<string>()
    if (op === 'copy') {
      try {
        const d = await api.browseProject(dest.project, destKey || undefined)
        for (const f of d.folders) existing.add(f.name)
        for (const f of d.files ?? []) existing.add(f.name)
      } catch { /* destination listed empty: the backend still refuses an overwrite */ }
    }
    const undoActions: UndoAction[] = []
    const moved: string[] = []
    let ok = 0
    for (const name of names) {
      try {
        if (op === 'move') {
          await api.patchItem(src.project, src.subpath, name, undefined, dest.subpath)
          undoActions.push({ kind: 'move', project: src.project, fromSub: src.subpath, toSub: dest.subpath, name })
          moved.push(itemKey(src.project, src.subpath, name))
        } else {
          const target = uniqueName(name, existing)
          await api.copyItem(src.project, src.subpath, name, dest.subpath, target === name ? undefined : target)
          undoActions.push({ kind: 'copy', project: dest.project, sub: dest.subpath, name: target })
          existing.add(target)
        }
        ok++
      } catch (e) {
        toast.error(trNow(`${name} : ${e instanceof Error ? e.message : 'échec'}`, `${name}: ${e instanceof Error ? e.message : 'failed'}`))
      }
    }
    if (moved.length) forgetSaved(moved)
    pushUndo({ label: op === 'move'
      ? trNow(`déplacement (${undoActions.length})`, `move (${undoActions.length})`)
      : trNow(`copie (${undoActions.length})`, `copy (${undoActions.length})`), actions: undoActions })
    if (ok > 0) {
      toast.success(trNow(`${ok} élément(s) ${op === 'move' ? 'déplacé(s)' : 'copié(s)'}`, `${ok} item(s) ${op === 'move' ? 'moved' : 'copied'}`))
      bumpFs()
    }
    return ok
  }, [forgetSaved, pushUndo, bumpFs])

  const shared: FolderManagerShared = useMemo(() => ({
    workspace: settings?.workspace,
    tileSize, dccStatus, favorites, archived,
    toggleFavorite, toggleArchived, addToRecents, forgetSaved, renameSaved,
    clipboard, setClipboard, pushUndo, undoLast,
    fsTick, bumpFs, dragRef, transfer, showSetup,
  }), [settings?.workspace, tileSize, dccStatus, favorites, archived, toggleFavorite, toggleArchived, addToRecents,
       forgetSaved, renameSaved, clipboard, pushUndo, undoLast, fsTick, bumpFs, transfer, showSetup])

  // ── Presets (quick-drop into the active view's folder) ──────────────────────
  // Reload the project's presets when entering a project, and whenever the
  // Template Editor edits them (global flux:refresh event).
  const loadPresets = useCallback(async () => {
    if (!navProject) { setPresets([]); return }
    try { const d = await api.listPresets(navProject); setPresets(d.presets) }
    catch { setPresets([]) }
  }, [navProject])

  useEffect(() => { void loadPresets() }, [loadPresets])

  useEffect(() => {
    const onRefresh = () => void loadPresets()
    window.addEventListener('flux:refresh', onRefresh)
    return () => window.removeEventListener('flux:refresh', onRefresh)
  }, [loadPresets])

  // Drop a preset's linked file into the folder the active view shows.
  const dropPresetHere = useCallback(async (p: Preset) => {
    if (nav.kind !== 'inside') return
    try {
      const r = await api.dropPreset(nav.project, p.id, nav.subpath.join('/'))
      toast.success(trNow(`${r.name} déposé ici`, `${r.name} dropped here`))
      bumpFs()
    } catch (e) {
      toast.error(trNow(`Dépôt : ${e instanceof Error ? e.message : 'échec'}`, `Drop: ${e instanceof Error ? e.message : 'failed'}`))
    }
  }, [nav, bumpFs])

  // Fetch tokens.json for the active/nav project whenever project or tick changes
  const tokensProject = navProject || activeProject
  useEffect(() => {
    if (!tokensProject) { setProjectTokens({}); return }
    api.getTokens(tokensProject).then(d => setProjectTokens(d.tokens)).catch(() => setProjectTokens({}))
  }, [tokensProject])

  // ── Token Finder (results shown in the active view) ─────────────────────────

  const handleFind = useCallback(async () => {
    const proj = navProject || activeProject
    const pane = paneRefs.current[activeIdx]
    if (!proj || !pane) return
    const label = tokenSel.mode === 'shot' ? 'Shot Finder' : 'Finder'
    setFindLoading(true)
    pane.showFind(label, [], true)
    const results: FindResult[] = []

    const classTokens    = projectTokens.CLASS    ?? {}
    const typeTokens     = projectTokens.TYPE      ?? {}

    if (tokenSel.mode === 'shot') {
      const seqList = tokenSel.seq
        ? [tokenSel.seq]
        : await api.getSequences(proj).then(d => d.sequences).catch(() => [] as string[])

      for (const seq of seqList) {
        const shotList = tokenSel.shot
          ? [tokenSel.shot]
          : await api.getShots(proj, seq).then(d => d.shots.map(s => s.split('/')[1] ?? s)).catch(() => [] as string[])
        for (const shot of shotList) {
          const base = ['shot', seq, shot]
          if (tokenSel.name) {
            // Resolve via CLASS token template (e.g. "shot/{seq}/{shot}/anim")
            const template = classTokens[tokenSel.name]
            if (template) {
              const subpath = template.replace('{seq}', seq).replace('{shot}', shot).split('/')
              results.push({ label: `${seq} / ${shot} / ${tokenSel.name}`, pathStr: subpath.join(' / '), project: proj, subpath, isDir: true })
            } else {
              const sub = tokenSel.name.toLowerCase()
              results.push({ label: `${seq} / ${shot} / ${sub}`, pathStr: [...base, sub].join(' / '), project: proj, subpath: [...base, sub], isDir: true })
            }
          } else {
            results.push({ label: `${seq} / ${shot}`, pathStr: base.join(' / '), project: proj, subpath: base, isDir: true })
          }
        }
      }
    } else {
      // Category → CLASS token; if none, search every asset class
      const mappedCls = tokenSel.category ? (FINDER_CATEGORY_TO_CLASS[tokenSel.category] ?? '') : ''
      const assetClassKeys = Object.keys(classTokens).filter(k => !classTokens[k].includes('{seq}'))
      const classes = mappedCls ? [mappedCls] : assetClassKeys
      const nameLow = tokenSel.name.toLowerCase()

      for (const c of classes) {
        const classRelPath = classTokens[c]
        if (!classRelPath) continue
        const basePath = classRelPath.split('/')
        let folders: { name: string }[] = []
        try {
          const d = await api.browseProject(proj, basePath.join('/'))
          folders = d.folders
        } catch { continue }

        const matching = nameLow ? folders.filter(f => f.name.toLowerCase().includes(nameLow)) : folders

        for (const folder of matching) {
          const assetPath = [...basePath, folder.name]
          if (tokenSel.task) {
            // Task → TYPE subfolder (coarse token, e.g. GEO → model)
            const subfolder = typeTokens[tokenSel.task] || tokenSel.task.toLowerCase()
            const taskPath = [...assetPath, ...subfolder.split('/')]
            if (tokenSel.instance) {
              const p = [...taskPath, tokenSel.instance]
              results.push({ label: `${folder.name} / ${tokenSel.task} / ${tokenSel.instance}`, pathStr: p.join(' / '), project: proj, subpath: p, isDir: true })
            } else {
              results.push({ label: `${folder.name} / ${tokenSel.task}`, pathStr: taskPath.join(' / '), project: proj, subpath: taskPath, isDir: true })
            }
          } else {
            results.push({ label: folder.name, pathStr: assetPath.join(' / '), project: proj, subpath: assetPath, isDir: true })
          }
        }
      }
    }

    pane.showFind(label, results, false)
    setFindLoading(false)
  }, [tokenSel, navProject, activeProject, projectTokens, activeIdx])

  // Hard-delete a whole project from the Archives view (after typed confirmation).
  const handleDeleteProject = useCallback(async (s: SavedItem) => {
    const name = s.project
    try {
      await api.deleteProject(name)
      const purge = (list: SavedItem[]) => list.filter(x => x.project !== name)
      setArchived(purge)
      setFavorites(purge)
      setRecents(purge)
      await refreshProjects()
      if (activeProject === name) {
        const remaining = projects.filter(p => p !== name)
        setActiveProject(remaining[0] ?? '')
      }
      bumpFs()
      toast.success(trNow(`Projet "${name}" supprimé`, `Project "${name}" deleted`))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : trNow('Suppression du projet échouée', 'Project delete failed'))
    } finally {
      setDeleteProjectTarget(null)
    }
  }, [refreshProjects, activeProject, projects, setActiveProject, bumpFs])

  const recentSidebarItems = recents.slice(0, 5)
  const navBtn = (ok: boolean): React.CSSProperties => ({ width: 24, height: 24, border: '1px solid var(--rule-2)', borderRadius: 5, display: 'flex', alignItems: 'center', justifyContent: 'center', color: ok ? 'var(--ink-2)' : 'var(--ink-4)', boxShadow: 'var(--shadow-xs)', cursor: ok ? 'pointer' : 'default', opacity: ok ? 1 : 0.4, flexShrink: 0 })
  const twoCols = layout === 'side' || layout === 'quad'
  const twoRows = layout === 'stacked' || layout === 'quad'

  return (
    <FolderManagerContext.Provider value={shared}>
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>

      {/* Barre commune : annuler + Token Finder (résultats dans la vue active) + presse-papier */}
      <div style={{ padding: '6px 10px 7px', borderBottom: '1px solid var(--rule)', background: 'var(--paper-2)', flexShrink: 0, display: 'flex', alignItems: 'center', gap: 6 }}>
        <div onClick={undoStack.length > 0 ? () => void undoLast() : undefined} title={tr('Annuler (Ctrl+Z)', 'Undo (Ctrl+Z)')} style={navBtn(undoStack.length > 0)}>
          <RotateCcw size={12} strokeWidth={2} />
        </div>
        <TokenFinder project={navProject || activeProject} onChange={setTokenSel} />
        <div
          onClick={() => void handleFind()}
          className="btn primary"
          style={{ height: 30, padding: '0 14px', flexShrink: 0, display: 'flex', alignItems: 'center', fontSize: 11, cursor: findLoading ? 'wait' : 'pointer' }}
        >
          {findLoading ? '…' : 'Find'}
        </div>
        {clipboard && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0, padding: '0 8px', height: 30, border: '1px solid var(--rule-2)', borderRadius: 5, background: 'var(--bg-deep)', fontFamily: 'var(--mono)', fontSize: 10.5, color: 'var(--ink-3)', boxShadow: 'var(--shadow-inset)' }}>
            <Copy size={10} strokeWidth={1.75} color="var(--ink-4)" />
            <span>{clipboard.items.length} {clipboard.op === 'cut' ? tr('coupé(s)', 'cut') : tr('copié(s)', 'copied')}</span>
            <X size={10} strokeWidth={2} style={{ cursor: 'pointer' }} onClick={() => setClipboard(null)} />
          </div>
        )}
        <div style={{ flex: 1 }} />
        <label className="fm-setup-toggle" title={tr('Afficher le dossier _flux_setup et les fichiers de configuration du projet', 'Show the _flux_setup folder and the project configuration files')}>
          <input type="checkbox" checked={showSetup} onChange={e => setShowSetupValue(e.target.checked ? 'shown' : 'hidden')} />
          <span>Setup files</span>
        </label>
        <ViewMenu
          layout={layout} onLayout={changeLayout}
          tileSize={tileSize} onTileSize={changeTileSize}
        />
      </div>

      {/* Corps */}
      <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>

        {/* Sidebar gauche */}
        <div style={{ width: 170, borderRight: '1px solid var(--rule)', display: 'flex', flexDirection: 'column', background: 'var(--paper-2)', flexShrink: 0 }}>
          <div style={{ padding: '8px 0 4px' }}>
            {SIDEBAR_TABS.map(({ id, label, labelEn, icon: Icon }) => {
              const active = sidebarTab === id
              return (
                <div
                  key={id}
                  onClick={() => { setSidebarTab(id); if (id === 'tous') navigateActive({ kind: 'root' }) }}
                  style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 10px', margin: '1px 8px 1px 0', background: active ? 'var(--accent-soft)' : 'transparent', borderLeft: active ? '2px solid var(--rule-3)' : '2px solid transparent', borderRadius: '0 6px 6px 0', fontSize: 11, color: active ? 'var(--ink)' : 'var(--ink-3)', fontWeight: active ? 500 : 400, cursor: 'pointer', userSelect: 'none' }}
                >
                  <Icon size={12} strokeWidth={1.75} color={active ? 'var(--accent)' : 'var(--ink-4)'} />
                  <span>{tr(label, labelEn)}</span>
                  {id === 'favoris' && favorites.length > 0 && (
                    <span style={{ marginLeft: 'auto', fontSize: 10.5, fontFamily: 'var(--mono)', color: active ? 'var(--accent)' : 'var(--ink-4)', background: active ? 'transparent' : 'var(--bg-deep)', padding: '1px 5px', borderRadius: 9, border: '1px solid var(--rule-2)' }}>
                      {favorites.length}
                    </span>
                  )}
                  {id === 'archives' && archived.length > 0 && (
                    <span style={{ marginLeft: 'auto', fontSize: 10.5, fontFamily: 'var(--mono)', color: active ? 'var(--accent)' : 'var(--ink-4)', background: active ? 'transparent' : 'var(--bg-deep)', padding: '1px 5px', borderRadius: 9, border: '1px solid var(--rule-2)' }}>
                      {archived.length}
                    </span>
                  )}
                </div>
              )
            })}
          </div>

          <div style={{ height: 1, background: 'var(--rule)', margin: '6px 0' }} />

          {/* Presets — dépôt rapide dans le dossier de la vue active (RETAKES-3) */}
          {nav.kind === 'inside' && presets.some(p => p.file) && (
            <>
              <div style={{ padding: '2px 12px 0' }}>
                <div className="cap" style={{ marginBottom: 6 }}>PRESETS</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                  {presets.filter(p => p.file).map(p => (
                    <button
                      key={p.id}
                      onClick={() => void dropPresetHere(p)}
                      title={tr(`Déposer "${p.file}" dans le dossier courant`, `Drop "${p.file}" into the current folder`)}
                      style={{
                        display: 'flex', alignItems: 'center', gap: 7, width: '100%', textAlign: 'left',
                        padding: '6px 8px', background: 'var(--bg-deep)', border: '1px solid var(--rule-2)',
                        borderRadius: 6, color: 'var(--ink-2)', fontSize: 11, fontFamily: 'var(--sans)',
                        cursor: 'pointer', boxShadow: 'var(--shadow-xs)',
                      }}
                      onMouseEnter={e => { e.currentTarget.style.borderColor = 'var(--rule-3)'; e.currentTarget.style.color = 'var(--ink)' }}
                      onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--rule-2)'; e.currentTarget.style.color = 'var(--ink-2)' }}
                    >
                      <FileDown size={12} strokeWidth={1.75} color="var(--accent)" style={{ flexShrink: 0 }} />
                      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.name}</span>
                    </button>
                  ))}
                </div>
              </div>
              <div style={{ height: 1, background: 'var(--rule)', margin: '6px 0' }} />
            </>
          )}

          {/* Récents rapides */}
          <div style={{ padding: '2px 12px 0' }}>
            <div className="cap" style={{ marginBottom: 6 }}>{tr('RÉCENTS', 'RECENT')}</div>
            {recentSidebarItems.length === 0 ? (
              <div style={{ fontSize: 11, color: 'var(--ink-4)', fontStyle: 'italic', padding: '3px 0' }}>{tr('Aucun', 'None')}</div>
            ) : recentSidebarItems.map((s, i) => (
              <div
                key={i}
                onClick={() => navigateToSaved(s)}
                style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '5px 0', fontSize: 11, color: s.project === activeProject ? 'var(--accent-hi)' : 'var(--ink-3)', cursor: 'pointer' }}
              >
                <FolderIcon size={11} color={s.project === activeProject ? 'var(--accent)' : 'var(--ink-4)'} />
                <span title={s.label} style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.label}</span>
              </div>
            ))}
          </div>

          <div style={{ height: 1, background: 'var(--rule)', margin: '10px 0 0' }} />

          <div style={{ flex: 1 }} />
          <div style={{ padding: '10px 12px 12px', borderTop: '1px solid var(--rule)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 8 }}>
              <HardDrive size={10} strokeWidth={1.75} color="var(--ink-4)" />
              <div className="cap">WORKSPACE</div>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11 }}>
              <span style={{ color: 'var(--ink-3)' }}>{tr('Projets', 'Projects')}</span>
              <span style={{ fontFamily: 'var(--mono)', color: 'var(--ink-2)', fontSize: 11 }}>{projects.length}</span>
            </div>
          </div>
        </div>

        {/* Zone centrale */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, borderRight: '1px solid var(--rule)', overflow: 'hidden' }}>

          {/* Listes sauvegardées (Favoris / Récents / Archivés) : ouvrent dans la vue active */}
          {sidebarTab === 'favoris' && (
            <SavedList
              items={favorites} label={tr('FAVORIS', 'FAVORITES')} emptyMsg={tr('Aucun favori', 'No favorites')}
              removeLabel={tr('Retirer des Favoris', 'Remove from Favorites')}
              onNavigate={navigateToSaved}
              onRemove={s => removeFromSaved(s, 'favorites')}
            />
          )}
          {sidebarTab === 'recents' && (
            <SavedList
              items={recents} label={tr('RÉCENTS', 'RECENT')} emptyMsg={tr('Aucun élément récent', 'No recent items')}
              removeLabel={tr('Retirer des Récents', 'Remove from Recent')}
              onNavigate={navigateToSaved}
              onRemove={s => removeFromSaved(s, 'recents')}
            />
          )}
          {sidebarTab === 'archives' && (
            <ArchivesBrowser
              onOpen={(project, subpath) => {
                navigateActive({ kind: 'inside', project, subpath })
                setSidebarTab('tous')
              }}
            />
          )}

          {/* Vues d'exploration : restent montées (état gardé) quand une liste est affichée */}
          <div ref={viewsRef} title={tr('Ctrl + molette : taille des tuiles', 'Ctrl + wheel: tile size')} style={{
            flex: 1, minHeight: 0, minWidth: 0,
            display: sidebarTab === 'tous' ? 'grid' : 'none',
            gridTemplateColumns: twoCols ? 'minmax(0, 1fr) minmax(0, 1fr)' : 'minmax(0, 1fr)',
            gridTemplateRows: twoRows ? 'minmax(0, 1fr) minmax(0, 1fr)' : 'minmax(0, 1fr)',
            gap: paneCount > 1 ? 6 : 0, padding: paneCount > 1 ? 6 : 0,
          }}>
            {Array.from({ length: paneCount }, (_, i) => (
              <ExplorerPane
                key={i}
                ref={el => { paneRefs.current[i] = el }}
                paneId={i}
                active={i === activeIdx}
                framed={paneCount > 1}
                initialNav={nav}
                onFocus={setActivePane}
                onReport={onReport}
              />
            ))}
          </div>

          {/* N7: note of the selected published file, at the bottom (hidden when it has none) */}
          {sidebarTab === 'tous' && nav.kind === 'inside' && report.selectedNames.size === 1 && (
            <PublishNote project={nav.project} relPath={[...nav.subpath, [...report.selectedNames][0]].join('/')} />
          )}
        </div>

      </div>

      {deleteProjectTarget && (
        <DeleteProjectModal
          project={deleteProjectTarget.project}
          onConfirm={() => void handleDeleteProject(deleteProjectTarget)}
          onCancel={() => setDeleteProjectTarget(null)}
        />
      )}
    </div>
    </FolderManagerContext.Provider>
  )
}

// "Affichage" menu of the Folder Manager header (ADR 0042, page prefs per ADR 0043): views, tile size and the
// creation forms in one place instead of seven always-visible buttons.
function ViewMenu({ layout, onLayout, tileSize, onTileSize }: {
  layout: PaneLayout; onLayout: (l: PaneLayout) => void
  tileSize: TileSize; onTileSize: (s: TileSize) => void
}) {
  const Current = LAYOUTS.find(l => l.id === layout)?.icon ?? Square
  const { tr } = useTr()
  return (
    <Menu.Root modal={false}>
      <Menu.Trigger className="fm-view-trigger" aria-label={tr('Affichage', 'View')}>
        <Current size={13} strokeWidth={1.75} />
        <span>{tr('Affichage', 'View')}</span>
        <ChevronDown size={11} />
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Content className="launcher-menu" side="bottom" align="end" sideOffset={4} collisionPadding={10}>
          <Menu.Label className="launcher-menu-label">{tr('Vues', 'Views')}</Menu.Label>
          <Menu.RadioGroup value={layout} onValueChange={v => onLayout(v as PaneLayout)}>
            {LAYOUTS.map(({ id, icon: Icon, title, titleEn }) => (
              <Menu.RadioItem key={id} value={id} className="launcher-menu-item">
                <Icon size={13} strokeWidth={1.75} />{tr(title, titleEn)}
                <Menu.ItemIndicator style={{ marginLeft: 'auto', display: 'inline-flex' }}><Check size={13} /></Menu.ItemIndicator>
              </Menu.RadioItem>
            ))}
          </Menu.RadioGroup>
          <Menu.Separator className="launcher-menu-separator" />
          <Menu.Label className="launcher-menu-label">{tr('Taille · Ctrl + molette', 'Size · Ctrl + wheel')}</Menu.Label>
          <Menu.RadioGroup value={tileSize} onValueChange={v => onTileSize(v as TileSize)}>
            {TILE_CHOICES.map(({ id, icon: Icon, title, titleEn }) => (
              <Menu.RadioItem key={id} value={id} className="launcher-menu-item">
                <Icon size={13} strokeWidth={1.75} />{tr(title, titleEn)}
                <Menu.ItemIndicator style={{ marginLeft: 'auto', display: 'inline-flex' }}><Check size={13} /></Menu.ItemIndicator>
              </Menu.RadioItem>
            ))}
          </Menu.RadioGroup>
        </Menu.Content>
      </Menu.Portal>
    </Menu.Root>
  )
}
