import { useState, useEffect, useCallback, useRef } from 'react'
import { toast } from 'sonner'
import { useLocation } from 'react-router-dom'
import {
  ChevronLeft, ChevronRight, Search,
  Star, LayoutGrid, Clock, Archive,
  HardDrive, Plus, Minus, X, Trash2, Copy, RotateCcw, Lock,
  Grid3x3, Grid2x2, Square, FileDown,
} from 'lucide-react'
import { FolderIcon, Select, SelectTrigger, SelectContent, SelectItem } from '../components/shared/ui'
import { api } from '../api/client'
import type { Preset } from '../types'
import { useProject } from '../ProjectContext'
import { useSettings } from '../hooks/useSettings'
import { useDccStatus } from '../hooks/useDccStatus'
import { readActiveInstancePort } from '../hooks/useActiveInstances'

// DCCs the backend can import into (from the Folder Manager). Others have no
// import bridge yet, so they never appear in "Ouvrir dans…".

// ── Types ─────────────────────────────────────────────────────────────────────

type NavLevel =
  | { kind: 'root' }
  | { kind: 'inside'; project: string; subpath: string[] }

type SidebarTab = 'tous' | 'favoris' | 'recents' | 'archives'

// Tile size for the explorer grid. Bigger tiles = larger icons + more room for
// the label below. Persisted per-browser in localStorage.
type TileSize = 'sm' | 'md' | 'lg'

const TILE_SIZES: Record<TileSize, { col: number; folder: number; file: number; font: number; gap: number }> = {
  sm: { col: 64,  folder: 30, file: 26, font: 9,  gap: 3 },
  md: { col: 80,  folder: 40, file: 34, font: 10, gap: 4 },
  lg: { col: 116, folder: 58, file: 50, font: 12, gap: 6 },
}

const TILE_SIZE_KEY = 'flux.folderManager.tileSize'

function loadTileSize(): TileSize {
  try {
    const v = localStorage.getItem(TILE_SIZE_KEY)
    if (v === 'sm' || v === 'md' || v === 'lg') return v
  } catch { /* localStorage unavailable */ }
  return 'md'
}

interface ExplorerItem { name: string; isDir: boolean }

interface SavedItem {
  label:   string
  project: string
  subpath: string[]  // subpath within project EXCLUDING item name; [] = project root
  isDir:   boolean
}

interface FindResult {
  label:   string
  pathStr: string
  project: string
  subpath: string[]
  isDir:   boolean
}

type FinderMode = 'asset' | 'shot'

interface TokenSel { category: string; name: string; task: string; instance: string; variante: string; seq: string; shot: string; mode: FinderMode }
const EMPTY_TOKEN_SEL: TokenSel = { category: '', name: '', task: '', instance: '', variante: '', seq: '', shot: '', mode: 'asset' }

interface CtxMenu { x: number; y: number; items: ExplorerItem[] }

// Clipboard for copy/cut → paste. Scoped to a project + source folder.
interface Clip { op: 'copy' | 'cut'; project: string; subpath: string[]; items: ExplorerItem[] }

// Reversible file operations, for Ctrl+Z. One user action pushes one UndoOp
// (which may bundle several items). Delete is destructive → never recorded.
type UndoAction =
  | { kind: 'move';   project: string; fromSub: string[]; toSub: string[]; name: string }
  | { kind: 'rename'; project: string; sub: string[]; oldName: string; newName: string }
  | { kind: 'copy';   project: string; sub: string[]; name: string }   // undo = delete the created copy
interface UndoOp { label: string; actions: UndoAction[] }

type Tab = 'project' | 'asset' | 'shot' | 'directory'
const TABS: { id: Tab; label: string }[] = [
  { id: 'project',   label: 'Projet' },
  { id: 'asset',     label: 'Asset' },
  { id: 'shot',      label: 'Shot' },
  { id: 'directory', label: 'Dossier' },
]

const ASSET_TOKENS = ['CHAR', 'PROPS', 'ENV', 'FXRIG']
const TOKEN_TYPES  = ['CLASS', 'TYPE', 'NAME', 'INSTANCE', 'SEQ', 'SHOT', 'custom']

// Finder — same fixed lists as the Publisher composer (Category / Task predefined,
// FX is the display label for the FXRIG class). Name/Instance/Variante come from disk.
const FINDER_CATEGORIES = ['CHAR', 'PROPS', 'ENV', 'FX']
const FINDER_CATEGORY_TO_CLASS: Record<string, string> = { CHAR: 'CHAR', PROPS: 'PROPS', ENV: 'ENV', FX: 'FXRIG' }
const FINDER_TASKS = ['GEO', 'SHADING', 'GROOM', 'RIG', 'CFX', 'MULT']

const SIDEBAR_TABS: { id: SidebarTab; label: string; icon: typeof Star }[] = [
  { id: 'favoris',  label: 'Favoris',  icon: Star },
  { id: 'tous',     label: 'Home',     icon: LayoutGrid },
  { id: 'recents',  label: 'Récents',  icon: Clock },
  { id: 'archives', label: 'Archivés', icon: Archive },
]

// ── Saved-item helpers ────────────────────────────────────────────────────────

function savedKey(s: SavedItem): string {
  return `${s.project}||${s.subpath.join('/')}||${s.label}`
}

function itemKey(project: string, subpath: string[], label: string): string {
  return `${project}||${subpath.join('/')}||${label}`
}

function makeSavedItem(item: ExplorerItem, nav: NavLevel): SavedItem {
  if (nav.kind === 'root') {
    return { label: item.name, project: item.name, subpath: [], isDir: true }
  }
  return { label: item.name, project: nav.project, subpath: nav.subpath, isDir: item.isDir }
}

function currentItemKey(item: ExplorerItem, nav: NavLevel): string {
  if (nav.kind === 'root') return itemKey(item.name, [], item.name)
  return itemKey(nav.project, nav.subpath, item.name)
}

function navigateTargetFor(s: SavedItem): NavLevel {
  // Root-level project: project === label && subpath empty
  if (s.project === s.label && s.subpath.length === 0) {
    return { kind: 'inside', project: s.project, subpath: [] }
  }
  if (s.isDir) {
    return { kind: 'inside', project: s.project, subpath: [...s.subpath, s.label] }
  }
  return { kind: 'inside', project: s.project, subpath: s.subpath }
}

// ── Icônes SVG ────────────────────────────────────────────────────────────────

// Version badge colours: LAST is the active publish (green), a locked version is
// a frozen snapshot (orange). Drawn on the file/folder icon itself.
const VER_LAST_BG = '#1F9E6A'
const VER_NUM_BG  = '#E8912A'

// Parse the trailing "_<FORMAT>_<VERSION>" of a published name (file or folder),
// e.g. CHAR_RIG_PATRICK_ALL_A_USD_LAST → { format: 'USD', version: 'LAST' } or
// ..._USD_V003 → { format: 'USD', version: 'V003' }. Returns {} when the name is
// not a versioned publish (plain assets/tasks/instances), so no badge is drawn.
function parseVersionMeta(name: string): { version?: string; format?: string } {
  // Drop a real file extension first so the version token is the last segment.
  const dot = name.lastIndexOf('.')
  const stem = dot > 0 ? name.slice(0, dot) : name
  const parts = stem.split('_')
  if (parts.length < 2) return {}
  const last = parts[parts.length - 1]
  const m = /^(LAST|v\d+|V\d+)$/.exec(last)
  if (!m) return {}
  const version = last.toUpperCase()
  const fmtTok = parts[parts.length - 2]
  const format = /^[A-Za-z]{2,5}$/.test(fmtTok) ? fmtTok.toUpperCase() : undefined
  return { version, format }
}

// Small version/format chips drawn inside an icon's SVG viewBox. `w` is the
// viewBox width so the chips can be centred for both the file (30) and folder (40).
function IconBadges({ version, format, w, versionY, formatY }: {
  version?: string; format?: string; w: number; versionY: number; formatY?: number
}) {
  const bw = Math.min(28, w - 4)
  const x = (w - bw) / 2
  const cx = w / 2
  return (
    <>
      {version && (
        <>
          <rect x={x} y={versionY} width={bw} height="10" rx="2" fill={version === 'LAST' ? VER_LAST_BG : VER_NUM_BG} />
          <text x={cx} y={versionY + 7.5} textAnchor="middle" fontSize="6.5" fontWeight="700" fontFamily="monospace" fill="#fff" letterSpacing="0.2">{version}</text>
        </>
      )}
      {format && formatY !== undefined && (
        <>
          <rect x={x} y={formatY} width={bw} height="10" rx="2" fill="rgba(18,18,18,0.55)" />
          <text x={cx} y={formatY + 7.5} textAnchor="middle" fontSize="6.5" fontWeight="700" fontFamily="monospace" fill="#fff" letterSpacing="0.2">{format}</text>
        </>
      )}
    </>
  )
}

function FolderSvg({ size = 40, selected = false, version, format }: {
  size?: number; selected?: boolean; version?: string; format?: string
}) {
  const body = selected ? 'var(--accent)'    : '#F5A623'
  const tab  = selected ? 'var(--accent-hi)' : '#FFCA5C'
  return (
    <svg width={size} height={Math.round(size * 0.82)} viewBox="0 0 40 33" fill="none">
      <path d="M2 7 L2 4 Q2 2 4 2 L15 2 L18.5 7 Z" fill={tab} />
      <path d="M0 9 Q0 7 2 7 L38 7 Q40 7 40 9 L40 31 Q40 33 38 33 L2 33 Q0 33 0 31 Z" fill={body} />
      <IconBadges version={version} format={format} w={40} versionY={10} formatY={21} />
    </svg>
  )
}

const EXT_BADGE: Record<string, { bg: string; fg: string }> = {
  usd:  { bg: '#E07820', fg: '#fff' },
  usda: { bg: '#E07820', fg: '#fff' },
  usdc: { bg: '#E07820', fg: '#fff' },
  usdz: { bg: '#E07820', fg: '#fff' },
  abc:  { bg: '#1A9E6E', fg: '#fff' },
  gbx:  { bg: '#5A8A2E', fg: '#fff' },
  obj:  { bg: '#7B6FAA', fg: '#fff' },
  ma:   { bg: '#1E88C8', fg: '#fff' },
  mb:   { bg: '#1565A8', fg: '#fff' },
  ztl:  { bg: '#D03030', fg: '#fff' },
}

function getExt(filename: string): string {
  return filename.split('.').pop()?.toLowerCase() ?? ''
}

function FileSvg({ size = 36, selected = false, ext = '', version }: {
  size?: number; selected?: boolean; ext?: string; version?: string
}) {
  const body   = selected ? 'var(--accent)'    : 'var(--ink-2)'
  const corner = selected ? 'var(--accent-hi)' : 'var(--ink-3)'
  const badge  = EXT_BADGE[ext]
  return (
    <svg width={size} height={Math.round(size * 1.22)} viewBox="0 0 30 37" fill="none">
      <path d="M2 0 L20 0 L30 10 L30 35 Q30 37 28 37 L2 37 Q0 37 0 35 L0 2 Q0 0 2 0Z" fill={body} />
      <path d="M20 0 L20 10 L30 10Z" fill={corner} />
      {/* version chip sits above the format badge */}
      <IconBadges version={version} w={30} versionY={13} />
      {badge && (
        <>
          <rect x="2" y="25" width="26" height="10" rx="2" fill={badge.bg} />
          <text x="15" y="33" textAnchor="middle" fontSize="6.5" fontWeight="700"
            fontFamily="monospace" fill={badge.fg} letterSpacing="0.3">
            {ext.toUpperCase()}
          </text>
        </>
      )}
    </svg>
  )
}

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
        { key: 'category', label: 'CATÉGORIE', opts: FINDER_CATEGORIES },
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
        style={{ flexShrink: 0, height: 30, padding: '0 9px', display: 'flex', alignItems: 'center', border: '1px solid var(--rule-2)', borderRadius: 5, background: mode === 'shot' ? 'var(--accent-soft)' : 'var(--bg-deep)', cursor: 'pointer', fontSize: 9, fontFamily: 'var(--mono)', color: mode === 'shot' ? 'var(--accent-hi)' : 'var(--ink-3)', fontWeight: 600, letterSpacing: '0.08em', userSelect: 'none', boxShadow: 'var(--shadow-xs)' }}
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
              <span style={{ fontSize: 7, color: 'var(--ink-4)', textTransform: 'uppercase', letterSpacing: '0.1em', lineHeight: 1 }}>{label}</span>
              <span style={{ fontSize: 9, fontFamily: 'var(--mono)', color: value ? 'var(--accent-hi)' : 'var(--ink-4)', fontWeight: value ? 600 : 400, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', lineHeight: 1.3 }}>
                {value || '-'}
              </span>
            </div>
            {isOpen && (
              <div style={{ position: 'absolute', top: 'calc(100% + 3px)', left: 0, zIndex: 500, minWidth: 110, background: 'var(--paper)', border: '1px solid var(--rule-2)', borderRadius: 5, boxShadow: 'var(--shadow)', overflow: 'hidden' }}>
                {value && (
                  <div onClick={() => clear(key)} style={{ padding: '5px 8px', fontSize: 9, fontFamily: 'var(--mono)', color: 'var(--ink-4)', borderBottom: '1px solid var(--rule)', cursor: 'pointer' }}>
                    effacer
                  </div>
                )}
                {opts.length === 0 ? (
                  <div style={{ padding: '6px 8px', fontSize: 9, color: 'var(--ink-4)', fontStyle: 'italic' }}>
                    {project ? 'Vide' : 'Projet requis'}
                  </div>
                ) : opts.map(o => (
                  <div
                    key={o}
                    onClick={() => update(key, o)}
                    style={{ padding: '5px 8px', fontSize: 9, fontFamily: 'var(--mono)', color: o === value ? 'var(--accent-hi)' : 'var(--ink-2)', background: o === value ? 'var(--accent-soft)' : 'transparent', cursor: 'pointer', whiteSpace: 'nowrap' }}
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

// ── Sous-composants partagés ──────────────────────────────────────────────────

function Spinner({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  const [draft, setDraft] = useState(String(value).padStart(3, '0'))

  useEffect(() => { setDraft(String(value).padStart(3, '0')) }, [value])

  const commit = () => {
    const n = parseInt(draft, 10)
    if (!isNaN(n) && n >= 1) { onChange(n); setDraft(String(n).padStart(3, '0')) }
    else setDraft(String(value).padStart(3, '0'))
  }

  return (
    <div style={{ display: 'flex', alignItems: 'center', height: 28, border: '1px solid var(--rule-2)', borderRadius: 5, overflow: 'hidden', background: 'var(--bg-deep)', boxShadow: 'var(--shadow-inset)' }}>
      <div onClick={() => onChange(Math.max(1, value - 1))} style={{ width: 26, height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', borderRight: '1px solid var(--rule-2)', cursor: 'pointer', color: 'var(--ink-3)', flexShrink: 0 }}>
        <Minus size={10} strokeWidth={2} />
      </div>
      <input
        type="text"
        inputMode="numeric"
        value={draft}
        onChange={e => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={e => { if (e.key === 'Enter') commit() }}
        style={{ flex: 1, textAlign: 'center', fontFamily: 'var(--sans)', fontSize: 11, color: 'var(--ink-2)', background: 'transparent', border: 'none', outline: 'none', minWidth: 0 }}
      />
      <div onClick={() => onChange(value + 1)} style={{ width: 26, height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', borderLeft: '1px solid var(--rule-2)', cursor: 'pointer', color: 'var(--ink-3)', flexShrink: 0 }}>
        <Plus size={10} strokeWidth={2} />
      </div>
    </div>
  )
}

function SelectEl({ options, value, onChange }: { options: string[]; value: string; onChange: (v: string) => void }) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger style={{ width: '100%' }} />
      <SelectContent>
        {options.length === 0
          ? <SelectItem value="__empty__">-</SelectItem>
          : options.map(o => <SelectItem key={o} value={o}>{o}</SelectItem>)}
      </SelectContent>
    </Select>
  )
}

function InputField({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder: string }) {
  return (
    <input
      value={value}
      onChange={e => onChange(e.target.value)}
      placeholder={placeholder}
      style={{ width: '100%', height: 28, border: '1px solid var(--rule-2)', borderRadius: 5, background: 'var(--bg-deep)', color: 'var(--ink-2)', fontFamily: 'var(--sans)', fontSize: 10, padding: '0 8px', boxShadow: 'var(--shadow-inset)', outline: 'none' }}
    />
  )
}

function PanelBtn({ primary, children, onClick, disabled, danger }: { primary?: boolean; danger?: boolean; children: React.ReactNode; onClick?: () => void; disabled?: boolean }) {
  return (
    <div
      className={`btn${primary ? ' primary' : ' ghost'}`}
      onClick={disabled ? undefined : onClick}
      style={{ width: '100%', justifyContent: 'center', opacity: disabled ? 0.5 : 1, cursor: disabled ? 'default' : 'pointer', ...(danger ? { background: 'var(--err)', borderColor: 'var(--err)' } : {}) }}
    >
      {children}
    </div>
  )
}

function NavContext({ project }: { project: string }) {
  if (!project) return (
    <div style={{ padding: '5px 8px', borderRadius: 5, border: '1px solid var(--rule-2)', background: 'var(--bg-deep)', fontFamily: 'var(--mono)', fontSize: 9, color: 'var(--ink-4)', fontStyle: 'italic' }}>
      Naviguez dans un projet
    </div>
  )
  return (
    <div style={{ padding: '5px 8px', borderRadius: 5, border: '1px solid var(--rule-2)', background: 'var(--bg-deep)', fontFamily: 'var(--mono)', fontSize: 9, color: 'var(--ink-2)' }}>
      <span style={{ color: 'var(--ink-4)' }}>Projet : </span>
      <span style={{ fontWeight: 600 }}>{project}</span>
    </div>
  )
}

// ── Onglets panneau droit ─────────────────────────────────────────────────────

function TabProject({ onCreateProject }: { onCreateProject: (name: string) => Promise<void> }) {
  const [name, setName]     = useState('')
  const [status, setStatus] = useState('')

  const handleCreate = async () => {
    if (!name.trim()) return
    try {
      await onCreateProject(name.trim())
      setStatus('✓ Créé')
      setName('')
    } catch (e) {
      setStatus('✗ ' + (e instanceof Error ? e.message : 'Erreur'))
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, flex: 1 }}>
      <div>
        <div className="cap" style={{ marginBottom: 4 }}>NOM</div>
        <InputField value={name} onChange={setName} placeholder="ex: NEW_PROJECT" />
      </div>
      {status && <div style={{ fontFamily: 'var(--mono)', fontSize: 10, color: status.startsWith('✓') ? 'var(--ok)' : 'var(--err)' }}>{status}</div>}
      <div style={{ flex: 1 }} />
      <PanelBtn primary onClick={() => void handleCreate()} disabled={!name.trim()}>Create Project</PanelBtn>
    </div>
  )
}

function TabAsset({ currentProject, onCreateAsset }: {
  currentProject: string
  onCreateAsset: (project: string, cls: string, name: string) => Promise<void>
}) {
  const [token, setToken]   = useState('CHAR')
  const [name, setName]     = useState('')
  const [status, setStatus] = useState('')

  const handleCreate = async () => {
    if (!currentProject || !name.trim()) return
    try {
      await onCreateAsset(currentProject, token, name.trim())
      setStatus('✓ Créé')
      setName('')
    } catch (e) {
      setStatus('✗ ' + (e instanceof Error ? e.message : 'Erreur'))
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, flex: 1 }}>
      <NavContext project={currentProject} />
      <div>
        <div className="cap" style={{ marginBottom: 4 }}>TYPE</div>
        <SelectEl options={ASSET_TOKENS} value={token} onChange={setToken} />
      </div>
      <div>
        <div className="cap" style={{ marginBottom: 4 }}>NAME</div>
        <InputField value={name} onChange={setName} placeholder="ex: HorseRig" />
      </div>
      {status && <div style={{ fontFamily: 'var(--mono)', fontSize: 10, color: status.startsWith('✓') ? 'var(--ok)' : 'var(--err)' }}>{status}</div>}
      <div style={{ flex: 1 }} />
      <PanelBtn primary onClick={() => void handleCreate()} disabled={!currentProject || !name.trim()}>Create Asset</PanelBtn>
    </div>
  )
}

function TabShot({ currentProject, sequences, onCreateSequence, onCreateShot, onRefreshSequences }: {
  currentProject: string; sequences: string[]
  onCreateSequence: (project: string, seqN: number) => Promise<void>
  onCreateShot: (project: string, seqN: number, shotN: number) => Promise<void>
  onRefreshSequences: () => void
}) {
  const [seqN, setSeqN]             = useState(1)
  const [shotN, setShotN]           = useState(1)
  const [seq, setSeq]               = useState('')
  const [statusSeq, setStatusSeq]   = useState('')
  const [statusShot, setStatusShot] = useState('')

  useEffect(() => { setSeq(sequences[0] ?? '') }, [sequences])

  const handleCreateSeq = async () => {
    if (!currentProject) return
    try {
      await onCreateSequence(currentProject, seqN)
      setStatusSeq('✓ SQ' + String(seqN).padStart(3, '0'))
      onRefreshSequences()
    } catch (e) {
      setStatusSeq('✗ ' + (e instanceof Error ? e.message : 'Erreur'))
    }
  }

  const handleCreateShot = async () => {
    if (!currentProject || !seq) return
    const seqNum = parseInt(seq.replace(/\D/g, ''), 10) || seqN
    try {
      await onCreateShot(currentProject, seqNum, shotN)
      setStatusShot(`✓ SQ${String(seqNum).padStart(3, '0')}_SH${String(shotN).padStart(3, '0')}`)
    } catch (e) {
      setStatusShot('✗ ' + (e instanceof Error ? e.message : 'Erreur'))
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, flex: 1 }}>
      <NavContext project={currentProject} />
      <div style={{ padding: '10px', border: '1px solid var(--rule-2)', borderRadius: 7, background: 'var(--bg-deep)', display: 'flex', flexDirection: 'column', gap: 8, boxShadow: 'var(--shadow-inset)' }}>
        <div className="cap">SEQ</div>
        <Spinner value={seqN} onChange={setSeqN} />
        {statusSeq && <div style={{ fontFamily: 'var(--mono)', fontSize: 9, color: statusSeq.startsWith('✓') ? 'var(--ok)' : 'var(--err)' }}>{statusSeq}</div>}
        <PanelBtn primary onClick={() => void handleCreateSeq()} disabled={!currentProject}>Create Sequence</PanelBtn>
      </div>
      <div style={{ padding: '10px', border: '1px solid var(--rule-2)', borderRadius: 7, background: 'var(--bg-deep)', display: 'flex', flexDirection: 'column', gap: 8, boxShadow: 'var(--shadow-inset)' }}>
        <div className="cap">SHOT</div>
        <div>
          <div className="cap" style={{ marginBottom: 4, fontSize: 8 }}>IN SEQUENCE</div>
          <SelectEl options={sequences.length > 0 ? sequences : ['-']} value={seq} onChange={setSeq} />
        </div>
        <div>
          <div className="cap" style={{ marginBottom: 4, fontSize: 8 }}>SHOT NO.</div>
          <Spinner value={shotN} onChange={setShotN} />
        </div>
        {statusShot && <div style={{ fontFamily: 'var(--mono)', fontSize: 9, color: statusShot.startsWith('✓') ? 'var(--ok)' : 'var(--err)' }}>{statusShot}</div>}
        <PanelBtn primary onClick={() => void handleCreateShot()} disabled={!currentProject || !seq}>Create Shot</PanelBtn>
      </div>
      <div style={{ flex: 1 }} />
    </div>
  )
}

function TabDirectory({ currentProject, currentSubpath, onSuccess }: {
  currentProject: string
  currentSubpath: string[]
  onSuccess: () => void
}) {
  const [name, setName]           = useState('')
  const [token, setToken]         = useState('')
  const [tokenType, setTokenType] = useState('CLASS')
  const [status, setStatus]       = useState('')
  const [busy, setBusy]           = useState(false)

  const handleAdd = async () => {
    if (!name.trim() || !currentProject) return
    setBusy(true)
    setStatus('')
    try {
      const res = await api.createDirectory(
        currentProject,
        currentSubpath,
        name.trim(),
        token.trim() || undefined,
        token.trim() ? tokenType : undefined,
      )
      const shortPath = res.rel_path.split('/').slice(-2).join('/')
      setStatus(`✓ ${shortPath}`)
      setName('')
      setToken('')
      onSuccess()
    } catch (e) {
      setStatus('✗ ' + (e instanceof Error ? e.message : 'Erreur'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, flex: 1 }}>
      <NavContext project={currentProject} />
      <div>
        <div className="cap" style={{ marginBottom: 4 }}>NAME</div>
        <InputField value={name} onChange={setName} placeholder="ex: NEW_FOLDER" />
      </div>
      <div>
        <div className="cap" style={{ marginBottom: 4 }}>TOKEN (optionnel)</div>
        <InputField value={token} onChange={setToken} placeholder="ex: SLA" />
      </div>
      {token.trim() && (
        <div>
          <div className="cap" style={{ marginBottom: 4 }}>TOKEN TYPE</div>
          <SelectEl options={TOKEN_TYPES} value={tokenType} onChange={setTokenType} />
        </div>
      )}
      {status && (
        <div style={{ fontFamily: 'var(--mono)', fontSize: 9, color: status.startsWith('✓') ? 'var(--ok)' : 'var(--err)', lineHeight: 1.4 }}>
          {status}
        </div>
      )}
      <div style={{ flex: 1 }} />
      <PanelBtn primary onClick={() => void handleAdd()} disabled={!name.trim() || !currentProject || busy}>
        {busy ? '…' : 'Add Folder'}
      </PanelBtn>
    </div>
  )
}

// ── Context Menu ──────────────────────────────────────────────────────────────

function RenameModal({ item, onConfirm, onCancel }: {
  item: ExplorerItem
  onConfirm: (newName: string) => Promise<void>
  onCancel: () => void
}) {
  const [name, setName]   = useState(item.name)
  const [busy, setBusy]   = useState(false)
  const [error, setError] = useState('')
  const inputRef          = useRef<HTMLInputElement>(null)

  useEffect(() => { inputRef.current?.focus(); inputRef.current?.select() }, [])
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onCancel() }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [onCancel])

  const canConfirm = name.trim() !== '' && name.trim() !== item.name && !busy

  const handleConfirm = async () => {
    if (!canConfirm) return
    setBusy(true); setError('')
    try { await onConfirm(name.trim()) }
    catch (e) { setError(e instanceof Error ? e.message : 'Erreur'); setBusy(false) }
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)', zIndex: 2000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ background: 'var(--paper)', border: '1px solid var(--rule-2)', borderRadius: 10, padding: '20px 22px', width: 320, boxShadow: 'var(--shadow)' }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 14, color: 'var(--ink)' }}>Renommer "{item.name}"</div>
        <input
          ref={inputRef}
          value={name}
          onChange={e => setName(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') void handleConfirm() }}
          style={{ width: '100%', height: 32, border: '1px solid var(--rule-2)', borderRadius: 5, background: 'var(--bg-deep)', color: 'var(--ink-2)', fontFamily: 'var(--sans)', fontSize: 11, padding: '0 10px', outline: 'none', boxSizing: 'border-box' }}
        />
        {error && <div style={{ fontSize: 10, color: 'var(--err)', fontFamily: 'var(--mono)', marginTop: 6 }}>{error}</div>}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 16 }}>
          <div className="btn ghost" onClick={onCancel} style={{ cursor: 'pointer' }}>Annuler</div>
          <div className="btn primary" onClick={() => void handleConfirm()} style={{ cursor: canConfirm ? 'pointer' : 'default', opacity: canConfirm ? 1 : 0.5 }}>
            {busy ? '…' : 'Renommer'}
          </div>
        </div>
      </div>
    </div>
  )
}

function MoveModal({ items, project, currentSubpath, onConfirm, onCancel }: {
  items: ExplorerItem[]
  project: string
  currentSubpath: string[]
  onConfirm: (newSubpath: string[]) => Promise<void>
  onCancel: () => void
}) {
  const [browsePath, setBrowsePath] = useState<string[]>(currentSubpath)
  const [folders, setFolders]       = useState<string[]>([])
  const [loading, setLoading]       = useState(false)
  const [busy, setBusy]             = useState(false)
  const [error, setError]           = useState('')
  const itemNames = new Set(items.map(i => i.name))

  useEffect(() => {
    setLoading(true)
    api.browseProject(project, browsePath.join('/') || undefined)
      .then(d => {
        const all = d.folders.map(f => f.name)
        const isCurrentParent = browsePath.join('/') === currentSubpath.join('/')
        setFolders(isCurrentParent ? all.filter(n => !itemNames.has(n)) : all)
      })
      .catch(() => setFolders([]))
      .finally(() => setLoading(false))
  }, [project, browsePath, currentSubpath])

  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onCancel() }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [onCancel])

  const isSameLocation  = browsePath.join('/') === currentSubpath.join('/')
  const isInsideItself  = items.some(it => it.isDir &&
    browsePath.length > currentSubpath.length &&
    browsePath.slice(0, currentSubpath.length + 1).join('/') === [...currentSubpath, it.name].join('/'))
  const canConfirm = !isSameLocation && !isInsideItself && !busy

  const handleConfirm = async () => {
    if (!canConfirm) return
    setBusy(true); setError('')
    try { await onConfirm(browsePath) }
    catch (e) { setError(e instanceof Error ? e.message : 'Erreur'); setBusy(false) }
  }

  const breadcrumb = [project, ...browsePath]

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)', zIndex: 2000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ background: 'var(--paper)', border: '1px solid var(--rule-2)', borderRadius: 10, padding: '20px 22px', width: 360, boxShadow: 'var(--shadow)' }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4, color: 'var(--ink)' }}>
          {items.length === 1 ? `Déplacer "${items[0].name}"` : `Déplacer ${items.length} éléments`}
        </div>
        <div style={{ fontSize: 10, color: 'var(--ink-3)', marginBottom: 12 }}>Double-clic pour naviguer dans un dossier</div>

        {/* Breadcrumb */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 3, fontFamily: 'var(--mono)', fontSize: 9, marginBottom: 8, flexWrap: 'wrap' }}>
          {breadcrumb.map((seg, i) => (
            <span key={i} style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
              {i > 0 && <ChevronRight size={8} strokeWidth={1.5} color="var(--ink-4)" />}
              <span
                onClick={() => setBrowsePath(browsePath.slice(0, i))}
                style={{ color: i === breadcrumb.length - 1 ? 'var(--ink)' : 'var(--accent-hi)', fontWeight: i === breadcrumb.length - 1 ? 600 : 400, cursor: i === breadcrumb.length - 1 ? 'default' : 'pointer' }}
              >
                {seg}
              </span>
            </span>
          ))}
        </div>

        {/* Folder list */}
        <div style={{ height: 180, border: '1px solid var(--rule-2)', borderRadius: 6, background: 'var(--bg-deep)', overflowY: 'auto', marginBottom: 10 }}>
          {loading ? (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', fontSize: 11, color: 'var(--ink-4)', fontStyle: 'italic' }}>Chargement…</div>
          ) : folders.length === 0 ? (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', fontSize: 11, color: 'var(--ink-4)', fontStyle: 'italic' }}>Aucun sous-dossier</div>
          ) : folders.map((f, i) => (
            <div
              key={i}
              onDoubleClick={() => setBrowsePath([...browsePath, f])}
              style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 10px', cursor: 'default', borderBottom: '1px solid var(--rule)', fontSize: 11, color: 'var(--ink-2)' }}
              onMouseEnter={e => (e.currentTarget.style.background = 'var(--accent-soft)')}
              onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
            >
              <FolderSvg size={18} />
              <span style={{ fontFamily: 'var(--mono)', fontSize: 10, flex: 1 }}>{f}</span>
              <ChevronRight size={9} strokeWidth={1.5} color="var(--ink-4)" />
            </div>
          ))}
        </div>

        {/* Destination */}
        <div style={{ padding: '5px 8px', borderRadius: 5, border: '1px solid var(--rule-2)', background: 'var(--bg-deep)', fontFamily: 'var(--mono)', fontSize: 9, marginBottom: 10 }}>
          <span style={{ color: 'var(--ink-4)' }}>Destination : </span>
          <span style={{ color: 'var(--ink-2)', fontWeight: 600 }}>{breadcrumb.join(' / ')}</span>
          {isSameLocation && <span style={{ color: 'var(--err)', marginLeft: 6 }}>= emplacement actuel</span>}
          {isInsideItself && <span style={{ color: 'var(--err)', marginLeft: 6 }}>dossier enfant interdit</span>}
        </div>

        {error && <div style={{ fontSize: 10, color: 'var(--err)', fontFamily: 'var(--mono)', marginBottom: 8 }}>{error}</div>}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <div className="btn ghost" onClick={onCancel} style={{ cursor: 'pointer' }}>Annuler</div>
          <div className="btn primary" onClick={() => void handleConfirm()} style={{ cursor: canConfirm ? 'pointer' : 'default', opacity: canConfirm ? 1 : 0.5 }}>
            {busy ? '…' : 'Déplacer ici'}
          </div>
        </div>
      </div>
    </div>
  )
}

function ContextMenu({ x, y, isFavorited, isArchived, locked, canEdit, canDelete, count, onFavorite, onArchive, onToggleLock, onRename, onMove, onDelete, onCopyPath, openInTargets, onClose }: {
  x: number; y: number
  isFavorited: boolean
  isArchived: boolean
  locked: boolean
  canEdit: boolean
  canDelete: boolean
  count: number
  onFavorite:       () => void
  onArchive:        () => void
  onToggleLock?:    () => void
  onRename:         () => void
  onMove:           () => void
  onDelete:         () => void
  onCopyPath?:      () => void
  // Every currently-connected, import-capable DCC for this item (built from live status).
  openInTargets?:   { dcc: string; onClick: () => void }[]
  onClose:          () => void
}) {
  const menuRef = useRef<HTMLDivElement>(null)
  const [openInHovered, setOpenInHovered] = useState(false)

  // Ajuste la position pour rester dans la fenêtre
  const [pos, setPos] = useState({ x, y })
  useEffect(() => {
    if (!menuRef.current) return
    const rect = menuRef.current.getBoundingClientRect()
    const nx = rect.right  > window.innerWidth  ? x - rect.width  : x
    const ny = rect.bottom > window.innerHeight ? y - rect.height : y
    if (nx !== x || ny !== y) setPos({ x: nx, y: ny })
  }, [x, y])

  const row = (label: string, danger = false, onClick?: () => void) => (
    <div
      onClick={onClick}
      style={{
        padding: '6px 12px', fontSize: 11, cursor: onClick ? 'pointer' : 'default',
        color: danger ? 'var(--err)' : 'var(--ink-2)',
        display: 'flex', alignItems: 'center', gap: 7,
        transition: 'background 0.06s',
      }}
      onMouseEnter={e => { if (onClick) e.currentTarget.style.background = danger ? 'rgba(var(--err-rgb),0.1)' : 'var(--accent-soft)' }}
      onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
    >
      {label}
    </div>
  )

  return (
    <div
      ref={menuRef}
      onMouseDown={e => e.stopPropagation()}
      style={{
        position: 'fixed', top: pos.y, left: pos.x, zIndex: 1000,
        background: 'var(--paper)', border: '1px solid var(--rule-2)',
        borderRadius: 7, boxShadow: 'var(--shadow)', minWidth: 180,
        paddingBlock: 4,
      }}
    >
      {row(
        isFavorited ? '★ Retirer des Favoris' : '☆ Ajouter aux Favoris',
        false,
        () => { onFavorite(); onClose() },
      )}
      {row(
        isArchived ? 'Désarchiver' : 'Archiver',
        false,
        () => { onArchive(); onClose() },
      )}
      {onToggleLock && count === 1 && (
        <>
          <div style={{ height: 1, background: 'var(--rule)', margin: '4px 0' }} />
          {row(locked ? '🔓 Déverrouiller' : '🔒 Verrouiller', false, () => { onToggleLock(); onClose() })}
        </>
      )}
      {onCopyPath && count === 1 && (
        <>
          <div style={{ height: 1, background: 'var(--rule)', margin: '4px 0' }} />
          {row('Copier le chemin', false, () => { onCopyPath(); onClose() })}
        </>
      )}
      {canEdit && (
        <>
          <div style={{ height: 1, background: 'var(--rule)', margin: '4px 0' }} />
          {count === 1 && row('Renommer', false, () => { onRename(); onClose() })}
          {!locked && row(count > 1 ? `Déplacer (${count})` : 'Déplacer', false, () => { onMove(); onClose() })}
        </>
      )}
      {openInTargets && openInTargets.length > 0 && (
        <>
          <div style={{ height: 1, background: 'var(--rule)', margin: '4px 0' }} />
          <div
            style={{ position: 'relative' }}
            onMouseEnter={() => setOpenInHovered(true)}
            onMouseLeave={() => setOpenInHovered(false)}
          >
            <div style={{
              padding: '6px 12px', fontSize: 11, cursor: 'pointer',
              color: 'var(--ink-2)', display: 'flex', alignItems: 'center',
              justifyContent: 'space-between', gap: 7,
              background: openInHovered ? 'var(--accent-soft)' : 'transparent',
              transition: 'background 0.06s',
            }}>
              <span>Open in</span>
              <ChevronRight size={11} strokeWidth={2} />
            </div>
            {openInHovered && (
              <div style={{
                position: 'absolute', top: 0, left: '100%',
                background: 'var(--paper)', border: '1px solid var(--rule-2)',
                borderRadius: 7, boxShadow: 'var(--shadow)', minWidth: 140,
                overflow: 'hidden', paddingBlock: 4, zIndex: 1001,
              }}>
                {openInTargets.map(target => (
                  <div
                    key={target.dcc}
                    onClick={() => { target.onClick(); onClose() }}
                    style={{
                      padding: '6px 12px', fontSize: 11, cursor: 'pointer',
                      color: 'var(--ink-2)', display: 'flex', alignItems: 'center', gap: 7,
                      transition: 'background 0.06s',
                    }}
                    onMouseEnter={e => { e.currentTarget.style.background = 'var(--accent-soft)' }}
                    onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
                  >
                    {target.dcc}
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
      {canDelete && !locked && (
        <>
          <div style={{ height: 1, background: 'var(--rule)', margin: '4px 0' }} />
          {row(count > 1 ? `Supprimer (${count})` : 'Supprimer', true, () => { onDelete(); onClose() })}
        </>
      )}
    </div>
  )
}

// ── Delete Confirm Modal ───────────────────────────────────────────────────────

function DeleteModal({ items, onConfirm, onCancel }: {
  items: ExplorerItem[]
  onConfirm: () => void
  onCancel:  () => void
}) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onCancel() }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [onCancel])

  const single = items.length === 1
  const allDirs = items.every(i => i.isDir)

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)', zIndex: 2000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ background: 'var(--paper)', border: '1px solid var(--rule-2)', borderRadius: 10, padding: '22px 24px', minWidth: 300, maxWidth: 380, boxShadow: 'var(--shadow)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
          <Trash2 size={16} strokeWidth={1.75} color="var(--err)" />
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)' }}>
            {single ? `Supprimer "${items[0].name}" ?` : `Supprimer ${items.length} éléments ?`}
          </div>
        </div>
        <div style={{ fontSize: 11, color: 'var(--ink-3)', marginBottom: 20, lineHeight: 1.5 }}>
          {single
            ? items[0].isDir
              ? 'Ce dossier et tout son contenu seront supprimés définitivement.'
              : 'Ce fichier sera supprimé définitivement.'
            : allDirs
              ? 'Ces dossiers et tout leur contenu seront supprimés définitivement.'
              : 'Ces éléments seront supprimés définitivement.'}
          {' '}Cette action est irréversible.
        </div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <div className="btn ghost" onClick={onCancel} style={{ cursor: 'pointer' }}>Annuler</div>
          <div
            className="btn primary"
            onClick={onConfirm}
            style={{ cursor: 'pointer', background: 'var(--err)', borderColor: 'var(--err)' }}
          >
            Supprimer
          </div>
        </div>
      </div>
    </div>
  )
}

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
            Supprimer le projet «&nbsp;{project}&nbsp;» ?
          </div>
        </div>
        <div style={{ fontSize: 11, color: 'var(--ink-3)', marginBottom: 16, lineHeight: 1.5 }}>
          Le dossier du projet et tout son contenu seront retirés définitivement du workspace.
          Cette action est irréversible.
        </div>
        <div style={{ fontSize: 11, color: 'var(--ink-2)', marginBottom: 8, lineHeight: 1.5 }}>
          Tape{' '}
          <code style={{ fontFamily: 'var(--mono)', fontSize: 11, background: 'var(--paper-2)', border: '1px solid var(--rule)', borderRadius: 4, padding: '1px 5px', color: 'var(--ink)' }}>
            {DELETE_PROJECT_PHRASE}
          </code>{' '}
          pour confirmer.
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
          <div className="btn ghost" onClick={onCancel} style={{ cursor: 'pointer' }}>Annuler</div>
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
            Supprimer
          </div>
        </div>
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
        <div style={{ padding: '7px 12px', borderBottom: '1px solid var(--rule)', flexShrink: 0, background: 'var(--paper-2)', fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink-4)' }}>
          {label} · {items.length === 0 ? emptyMsg : `${items.length} élément${items.length > 1 ? 's' : ''}`}
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
                <div style={{ fontSize: 9, fontFamily: 'var(--mono)', color: 'var(--ink-4)', marginTop: 1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
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
          {menuRow('Ouvrir', false, () => { onNavigate(ctx.item); setCtx(null) })}
          {menuRow(removeLabel, false, () => { onRemove(ctx.item); setCtx(null) })}
          {onDeleteProject && isProjectRoot(ctx.item) && (
            <>
              <div style={{ height: 1, background: 'var(--rule)', margin: '4px 0' }} />
              {menuRow('Supprimer définitivement', true, () => { onDeleteProject(ctx.item); setCtx(null) })}
            </>
          )}
        </div>
      )}
    </>
  )
}

// ── Deep-link helper ──────────────────────────────────────────────────────────

function resolveOpenPath(absPath: string, workspace: string): NavLevel | null {
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

// ── Composant principal ───────────────────────────────────────────────────────

export function Projects() {
  const [navStack, setNavStack] = useState<NavLevel[]>([{ kind: 'root' }])
  const [navIdx, setNavIdx]     = useState(0)
  const nav = navStack[navIdx]

  const [items, setItems]                   = useState<ExplorerItem[]>([])
  const [selectedNames, setSelectedNames]   = useState<Set<string>>(new Set())
  const [hoveredName,   setHoveredName]     = useState<string | null>(null)
  const [loading, setLoading]               = useState(false)

  // Active project + list come from the shared ProjectContext. Aliased to the
  // existing local names so the rest of the page is unchanged. Navigating into a
  // project calls setActiveProject -> the explored project becomes active everywhere.
  const { project: activeProject, projects, setProject: setActiveProject, refreshProjects } = useProject()
  const [sequences, setSequences]         = useState<string[]>([])
  // Preset quick-drop (RETAKES-3): the linked presets of the current project.
  const [presets, setPresets]             = useState<Preset[]>([])

  const { settings } = useSettings()
  const dccStatus = useDccStatus()
  const location = useLocation()

  useEffect(() => {
    const openPath = (location.state as { openPath?: string } | null)?.openPath
    if (!openPath || !settings?.workspace) return
    const navLevel = resolveOpenPath(openPath, settings.workspace)
    if (!navLevel) return
    setNavStack([{ kind: 'root' }, navLevel])
    setNavIdx(1)
  }, [settings?.workspace]) // eslint-disable-line react-hooks/exhaustive-deps

  const [tab, setTab]             = useState<Tab>('project')
  const [sidebarTab, setSidebarTab] = useState<SidebarTab>('tous')

  // Explorer tile size (small / medium / large), persisted per-browser
  const [tileSize, setTileSize]   = useState<TileSize>(loadTileSize)
  const changeTileSize = useCallback((s: TileSize) => {
    setTileSize(s)
    try { localStorage.setItem(TILE_SIZE_KEY, s) } catch { /* localStorage unavailable */ }
  }, [])

  // Saved lists — persisted per-user on the Flux drive (USER/<user>/UserSettings/User.json)
  const [favorites, setFavorites] = useState<SavedItem[]>([])
  const [archived,  setArchived]  = useState<SavedItem[]>([])
  const [recents,   setRecents]   = useState<SavedItem[]>([])
  const savedLoaded = useRef(false)

  // Context menu & delete confirm
  const [ctxMenu,        setCtxMenu]        = useState<CtxMenu | null>(null)
  const [deleteConfirm,  setDeleteConfirm]  = useState<ExplorerItem[] | null>(null)
  const [deleteProjectTarget, setDeleteProjectTarget] = useState<SavedItem | null>(null)
  const [deleteError,    setDeleteError]    = useState('')
  const [renameTarget,   setRenameTarget]   = useState<ExplorerItem | null>(null)
  const [moveTarget,     setMoveTarget]     = useState<ExplorerItem[] | null>(null)

  // Token Finder & Search
  const [tokenSel, setTokenSel]           = useState<TokenSel>(EMPTY_TOKEN_SEL)
  const [projectTokens, setProjectTokens] = useState<Record<string, Record<string, string>>>({})
  const [tokenRefreshTick, setTokenRefreshTick] = useState(0)
  const [searchQuery, setSearchQuery]     = useState('')
  const [searchResults, setSearchResults] = useState<FindResult[] | null>(null)
  const [findLoading, setFindLoading]     = useState(false)
  const [resultLabel, setResultLabel]     = useState('')

  // Editable / copy-paste path bar
  const [editingPath, setEditingPath] = useState(false)
  const [pathDraft, setPathDraft]     = useState('')
  const [pathError, setPathError]     = useState('')

  // File clipboard + drag & drop
  const [clipboard, setClipboard]   = useState<Clip | null>(null)
  const [dragOverName, setDragOverName] = useState<string | null>(null)
  const [dragOverBc, setDragOverBc]     = useState<number | null>(null)
  const [dragOverUp, setDragOverUp]     = useState(false)
  const [undoStack, setUndoStack]       = useState<UndoOp[]>([])
  const [locks, setLocks]               = useState<Set<string>>(new Set())  // locked rel paths, current project
  const dragNamesRef = useRef<string[]>([])

  const lastClickedRef = useRef<string | null>(null)

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

  // ── Close context menu on outside click / Escape ───────────────────────────

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

  // ── Locks ──────────────────────────────────────────────────────────────────

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
      toast.success(willLock ? `"${item.name}" verrouillé` : `"${item.name}" déverrouillé`)
    } catch (e) {
      toast.error(`Verrou : ${e instanceof Error ? e.message : 'échec'}`)
    }
  }, [nav, locks, lockRelOf])

  // ── Delete key on selected item ────────────────────────────────────────────

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === 'Delete' && selectedNames.size > 0 && !deleteConfirm && nav.kind === 'inside') {
        const targets = items.filter(it => selectedNames.has(it.name))
        if (targets.some(isItemLocked)) { toast.error('Élément verrouillé — déverrouillez d’abord'); return }
        if (targets.length > 0) setDeleteConfirm(targets)
      }
    }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [selectedNames, items, deleteConfirm, nav, isItemLocked])

  // ── Dérivés ────────────────────────────────────────────────────────────────

  const breadcrumb: string[] = nav.kind === 'root'
    ? ['PROJETS']
    : ['PROJETS', nav.project, ...nav.subpath]

  const navProject: string = nav.kind === 'inside' ? nav.project : ''
  const contextProject: string | null =
    navProject !== '' ? navProject
    : (selectedNames.size === 1 && projects.includes([...selectedNames][0])) ? [...selectedNames][0]
    : null

  // Exploring a project makes it the active project everywhere (shared context).
  useEffect(() => {
    if (navProject && navProject !== activeProject) setActiveProject(navProject)
  }, [navProject])  // eslint-disable-line react-hooks/exhaustive-deps

  const canBack    = navIdx > 0
  const canForward = navIdx < navStack.length - 1

  // ── Navigation ─────────────────────────────────────────────────────────────

  const navigateTo = useCallback((level: NavLevel) => {
    setNavStack(prev => [...prev.slice(0, navIdx + 1), level])
    setNavIdx(i => i + 1)
    setSelectedNames(new Set())
    setSearchResults(null)
    setSearchQuery('')
    lastClickedRef.current = null
  }, [navIdx])

  const goBack = useCallback(() => {
    if (navIdx > 0) { setNavIdx(i => i - 1); setSelectedNames(new Set()); setSearchResults(null); setSearchQuery(''); lastClickedRef.current = null }
  }, [navIdx])

  const goForward = useCallback(() => {
    if (navIdx < navStack.length - 1) { setNavIdx(i => i + 1); setSelectedNames(new Set()); setSearchResults(null); setSearchQuery('') }
  }, [navIdx, navStack.length])

  const navigateToBreadcrumb = useCallback((segIdx: number) => {
    if (segIdx === 0) navigateTo({ kind: 'root' })
    else if (nav.kind === 'inside')
      navigateTo({ kind: 'inside', project: nav.project, subpath: nav.subpath.slice(0, segIdx - 1) })
  }, [nav, navigateTo])

  // ── Path bar (copy / paste-to-navigate) ────────────────────────────────────

  // Absolute Windows/POSIX path of the current location, on the Flux drive.
  const currentAbsPath = useCallback((): string => {
    const ws = settings?.workspace
    if (!ws) return ''
    const sep = ws.includes('\\') ? '\\' : '/'
    const base = [ws.replace(/[\\/]+$/, ''), 'DOSSIER_PROJETS']
    if (nav.kind === 'inside') base.push(nav.project, ...nav.subpath)
    return base.join(sep)
  }, [settings?.workspace, nav])

  // Parse a pasted/typed path → NavLevel. Accepts:
  //  - absolute Windows (C:\…\DOSSIER_PROJETS\PROJ\sub) or UNC/POSIX under the workspace
  //  - relative "PROJ/sub" or "DOSSIER_PROJETS/PROJ/sub" (both separators)
  const parsePathToNav = useCallback((raw: string): NavLevel | null => {
    const s = raw.trim().replace(/^["']+|["']+$/g, '')
    if (!s) return null
    const ws = settings?.workspace ?? ''
    const isAbs = /^[a-zA-Z]:[\\/]/.test(s) || s.startsWith('\\\\') || s.startsWith('/')
    if (isAbs) return ws ? resolveOpenPath(s, ws) : null
    let norm = s.replace(/\\/g, '/').replace(/^\/+|\/+$/g, '')
    const mk = 'DOSSIER_PROJETS/'
    const idx = norm.toUpperCase().indexOf(mk)
    if (idx !== -1) norm = norm.slice(idx + mk.length)
    const parts = norm.split('/').filter(Boolean)
    if (parts.length && parts[0].toUpperCase() === 'PROJETS') parts.shift()  // breadcrumb prefix
    if (parts.length === 0) return { kind: 'root' }
    const [project, ...subpath] = parts
    return { kind: 'inside', project, subpath }
  }, [settings?.workspace])

  const commitPathValue = useCallback(async (raw: string) => {
    const target = parsePathToNav(raw)
    if (!target) { setPathError('Chemin invalide (hors du workspace FLUX ?)'); return }
    if (target.kind === 'root') { setEditingPath(false); setPathError(''); navigateTo({ kind: 'root' }); return }
    try {
      await api.browseProject(target.project, target.subpath.join('/') || undefined)  // throws on 404
      setEditingPath(false); setPathError(''); navigateTo(target)
    } catch {
      setPathError('Chemin introuvable dans le workspace FLUX')
    }
  }, [parsePathToNav, navigateTo])

  const copyCurrentPath = useCallback(() => {
    const p = currentAbsPath()
    if (!p) return
    navigator.clipboard.writeText(p).then(
      () => toast.success('Chemin copié'),
      () => toast.error('Copie impossible'),
    )
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

  // ── Saved-list helpers ─────────────────────────────────────────────────────

  const isItemFavorited = useCallback((item: ExplorerItem): boolean => {
    const k = currentItemKey(item, nav)
    return favorites.some(s => savedKey(s) === k)
  }, [favorites, nav])

  const isItemArchived = useCallback((item: ExplorerItem): boolean => {
    const k = currentItemKey(item, nav)
    return archived.some(s => savedKey(s) === k)
  }, [archived, nav])

  const addToRecents = useCallback((item: ExplorerItem, forNav: NavLevel) => {
    const s = makeSavedItem(item, forNav)
    const k = savedKey(s)
    setRecents(prev => {
      const filtered = prev.filter(x => savedKey(x) !== k)
      return [s, ...filtered].slice(0, 20)
    })
  }, [])

  const toggleFavorite = useCallback((item: ExplorerItem) => {
    const s = makeSavedItem(item, nav)
    const k = savedKey(s)
    setFavorites(prev =>
      prev.some(x => savedKey(x) === k)
        ? prev.filter(x => savedKey(x) !== k)
        : [s, ...prev]
    )
  }, [nav])

  const toggleArchived = useCallback((item: ExplorerItem) => {
    const s = makeSavedItem(item, nav)
    const k = savedKey(s)
    setArchived(prev =>
      prev.some(x => savedKey(x) === k)
        ? prev.filter(x => savedKey(x) !== k)
        : [s, ...prev]
    )
  }, [nav])

  const removeFromSaved = useCallback((s: SavedItem, list: 'favorites' | 'archived' | 'recents') => {
    const k = savedKey(s)
    if (list === 'favorites') setFavorites(prev => prev.filter(x => savedKey(x) !== k))
    if (list === 'archived')  setArchived(prev  => prev.filter(x => savedKey(x) !== k))
    if (list === 'recents')   setRecents(prev   => prev.filter(x => savedKey(x) !== k))
  }, [])

  const navigateToSaved = useCallback((s: SavedItem) => {
    navigateTo(navigateTargetFor(s))
    setSidebarTab('tous')
  }, [navigateTo])

  // ── Chargement items ───────────────────────────────────────────────────────

  const loadItems = useCallback(async () => {
    setLoading(true)
    try {
      if (nav.kind === 'root') {
        const d = await api.getProjects()
        void refreshProjects()  // keep the shared context list in sync
        setItems(d.projects.map(name => ({ name, isDir: true })))
      } else {
        const subpath = nav.subpath.join('/')
        const d = await api.browseProject(nav.project, subpath || undefined)
        setItems([
          ...d.folders.map(f => ({ name: f.name, isDir: true })),
          ...(d.files ?? []).map(f => ({ name: f.name, isDir: false })),
        ])
      }
    } catch { setItems([]) }
    finally { setLoading(false) }
  }, [nav])

  useEffect(() => { void loadItems() }, [loadItems])

  // ── Presets (quick-drop into the current folder) ────────────────────────────
  // Reload the project's presets when entering a project, and whenever the
  // Template Editor edits them (global flux:refresh event).
  const loadPresets = useCallback(async () => {
    if (nav.kind !== 'inside') { setPresets([]); return }
    try { const d = await api.listPresets(nav.project); setPresets(d.presets) }
    catch { setPresets([]) }
  }, [nav])

  useEffect(() => { void loadPresets() }, [loadPresets])

  useEffect(() => {
    const onRefresh = () => void loadPresets()
    window.addEventListener('flux:refresh', onRefresh)
    return () => window.removeEventListener('flux:refresh', onRefresh)
  }, [loadPresets])

  // Drop a preset's linked file into the folder currently being browsed.
  const dropPresetHere = useCallback(async (p: Preset) => {
    if (nav.kind !== 'inside') return
    try {
      const r = await api.dropPreset(nav.project, p.id, nav.subpath.join('/'))
      toast.success(`${r.name} déposé ici`)
      void loadItems()
    } catch (e) {
      toast.error(`Dépôt : ${e instanceof Error ? e.message : 'échec'}`)
    }
  }, [nav, loadItems])

  const loadSequences = useCallback(async () => {
    if (!activeProject) return
    try { const d = await api.getSequences(activeProject); setSequences(d.sequences) }
    catch {}
  }, [activeProject])

  useEffect(() => { void loadSequences() }, [activeProject])

  // Fetch tokens.json for the active/nav project whenever project or tick changes
  const tokensProject = navProject || activeProject
  useEffect(() => {
    if (!tokensProject) { setProjectTokens({}); return }
    api.getTokens(tokensProject).then(d => setProjectTokens(d.tokens)).catch(() => setProjectTokens({}))
  }, [tokensProject, tokenRefreshTick])

  // Load folder locks for the browsed project
  const lockProject = nav.kind === 'inside' ? nav.project : ''
  useEffect(() => {
    if (!lockProject) { setLocks(new Set()); return }
    api.getLocks(lockProject).then(d => setLocks(new Set(d.locked))).catch(() => setLocks(new Set()))
  }, [lockProject])

  // ── Find / Search ──────────────────────────────────────────────────────────

  const handleFind = useCallback(async () => {
    const proj = navProject || activeProject
    if (!proj) return
    setFindLoading(true)
    setSearchResults([])
    const results: FindResult[] = []

    const classTokens    = projectTokens.CLASS    ?? {}
    const typeTokens     = projectTokens.TYPE      ?? {}

    if (tokenSel.mode === 'shot') {
      setResultLabel('Shot Finder')

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
      setResultLabel('Finder')
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

    setSearchResults(results)
    setFindLoading(false)
  }, [tokenSel, navProject, activeProject, projectTokens])

  const handleSearch = useCallback(async (query: string) => {
    if (!query.trim()) { setSearchResults(null); return }
    const proj = navProject || activeProject
    if (!proj) return
    setFindLoading(true)
    setSearchResults([])
    setResultLabel(`«${query}»`)
    const results: FindResult[] = []
    const q = query.toLowerCase()
    const classBasePaths = Object.values(projectTokens.CLASS ?? {})
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
      } catch {}
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

  // ── Handlers ───────────────────────────────────────────────────────────────

  const pushUndo = useCallback((op: UndoOp) => {
    if (op.actions.length === 0) return
    setUndoStack(prev => [...prev, op].slice(-50))
  }, [])

  const handleDoubleClick = useCallback((item: ExplorerItem) => {
    if (!item.isDir) return
    addToRecents(item, nav)
    if (nav.kind === 'root') navigateTo({ kind: 'inside', project: item.name, subpath: [] })
    else navigateTo({ kind: 'inside', project: nav.project, subpath: [...nav.subpath, item.name] })
  }, [nav, navigateTo, addToRecents])

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
  }, [selectedNames, items])

  const handleSetProject = useCallback((name: string) => {
    setActiveProject(name)
    void api.updateSettings({ last_project: name })
  }, [])

  const handleCreateProject = useCallback(async (name: string) => {
    await api.createProject(name)
    await loadItems()
    setActiveProject(name)
  }, [loadItems])

  const handleCreateAsset = useCallback(async (project: string, cls: string, name: string) => {
    await api.createAsset(project, cls, name)
    await loadItems()
  }, [loadItems])

  const handleCreateSequence = useCallback(async (project: string, seqN: number) => {
    await api.createSequence(project, seqN)
    await loadItems()
  }, [loadItems])

  const handleCreateShot = useCallback(async (project: string, seqN: number, shotN: number) => {
    await api.createShot(project, seqN, shotN)
    await loadItems()
  }, [loadItems])

  const handleRename = useCallback(async (item: ExplorerItem, newName: string) => {
    if (nav.kind !== 'inside') return
    await api.patchItem(nav.project, nav.subpath, item.name, newName)
    pushUndo({ label: `renommage "${item.name}"`, actions: [{ kind: 'rename', project: nav.project, sub: nav.subpath, oldName: item.name, newName }] })
    const oldKey = currentItemKey(item, nav)
    setFavorites(prev => prev.map(s => savedKey(s) === oldKey ? { ...s, label: newName } : s))
    setRecents(prev   => prev.map(s => savedKey(s) === oldKey ? { ...s, label: newName } : s))
    setRenameTarget(null)
    await loadItems()
  }, [nav, loadItems, pushUndo])

  const handleOpenInHoudini = useCallback(async (item: ExplorerItem) => {
    if (nav.kind !== 'inside') return
    const rel_path = [...nav.subpath, item.name].join('/')
    try {
      const tok = await api.getFluxTokensFromPath(nav.project, rel_path)
      const res = await api.createFluxImporterNode({
        project:       nav.project,
        flux_class:    tok.CLASS,
        flux_type:     tok.TYPE,
        flux_name:     tok.NAME,
        flux_instance: tok.INSTANCE,
        flux_iter:     'LAST',
        rel_path,   // exact file selected → used to re-path a selected node
      })
      // Node is created but resolve can still find nothing (asset missing for these
      // tokens, or FLUX unreachable from Houdini) — warn instead of a false success.
      if (res.result?.mode === 'replaced') {
        toast.success(`${item.name} : path mis à jour sur le node sélectionné`)
      } else if (res.result?.resolved_path) {
        toast.success(`${item.name} importé dans Houdini`)
      } else {
        toast.warning(`Node créé mais fichier non résolu pour ${item.name} — clique ↺ Resolve dans le node`)
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Erreur inconnue'
      const offline = /urlopen|refused|connect|actively refused|WinError/i.test(msg)
      toast.error(offline
        ? 'Houdini non connecté : lance le serveur FLUX dans Houdini'
        : `Import Houdini échoué : ${msg}`)
    }
  }, [nav])

  const MAYA_IMPORT_EXTS = new Set(['.obj', '.fbx', '.ma', '.mb', '.abc', '.usd', '.usda', '.usdc', '.usdz'])

  const handleOpenInMaya = useCallback(async (item: ExplorerItem) => {
    if (nav.kind !== 'inside') return
    const rel_path = [...nav.subpath, item.name].join('/')
    try {
      await api.importFileInMaya(nav.project, rel_path, readActiveInstancePort('Maya') ?? undefined)
      toast.success(`${item.name} importé dans Maya`)
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Erreur inconnue'
      toast.error(msg.includes('répond pas')
        ? 'Maya non connecté : ouvre Maya avec le bridge FLUX actif (commandPort 7001)'
        : `Import Maya échoué : ${msg}`)
    }
  }, [nav])

  // "Open in" targets = every currently-CONNECTED DCC that can import this file.
  // Only Maya & Houdini have an import bridge today; add a branch here to onboard more.
  const buildOpenInTargets = useCallback((items: ExplorerItem[]): { dcc: string; onClick: () => void }[] => {
    if (nav.kind !== 'inside' || items.length !== 1) return []
    const item = items[0]
    if (item.isDir) return []
    const ext = '.' + (item.name.split('.').pop() ?? '').toLowerCase()
    const targets: { dcc: string; onClick: () => void }[] = []
    if (dccStatus['Houdini']?.connected) {
      targets.push({ dcc: 'Houdini', onClick: () => void handleOpenInHoudini(item) })
    }
    if (dccStatus['Maya']?.connected && MAYA_IMPORT_EXTS.has(ext)) {
      targets.push({ dcc: 'Maya', onClick: () => void handleOpenInMaya(item) })
    }
    return targets
  }, [nav, dccStatus, handleOpenInHoudini, handleOpenInMaya, MAYA_IMPORT_EXTS])

  const handleMove = useCallback(async (targets: ExplorerItem[], newSubpath: string[]) => {
    if (nav.kind !== 'inside') return
    const undoActions: UndoAction[] = []
    for (const item of targets) {
      await api.patchItem(nav.project, nav.subpath, item.name, undefined, newSubpath)
      undoActions.push({ kind: 'move', project: nav.project, fromSub: nav.subpath, toSub: newSubpath, name: item.name })
      const k = currentItemKey(item, nav)
      setFavorites(prev => prev.filter(s => savedKey(s) !== k))
      setRecents(prev   => prev.filter(s => savedKey(s) !== k))
    }
    pushUndo({ label: `déplacement (${undoActions.length})`, actions: undoActions })
    setMoveTarget(null)
    setSelectedNames(new Set())
    await loadItems()
  }, [nav, loadItems, pushUndo])

  // ── Clipboard (copy / cut / paste) + drag & drop ───────────────────────────

  const uniqueName = (base: string, existing: Set<string>): string => {
    if (!existing.has(base)) return base
    const dot  = base.lastIndexOf('.')
    const stem = dot > 0 ? base.slice(0, dot) : base
    const ext  = dot > 0 ? base.slice(dot) : ''
    let n = 2
    while (existing.has(`${stem} (${n})${ext}`)) n++
    return `${stem} (${n})${ext}`
  }

  const copySelection = useCallback(() => {
    if (nav.kind !== 'inside' || selectedNames.size === 0) return
    const sel = items.filter(i => selectedNames.has(i.name))
    setClipboard({ op: 'copy', project: nav.project, subpath: nav.subpath, items: sel })
    toast.success(`${sel.length} élément(s) copié(s)`)
  }, [nav, selectedNames, items])

  const cutSelection = useCallback(() => {
    if (nav.kind !== 'inside' || selectedNames.size === 0) return
    const sel = items.filter(i => selectedNames.has(i.name))
    const cuttable = sel.filter(i => !isItemLocked(i))
    if (cuttable.length < sel.length) toast.error(`${sel.length - cuttable.length} verrouillé(s) — non coupé(s)`)
    if (cuttable.length === 0) return
    setClipboard({ op: 'cut', project: nav.project, subpath: nav.subpath, items: cuttable })
  }, [nav, selectedNames, items, isItemLocked])

  const selectAll = useCallback(() => {
    setSelectedNames(new Set(items.filter(i => !isItemArchived(i)).map(i => i.name)))
  }, [items, isItemArchived])

  const pasteClipboard = useCallback(async () => {
    if (!clipboard || nav.kind !== 'inside') return
    if (clipboard.project !== nav.project) { toast.error('Collage entre projets non supporté'); return }
    const destSub = nav.subpath
    const sameFolder = clipboard.subpath.join('/') === destSub.join('/')
    if (clipboard.op === 'cut' && sameFolder) return  // no-op
    const existing = new Set(items.map(i => i.name))
    const undoActions: UndoAction[] = []
    let ok = 0
    for (const it of clipboard.items) {
      try {
        if (clipboard.op === 'cut') {
          await api.patchItem(clipboard.project, clipboard.subpath, it.name, undefined, destSub)
          undoActions.push({ kind: 'move', project: clipboard.project, fromSub: clipboard.subpath, toSub: destSub, name: it.name })
          const k = itemKey(clipboard.project, clipboard.subpath, it.name)
          setFavorites(prev => prev.filter(s => savedKey(s) !== k))
          setRecents(prev   => prev.filter(s => savedKey(s) !== k))
        } else {
          const target = uniqueName(it.name, existing)
          await api.copyItem(clipboard.project, clipboard.subpath, it.name, destSub, target === it.name ? undefined : target)
          undoActions.push({ kind: 'copy', project: clipboard.project, sub: destSub, name: target })
          existing.add(target)
        }
        ok++
      } catch (e) {
        toast.error(`${it.name} : ${e instanceof Error ? e.message : 'échec'}`)
      }
    }
    pushUndo({ label: clipboard.op === 'cut' ? `déplacement (${undoActions.length})` : `copie (${undoActions.length})`, actions: undoActions })
    if (clipboard.op === 'cut') setClipboard(null)
    if (ok > 0) { toast.success(`${ok} élément(s) ${clipboard.op === 'cut' ? 'déplacé(s)' : 'copié(s)'}`); await loadItems() }
  }, [clipboard, nav, items, loadItems, pushUndo])

  // Drag & drop: move `names` from the current folder into destSub (a folder within the project)
  const moveNamesTo = useCallback(async (names: string[], destSub: string[]) => {
    if (nav.kind !== 'inside' || names.length === 0) return
    if (destSub.join('/') === nav.subpath.join('/')) return  // same folder → no-op
    const all = items.filter(i => names.includes(i.name))
    const targets = all.filter(i => !isItemLocked(i))
    if (targets.length < all.length) toast.error(`${all.length - targets.length} verrouillé(s) — non déplacé(s)`)
    if (targets.length === 0) return
    const undoActions: UndoAction[] = []
    let ok = 0
    for (const it of targets) {
      try {
        await api.patchItem(nav.project, nav.subpath, it.name, undefined, destSub)
        undoActions.push({ kind: 'move', project: nav.project, fromSub: nav.subpath, toSub: destSub, name: it.name })
        const k = currentItemKey(it, nav)
        setFavorites(prev => prev.filter(s => savedKey(s) !== k))
        setRecents(prev   => prev.filter(s => savedKey(s) !== k))
        ok++
      } catch (e) {
        toast.error(`${it.name} : ${e instanceof Error ? e.message : 'échec'}`)
      }
    }
    pushUndo({ label: `déplacement (${undoActions.length})`, actions: undoActions })
    setSelectedNames(new Set())
    if (ok > 0) { toast.success(`${ok} élément(s) déplacé(s)`); await loadItems() }
  }, [nav, items, loadItems, pushUndo, isItemLocked])

  const undoLast = useCallback(async () => {
    const op = undoStack[undoStack.length - 1]
    if (!op) { toast('Rien à annuler'); return }
    setUndoStack(prev => prev.slice(0, -1))
    let ok = 0
    for (const a of [...op.actions].reverse()) {
      try {
        if (a.kind === 'move')        await api.patchItem(a.project, a.toSub, a.name, undefined, a.fromSub)
        else if (a.kind === 'rename') await api.patchItem(a.project, a.sub, a.newName, a.oldName)
        else if (a.kind === 'copy')   await api.deleteItem(a.project, a.sub, a.name)
        ok++
      } catch (e) {
        toast.error(`Annulation : ${e instanceof Error ? e.message : 'échec'}`)
      }
    }
    if (ok > 0) { toast.success(`Annulé : ${op.label}`); await loadItems() }
  }, [undoStack, loadItems])

  // Clipboard / select-all keyboard shortcuts (guarded against inputs, modals, path bar)
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null
      const typing = !!t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)
      if (typing || editingPath) return
      if (renameTarget || moveTarget || deleteConfirm) return
      if (t && t.closest && t.closest('[data-flux-pathbar]')) return  // path bar owns its own Ctrl+C/V
      if (!(e.ctrlKey || e.metaKey)) return
      const k = e.key.toLowerCase()
      if (k === 'c') copySelection()
      else if (k === 'x') cutSelection()
      else if (k === 'v') { e.preventDefault(); void pasteClipboard() }
      else if (k === 'a') { e.preventDefault(); selectAll() }
      else if (k === 'z') { e.preventDefault(); void undoLast() }
    }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [copySelection, cutSelection, pasteClipboard, selectAll, undoLast, editingPath, renameTarget, moveTarget, deleteConfirm])

  const handleDelete = useCallback(async (targets: ExplorerItem[]) => {
    if (nav.kind !== 'inside') return
    setDeleteConfirm(null)
    setDeleteError('')
    try {
      for (const item of targets) {
        await api.deleteItem(nav.project, nav.subpath, item.name)
        const k = currentItemKey(item, nav)
        setFavorites(prev => prev.filter(s => savedKey(s) !== k))
        setArchived(prev  => prev.filter(s => savedKey(s) !== k))
        setRecents(prev   => prev.filter(s => savedKey(s) !== k))
      }
      setSelectedNames(new Set())
      await loadItems()
    } catch (e) {
      setDeleteError(e instanceof Error ? e.message : 'Erreur lors de la suppression')
    }
  }, [nav, loadItems])

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
      toast.success(`Projet "${name}" supprimé`)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Suppression du projet échouée')
    } finally {
      setDeleteProjectTarget(null)
    }
  }, [refreshProjects, activeProject, projects, setActiveProject])

  const handleCopyPath = useCallback(async (item: ExplorerItem) => {
    const ws = settings?.workspace
    if (!ws) return
    const sep = ws.includes('\\') ? '\\' : '/'
    const parts = nav.kind === 'root'
      ? [ws, 'DOSSIER_PROJETS', item.name]
      : [ws, 'DOSSIER_PROJETS', nav.project, ...nav.subpath, item.name]
    try {
      await navigator.clipboard.writeText(parts.join(sep))
      toast.success('Chemin copié')
    } catch {
      toast.error('Impossible de copier le chemin')
    }
  }, [nav, settings?.workspace])

  const recentSidebarItems = recents.slice(0, 5)

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>

      {/* En-tête */}
      <div style={{ padding: '12px 20px', borderBottom: '1px solid var(--rule)', flexShrink: 0, display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{ fontSize: 13, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.1em', color: 'var(--ink)' }}>Folder Manager</div>
        <div style={{ flex: 1 }} />
      </div>

      {/* Barre de navigation */}
      <div style={{ padding: '6px 10px 7px', borderBottom: '1px solid var(--rule)', background: 'var(--paper-2)', flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 5 }}>

        {/* Ligne 1 : back/fwd/undo + breadcrumb + search */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {(() => {
            const navBtn = (ok: boolean): React.CSSProperties => ({ width: 24, height: 24, border: '1px solid var(--rule-2)', borderRadius: 5, display: 'flex', alignItems: 'center', justifyContent: 'center', color: ok ? 'var(--ink-2)' : 'var(--ink-4)', boxShadow: 'var(--shadow-xs)', cursor: ok ? 'pointer' : 'default', opacity: ok ? 1 : 0.4, flexShrink: 0, transition: 'background 0.1s, border-color 0.1s, color 0.1s' })
            const upDroppable = nav.kind === 'inside' && nav.subpath.length >= 1
            return (
              <>
                {/* Retour — clic: historique ; déposer ici: monter d'un niveau */}
                <div
                  onClick={canBack ? goBack : undefined}
                  onDragOver={upDroppable ? (e => { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; if (!dragOverUp) setDragOverUp(true) }) : undefined}
                  onDragLeave={upDroppable ? (() => setDragOverUp(false)) : undefined}
                  onDrop={upDroppable ? (e => { e.preventDefault(); e.stopPropagation(); setDragOverUp(false); void moveNamesTo(dragNamesRef.current, (nav.kind === 'inside' ? nav.subpath : []).slice(0, -1)) }) : undefined}
                  title={upDroppable ? 'Retour · déposer ici pour monter d’un niveau' : 'Retour'}
                  style={{ ...navBtn(canBack || upDroppable), ...(dragOverUp ? { borderColor: 'var(--accent)', background: 'var(--accent-soft)', color: 'var(--accent-hi)' } : {}) }}
                >
                  <ChevronLeft size={13} strokeWidth={2} />
                </div>
                {/* Suivant */}
                <div onClick={canForward ? goForward : undefined} title="Suivant" style={navBtn(canForward)}>
                  <ChevronRight size={13} strokeWidth={2} />
                </div>
                {/* Annuler (Ctrl+Z) */}
                <div onClick={undoStack.length > 0 ? () => void undoLast() : undefined} title="Annuler (Ctrl+Z)" style={navBtn(undoStack.length > 0)}>
                  <RotateCcw size={12} strokeWidth={2} />
                </div>
              </>
            )
          })()}

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
              placeholder="Coller un chemin (C:\… ou PROJET/sous-dossier) puis Entrée"
              style={{ flex: 1, minWidth: 0, height: 24, border: '1px solid ' + (pathError ? 'var(--err)' : 'var(--accent)'), padding: '0 8px', background: 'var(--bg-deep)', borderRadius: 5, boxShadow: 'var(--shadow-inset)', fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink)', outline: 'none' }}
            />
          ) : (
            <div
              data-flux-pathbar
              tabIndex={0}
              title="Cliquer pour éditer · Ctrl+C copier le chemin · Ctrl+V coller un chemin pour y naviguer"
              onClick={startEditPath}
              onKeyDown={e => {
                if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'c') { e.preventDefault(); copyCurrentPath() }
                else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'v') { e.preventDefault(); void pasteNavigate() }
              }}
              style={{ flex: 1, minWidth: 0, display: 'flex', alignItems: 'center', gap: 2, fontFamily: 'var(--mono)', fontSize: 10, height: 24, border: '1px solid var(--rule)', padding: '0 4px 0 8px', background: 'var(--bg-deep)', borderRadius: 5, boxShadow: 'var(--shadow-inset)', overflow: 'hidden', cursor: 'text', outline: 'none' }}
            >
              <div style={{ flex: 1, minWidth: 0, display: 'flex', alignItems: 'center', gap: 2, overflow: 'hidden' }}>
                {breadcrumb.map((seg, i) => {
                  const isLast = i === breadcrumb.length - 1
                  return (
                    <span key={i} style={{ display: 'flex', alignItems: 'center', gap: 2, flexShrink: isLast ? 0 : 1, minWidth: isLast ? 'auto' : 0 }}>
                      {i > 0 && <ChevronRight size={9} strokeWidth={1.5} color="var(--ink-4)" style={{ flexShrink: 0 }} />}
                      <span
                        onClick={!isLast ? (e) => { e.stopPropagation(); navigateToBreadcrumb(i) } : undefined}
                        onDragOver={!isLast && i >= 1 ? (e => { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; if (dragOverBc !== i) setDragOverBc(i) }) : undefined}
                        onDragLeave={!isLast && i >= 1 ? (() => setDragOverBc(prev => (prev === i ? null : prev))) : undefined}
                        onDrop={!isLast && i >= 1 && nav.kind === 'inside' ? (e => {
                          e.preventDefault(); e.stopPropagation(); setDragOverBc(null)
                          void moveNamesTo(dragNamesRef.current, nav.subpath.slice(0, i - 1))
                        }) : undefined}
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
                title="Copier le chemin"
                style={{ flexShrink: 0, width: 18, height: 18, display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: 4, color: 'var(--ink-4)', cursor: 'pointer' }}
                onMouseEnter={e => { e.currentTarget.style.background = 'var(--accent-soft)'; e.currentTarget.style.color = 'var(--accent-hi)' }}
                onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--ink-4)' }}
              >
                <Copy size={11} strokeWidth={1.75} />
              </div>
            </div>
          )}

          {/* Search */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 5, border: '1px solid var(--rule-2)', padding: '0 6px', height: 24, width: 150, background: 'var(--bg-deep)', borderRadius: 5, boxShadow: 'var(--shadow-inset)', flexShrink: 0 }}>
            <Search size={10} strokeWidth={2} color="var(--ink-4)" style={{ flexShrink: 0 }} />
            <input
              value={searchQuery}
              onChange={e => { setSearchQuery(e.target.value); if (!e.target.value) setSearchResults(null) }}
              onKeyDown={e => { if (e.key === 'Enter') void handleSearch(searchQuery) }}
              placeholder="Rechercher…"
              style={{ flex: 1, background: 'transparent', border: 'none', outline: 'none', fontSize: 10, color: 'var(--ink-2)', fontFamily: 'var(--sans)' }}
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
          <div style={{ fontFamily: 'var(--mono)', fontSize: 9, color: 'var(--err)', padding: '0 2px' }}>
            {pathError}
          </div>
        )}

        {/* Ligne 2 : Token Finder + Find */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <TokenFinder project={navProject || activeProject} onChange={setTokenSel} />
          <div
            onClick={() => void handleFind()}
            className="btn primary"
            style={{ height: 30, padding: '0 14px', flexShrink: 0, display: 'flex', alignItems: 'center', fontSize: 10, cursor: findLoading ? 'wait' : 'pointer' }}
          >
            {findLoading ? '…' : 'Find'}
          </div>
          {clipboard && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0, padding: '0 8px', height: 30, border: '1px solid var(--rule-2)', borderRadius: 5, background: 'var(--bg-deep)', fontFamily: 'var(--mono)', fontSize: 9, color: 'var(--ink-3)', boxShadow: 'var(--shadow-inset)' }}>
              <Copy size={10} strokeWidth={1.75} color="var(--ink-4)" />
              <span>{clipboard.items.length} {clipboard.op === 'cut' ? 'coupé(s)' : 'copié(s)'}</span>
              <X size={10} strokeWidth={2} style={{ cursor: 'pointer' }} onClick={() => setClipboard(null)} />
            </div>
          )}
        </div>
      </div>

      {/* Corps */}
      <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>

        {/* Sidebar gauche */}
        <div style={{ width: 170, borderRight: '1px solid var(--rule)', display: 'flex', flexDirection: 'column', background: 'var(--paper-2)', flexShrink: 0 }}>
          <div style={{ padding: '8px 0 4px' }}>
            {SIDEBAR_TABS.map(({ id, label, icon: Icon }) => {
              const active = sidebarTab === id
              return (
                <div
                  key={id}
                  onClick={() => { setSidebarTab(id); if (id === 'tous') navigateTo({ kind: 'root' }) }}
                  style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 10px', margin: '1px 8px 1px 0', background: active ? 'var(--accent-soft)' : 'transparent', borderLeft: active ? '2px solid var(--accent)' : '2px solid transparent', borderRadius: '0 6px 6px 0', fontSize: 11, color: active ? 'var(--ink)' : 'var(--ink-3)', fontWeight: active ? 500 : 400, cursor: 'pointer', userSelect: 'none' }}
                >
                  <Icon size={12} strokeWidth={1.75} color={active ? 'var(--accent)' : 'var(--ink-4)'} />
                  <span>{label}</span>
                  {id === 'favoris' && favorites.length > 0 && (
                    <span style={{ marginLeft: 'auto', fontSize: 9, fontFamily: 'var(--mono)', color: active ? 'var(--accent)' : 'var(--ink-4)', background: active ? 'transparent' : 'var(--bg-deep)', padding: '1px 5px', borderRadius: 9, border: '1px solid var(--rule-2)' }}>
                      {favorites.length}
                    </span>
                  )}
                  {id === 'archives' && archived.length > 0 && (
                    <span style={{ marginLeft: 'auto', fontSize: 9, fontFamily: 'var(--mono)', color: active ? 'var(--accent)' : 'var(--ink-4)', background: active ? 'transparent' : 'var(--bg-deep)', padding: '1px 5px', borderRadius: 9, border: '1px solid var(--rule-2)' }}>
                      {archived.length}
                    </span>
                  )}
                </div>
              )
            })}
          </div>

          <div style={{ height: 1, background: 'var(--rule)', margin: '6px 0' }} />

          {/* Presets — dépôt rapide dans le dossier courant (RETAKES-3) */}
          {nav.kind === 'inside' && presets.some(p => p.file) && (
            <>
              <div style={{ padding: '2px 12px 0' }}>
                <div className="cap" style={{ marginBottom: 6 }}>PRESETS</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                  {presets.filter(p => p.file).map(p => (
                    <button
                      key={p.id}
                      onClick={() => void dropPresetHere(p)}
                      title={`Déposer "${p.file}" dans le dossier courant`}
                      style={{
                        display: 'flex', alignItems: 'center', gap: 7, width: '100%', textAlign: 'left',
                        padding: '6px 8px', background: 'var(--bg-deep)', border: '1px solid var(--rule-2)',
                        borderRadius: 6, color: 'var(--ink-2)', fontSize: 10, fontFamily: 'var(--sans)',
                        cursor: 'pointer', boxShadow: 'var(--shadow-xs)',
                      }}
                      onMouseEnter={e => { e.currentTarget.style.borderColor = 'var(--accent)'; e.currentTarget.style.color = 'var(--ink)' }}
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
            <div className="cap" style={{ marginBottom: 6 }}>RÉCENTS</div>
            {recentSidebarItems.length === 0 ? (
              <div style={{ fontSize: 10, color: 'var(--ink-4)', fontStyle: 'italic', padding: '3px 0' }}>Aucun</div>
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

          {/* Taille des tuiles de l'explorer */}
          <div style={{ padding: '8px 12px 2px' }}>
            <div className="cap" style={{ marginBottom: 6 }}>TAILLE</div>
            <div style={{ display: 'flex', gap: 4 }}>
              {([
                { id: 'sm' as TileSize, icon: Grid3x3,    title: 'Petites tuiles' },
                { id: 'md' as TileSize, icon: Grid2x2,    title: 'Tuiles moyennes' },
                { id: 'lg' as TileSize, icon: Square,     title: 'Grandes tuiles' },
              ]).map(({ id, icon: Icon, title }) => {
                const active = tileSize === id
                return (
                  <div
                    key={id}
                    title={title}
                    onClick={() => changeTileSize(id)}
                    style={{ flex: 1, height: 26, display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: 5, cursor: 'pointer', background: active ? 'var(--accent-soft)' : 'transparent', border: active ? '1px solid var(--accent)' : '1px solid var(--rule-2)', transition: 'background 0.08s' }}
                  >
                    <Icon size={14} strokeWidth={1.75} color={active ? 'var(--accent)' : 'var(--ink-4)'} />
                  </div>
                )
              })}
            </div>
          </div>

          <div style={{ flex: 1 }} />
          <div style={{ padding: '10px 12px 12px', borderTop: '1px solid var(--rule)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 8 }}>
              <HardDrive size={10} strokeWidth={1.75} color="var(--ink-4)" />
              <div className="cap">WORKSPACE</div>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10 }}>
              <span style={{ color: 'var(--ink-3)' }}>Projets</span>
              <span style={{ fontFamily: 'var(--mono)', color: 'var(--ink-2)', fontSize: 10 }}>{projects.length}</span>
            </div>
          </div>
        </div>

        {/* Zone centrale */}
        <div
          style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, borderRight: '1px solid var(--rule)', overflow: 'hidden' }}
          onClick={() => { if (searchResults === null && sidebarTab === 'tous') setSelectedNames(new Set()) }}
        >

          {/* Listes sauvegardées (Favoris / Récents / Archivés) */}
          {sidebarTab === 'favoris' && (
            <SavedList
              items={favorites} label="FAVORIS" emptyMsg="Aucun favori"
              removeLabel="Retirer des Favoris"
              onNavigate={navigateToSaved}
              onRemove={s => removeFromSaved(s, 'favorites')}
            />
          )}
          {sidebarTab === 'recents' && (
            <SavedList
              items={recents} label="RÉCENTS" emptyMsg="Aucun élément récent"
              removeLabel="Retirer des Récents"
              onNavigate={navigateToSaved}
              onRemove={s => removeFromSaved(s, 'recents')}
            />
          )}
          {sidebarTab === 'archives' && (
            <SavedList
              items={archived} label="ARCHIVÉS" emptyMsg="Aucun élément archivé"
              removeLabel="Désarchiver"
              onNavigate={navigateToSaved}
              onRemove={s => removeFromSaved(s, 'archived')}
              onDeleteProject={s => setDeleteProjectTarget(s)}
            />
          )}

          {/* Vue "Tous" — explorer normal + résultats de recherche */}
          {sidebarTab === 'tous' && (
            <>
              {searchResults !== null ? (
                <>
                  <div style={{ padding: '7px 12px', borderBottom: '1px solid var(--rule)', flexShrink: 0, display: 'flex', alignItems: 'center', gap: 8, background: 'var(--paper-2)' }}>
                    <div style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink-2)', flex: 1 }}>
                      <span style={{ color: 'var(--ink-4)', fontSize: 9 }}>RÉSULTATS · </span>
                      {resultLabel && <span style={{ color: 'var(--ink-2)', fontWeight: 600 }}>{resultLabel} · </span>}
                      {findLoading ? 'Recherche…' : searchResults.length === 0 ? 'Aucun résultat' : `${searchResults.length} trouvé${searchResults.length > 1 ? 's' : ''}`}
                    </div>
                    <div
                      onClick={e => { e.stopPropagation(); setSearchResults(null) }}
                      style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer', color: 'var(--ink-4)', fontSize: 9, fontFamily: 'var(--mono)', padding: '2px 6px', borderRadius: 4, border: '1px solid var(--rule-2)' }}
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
                          <div style={{ fontSize: 9, fontFamily: 'var(--mono)', color: 'var(--ink-4)', marginTop: 1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{r.project} / {r.pathStr}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                </>
              ) : loading ? (
                <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--ink-4)', fontSize: 11, fontStyle: 'italic' }}>
                  Chargement…
                </div>
              ) : items.length === 0 ? (
                <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--ink-4)', fontSize: 11, fontStyle: 'italic' }}>
                  Vide
                </div>
              ) : (
                <div style={{ flex: 1, padding: '10px 12px', overflowY: 'auto', minHeight: 0 }}>
                  {deleteError && (
                    <div style={{ marginBottom: 8, padding: '6px 10px', borderRadius: 5, background: 'rgba(var(--err-rgb),0.1)', border: '1px solid var(--err)', fontSize: 10, fontFamily: 'var(--mono)', color: 'var(--err)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <span>{deleteError}</span>
                      <X size={10} strokeWidth={2} style={{ cursor: 'pointer', flexShrink: 0 }} onClick={() => setDeleteError('')} />
                    </div>
                  )}
                  <div style={{ display: 'grid', gridTemplateColumns: `repeat(auto-fill, minmax(${TILE_SIZES[tileSize].col}px, 1fr))`, gap: `${TILE_SIZES[tileSize].gap}px`, alignContent: 'start' }}>
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
                          onDragStart={e => {
                            const names = selectedNames.has(item.name) && selectedNames.size > 0 ? [...selectedNames] : [item.name]
                            if (!selectedNames.has(item.name)) setSelectedNames(new Set([item.name]))
                            dragNamesRef.current = names
                            e.dataTransfer.effectAllowed = 'move'
                            e.dataTransfer.setData('text/plain', names.join('\n'))
                          }}
                          onDragOver={item.isDir ? (e => { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; if (dragOverName !== item.name) setDragOverName(item.name) }) : undefined}
                          onDragLeave={item.isDir ? (() => setDragOverName(prev => (prev === item.name ? null : prev))) : undefined}
                          onDrop={item.isDir ? (e => {
                            e.preventDefault(); e.stopPropagation(); setDragOverName(null)
                            const names = dragNamesRef.current.filter(n => n !== item.name)
                            void moveNamesTo(names, [...(nav.kind === 'inside' ? nav.subpath : []), item.name])
                          }) : undefined}
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
                              {isSel && <span style={{ color: 'white', fontSize: 8, fontWeight: 700, lineHeight: 1 }}>✓</span>}
                            </div>
                          )}
                          {locked && (
                            <div
                              title="Verrouillé"
                              style={{ position: 'absolute', top: 4, right: 4, width: 15, height: 15, borderRadius: 3, background: 'var(--paper-2)', border: '1px solid var(--accent)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--accent-hi)', zIndex: 1, boxShadow: 'var(--shadow-xs)' }}
                            >
                              <Lock size={9} strokeWidth={2} />
                            </div>
                          )}
                          {(() => {
                            const meta = parseVersionMeta(item.name)
                            return item.isDir
                              ? <FolderSvg size={TILE_SIZES[tileSize].folder} selected={isSel} version={meta.version} format={meta.format} />
                              : <FileSvg   size={TILE_SIZES[tileSize].file} selected={isSel} ext={getExt(item.name)} version={meta.version} />
                          })()}
                          {/* Full name, no truncation: long publish names wrap entirely */}
                          <div title={item.name} style={{ fontSize: TILE_SIZES[tileSize].font, textAlign: 'center', color: isSel ? 'var(--ink)' : 'var(--ink-2)', fontWeight: isSel ? 500 : 400, wordBreak: 'break-all', lineHeight: 1.3, maxWidth: '100%' }}>
                            {item.name}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        {/* Panneau droit */}
        <div style={{ width: 200, display: 'flex', flexDirection: 'column', flexShrink: 0 }}>
          <div style={{ display: 'flex', borderBottom: '1px solid var(--rule)', flexShrink: 0, background: 'var(--paper-2)' }}>
            {TABS.map(t => (
              <div
                key={t.id}
                onClick={() => setTab(t.id)}
                style={{ flex: 1, height: 32, display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: 'var(--mono)', fontSize: 8.5, textTransform: 'uppercase', letterSpacing: '0.08em', color: tab === t.id ? 'var(--accent-hi)' : 'var(--ink-4)', borderBottom: tab === t.id ? '2px solid var(--accent)' : '2px solid transparent', background: tab === t.id ? 'var(--accent-soft)' : 'transparent', cursor: 'pointer' }}
              >
                {t.label}
              </div>
            ))}
          </div>

          <div style={{ flex: 1, padding: '12px', display: 'flex', flexDirection: 'column', overflowY: 'auto', minHeight: 0 }}>
            {tab === 'project' && <TabProject onCreateProject={handleCreateProject} />}
            {tab === 'asset' && <TabAsset currentProject={navProject} onCreateAsset={handleCreateAsset} />}
            {tab === 'shot' && (
              <TabShot
                currentProject={navProject}
                sequences={sequences}
                onCreateSequence={handleCreateSequence}
                onCreateShot={handleCreateShot}
                onRefreshSequences={() => void loadSequences()}
              />
            )}
            {tab === 'directory' && (
              <TabDirectory
                currentProject={navProject}
                currentSubpath={nav.kind === 'inside' ? nav.subpath : []}
                onSuccess={() => { void loadItems(); setTokenRefreshTick(t => t + 1) }}
              />
            )}
          </div>

          {/* Projet actif + Set Project */}
          <div style={{ flexShrink: 0, padding: '10px 12px 12px', borderTop: '1px solid var(--rule)' }}>
            <div className="cap" style={{ marginBottom: 6 }}>PROJET ACTIF</div>
            <div style={{ padding: '6px 8px', borderRadius: 5, border: '1px solid var(--accent)', background: 'var(--accent-soft)', marginBottom: 8 }}>
              <div style={{ fontFamily: 'var(--mono)', fontSize: 10, fontWeight: 600, color: 'var(--accent-hi)' }}>
                {activeProject || '-'}
              </div>
              <div style={{ fontSize: 9, color: 'var(--ink-3)', marginTop: 2 }}>
                {sequences.length > 0 ? `${sequences.length} séquences` : 'Aucune séquence'}
              </div>
            </div>
            {contextProject && contextProject !== activeProject && (
              <div style={{ fontFamily: 'var(--mono)', fontSize: 9, color: 'var(--ink-3)', marginBottom: 4, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                → {contextProject}
              </div>
            )}
            <PanelBtn primary onClick={() => contextProject && handleSetProject(contextProject)} disabled={!contextProject}>
              Set Project
            </PanelBtn>
          </div>
        </div>
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
          onFavorite={() => ctxMenu.items.forEach(toggleFavorite)}
          onArchive={() => ctxMenu.items.forEach(toggleArchived)}
          onToggleLock={nav.kind === 'inside' && ctxMenu.items.length === 1
            ? () => void toggleLock(ctxMenu.items[0])
            : undefined}
          onRename={() => setRenameTarget(ctxMenu.items[0])}
          onMove={() => setMoveTarget(ctxMenu.items)}
          onDelete={() => setDeleteConfirm(ctxMenu.items)}
          onCopyPath={ctxMenu.items.length === 1 ? () => void handleCopyPath(ctxMenu.items[0]) : undefined}
          openInTargets={buildOpenInTargets(ctxMenu.items)}
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

      {deleteProjectTarget && (
        <DeleteProjectModal
          project={deleteProjectTarget.project}
          onConfirm={() => void handleDeleteProject(deleteProjectTarget)}
          onCancel={() => setDeleteProjectTarget(null)}
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
}
