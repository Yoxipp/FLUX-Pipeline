import { useState, useEffect, useCallback, useRef } from 'react'
import { useLocation } from 'react-router-dom'
import {
  ChevronLeft, ChevronRight, Search,
  Star, LayoutGrid, Clock, Archive,
  HardDrive, Plus, Minus, X, Trash2,
} from 'lucide-react'
import { FolderIcon, Select, SelectTrigger, SelectContent, SelectItem } from '../components/shared/ui'
import { api } from '../api/client'
import { useSettings } from '../hooks/useSettings'

// ── Types ─────────────────────────────────────────────────────────────────────

type NavLevel =
  | { kind: 'root' }
  | { kind: 'inside'; project: string; subpath: string[] }

type SidebarTab = 'tous' | 'favoris' | 'recents' | 'archives'

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

interface TokenSel { class: string; type: string; name: string; instance: string; iter: string; mode: FinderMode }

interface CtxMenu { x: number; y: number; items: ExplorerItem[] }

type Tab = 'project' | 'asset' | 'shot' | 'directory'
const TABS: { id: Tab; label: string }[] = [
  { id: 'project',   label: 'Projet' },
  { id: 'asset',     label: 'Asset' },
  { id: 'shot',      label: 'Shot' },
  { id: 'directory', label: 'Dossier' },
]

const ASSET_TOKENS = ['CHAR', 'PROPS', 'ENV', 'CFXRIG', 'FXRIG']
const TOKEN_TYPES  = ['CLASS', 'TYPE', 'NAME', 'INSTANCE', 'SEQ', 'SHOT', 'custom']
const FINDER_ITERS = ['LAST', 'V001', 'V002', 'V003', 'V004', 'V005']

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

function readLS<T>(key: string, fallback: T): T {
  try { return JSON.parse(localStorage.getItem(key) ?? '') as T } catch { return fallback }
}

// ── Icônes SVG ────────────────────────────────────────────────────────────────

function FolderSvg({ size = 40, selected = false }: { size?: number; selected?: boolean }) {
  const body = selected ? 'var(--accent)'    : '#F5A623'
  const tab  = selected ? 'var(--accent-hi)' : '#FFCA5C'
  return (
    <svg width={size} height={Math.round(size * 0.82)} viewBox="0 0 40 33" fill="none">
      <path d="M2 7 L2 4 Q2 2 4 2 L15 2 L18.5 7 Z" fill={tab} />
      <path d="M0 9 Q0 7 2 7 L38 7 Q40 7 40 9 L40 31 Q40 33 38 33 L2 33 Q0 33 0 31 Z" fill={body} />
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

function FileSvg({ size = 36, selected = false, ext = '' }: { size?: number; selected?: boolean; ext?: string }) {
  const body   = selected ? 'var(--accent)'    : 'var(--ink-2)'
  const corner = selected ? 'var(--accent-hi)' : 'var(--ink-3)'
  const badge  = EXT_BADGE[ext]
  return (
    <svg width={size} height={Math.round(size * 1.22)} viewBox="0 0 30 37" fill="none">
      <path d="M2 0 L20 0 L30 10 L30 35 Q30 37 28 37 L2 37 Q0 37 0 35 L0 2 Q0 0 2 0Z" fill={body} />
      <path d="M20 0 L20 10 L30 10Z" fill={corner} />
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

function TokenFinder({ project, tokens, onChange }: {
  project:  string
  tokens:   Record<string, Record<string, string>>
  onChange: (sel: TokenSel) => void
}) {
  const [mode, setMode] = useState<FinderMode>('asset')
  const [sel, setSel]   = useState<TokenSel>({ class: '', type: '', name: '', instance: '', iter: '', mode: 'asset' })
  const [open, setOpen] = useState<number | null>(null)
  const [seqs,  setSeqs]  = useState<string[]>([])
  const [shots, setShots] = useState<string[]>([])
  const rootRef           = useRef<HTMLDivElement>(null)

  // Derive options from tokens.json — no hardcoded arrays
  const assetClasses = Object.keys(tokens.CLASS ?? {}).filter(k => !(tokens.CLASS?.[k] ?? '').includes('{seq}'))
  const shotClasses  = Object.keys(tokens.CLASS ?? {}).filter(k =>  (tokens.CLASS?.[k] ?? '').includes('{seq}'))
  const typeKeys     = Object.keys(tokens.TYPE ?? {})
  const nameKeys     = Object.keys(tokens.NAME ?? {})
  const instanceKeys = ['null', ...Object.keys(tokens.INSTANCE ?? {})]

  // SHOT mode: fetch sequences
  useEffect(() => {
    if (!project || mode !== 'shot') { setSeqs([]); return }
    setSeqs([])
    api.getSequences(project).then(d => setSeqs(d.sequences)).catch(() => setSeqs([]))
  }, [project, mode])

  // SHOT mode: fetch shots for selected SEQ
  useEffect(() => {
    if (!project || mode !== 'shot' || !sel.class) { setShots([]); return }
    setShots([])
    api.getShots(project, sel.class)
      .then(d => setShots(d.shots.map(s => s.split('/')[1] ?? s)))
      .catch(() => setShots([]))
  }, [project, mode, sel.class])

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
    if (key === 'class') { next.type = ''; next.name = '' }
    if (key === 'type')  { next.name = '' }
    setSel(next); onChange(next); setOpen(null)
  }
  const clear = (key: keyof TokenSel) => {
    const next: TokenSel = { ...sel, [key]: '', mode }
    if (key === 'class') { next.type = ''; next.name = '' }
    if (key === 'type')  { next.name = '' }
    setSel(next); onChange(next); setOpen(null)
  }

  const switchMode = () => {
    const newMode: FinderMode = mode === 'asset' ? 'shot' : 'asset'
    const reset: TokenSel = { class: '', type: '', name: '', instance: '', iter: '', mode: newMode }
    setMode(newMode); setSel(reset); onChange(reset); setOpen(null)
  }

  const MODULES: { key: keyof TokenSel; label: string; opts: string[] }[] = mode === 'asset'
    ? [
        { key: 'class',    label: 'CLASS',    opts: assetClasses },
        { key: 'type',     label: 'TYPE',     opts: typeKeys },
        { key: 'name',     label: 'NAME',     opts: nameKeys },
        { key: 'instance', label: 'INSTANCE', opts: instanceKeys },
        { key: 'iter',     label: 'ITER',     opts: FINDER_ITERS },
      ]
    : [
        { key: 'class',    label: 'SEQ',      opts: seqs },
        { key: 'type',     label: 'SHOT',     opts: shots },
        { key: 'name',     label: 'NAME',     opts: shotClasses },
        { key: 'instance', label: 'INSTANCE', opts: instanceKeys },
        { key: 'iter',     label: 'ITER',     opts: FINDER_ITERS },
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
                {value || '—'}
              </span>
            </div>
            {isOpen && (
              <div style={{ position: 'absolute', top: 'calc(100% + 3px)', left: 0, zIndex: 500, minWidth: 110, background: 'var(--paper)', border: '1px solid var(--rule-2)', borderRadius: 5, boxShadow: 'var(--shadow)', overflow: 'hidden' }}>
                {value && (
                  <div onClick={() => clear(key)} style={{ padding: '5px 8px', fontSize: 9, fontFamily: 'var(--mono)', color: 'var(--ink-4)', borderBottom: '1px solid var(--rule)', cursor: 'pointer' }}>
                    — effacer
                  </div>
                )}
                {opts.length === 0 ? (
                  <div style={{ padding: '6px 8px', fontSize: 9, color: 'var(--ink-4)', fontStyle: 'italic' }}>
                    {project ? (key === 'type' && mode === 'asset' && sel.class ? 'Pas de type' : 'Vide') : 'Projet requis'}
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
        style={{ flex: 1, textAlign: 'center', fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink)', background: 'transparent', border: 'none', outline: 'none', minWidth: 0 }}
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
          ? <SelectItem value="__empty__">—</SelectItem>
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
      style={{ width: '100%', height: 28, border: '1px solid var(--rule-2)', borderRadius: 5, background: 'var(--bg-deep)', color: 'var(--ink)', fontFamily: 'var(--mono)', fontSize: 10, padding: '0 8px', boxShadow: 'var(--shadow-inset)', outline: 'none' }}
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
          <SelectEl options={sequences.length > 0 ? sequences : ['—']} value={seq} onChange={setSeq} />
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
          style={{ width: '100%', height: 32, border: '1px solid var(--rule-2)', borderRadius: 5, background: 'var(--bg-deep)', color: 'var(--ink)', fontFamily: 'var(--mono)', fontSize: 11, padding: '0 10px', outline: 'none', boxSizing: 'border-box' }}
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

function ContextMenu({ x, y, isFavorited, isArchived, canEdit, canDelete, count, onFavorite, onArchive, onRename, onMove, onDelete, onOpenInHoudini, onOpenInMaya, onClose }: {
  x: number; y: number
  isFavorited: boolean
  isArchived: boolean
  canEdit: boolean
  canDelete: boolean
  count: number
  onFavorite:       () => void
  onArchive:        () => void
  onRename:         () => void
  onMove:           () => void
  onDelete:         () => void
  onOpenInHoudini?: () => void
  onOpenInMaya?:    () => void
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
      {canEdit && (
        <>
          <div style={{ height: 1, background: 'var(--rule)', margin: '4px 0' }} />
          {count === 1 && row('Renommer', false, () => { onRename(); onClose() })}
          {row(count > 1 ? `Déplacer (${count})` : 'Déplacer', false, () => { onMove(); onClose() })}
        </>
      )}
      {(onOpenInHoudini || onOpenInMaya) && (
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
                {onOpenInHoudini && (
                  <div
                    onClick={() => { onOpenInHoudini(); onClose() }}
                    style={{
                      padding: '6px 12px', fontSize: 11, cursor: 'pointer',
                      color: 'var(--ink-2)', display: 'flex', alignItems: 'center', gap: 7,
                      transition: 'background 0.06s',
                    }}
                    onMouseEnter={e => { e.currentTarget.style.background = 'var(--accent-soft)' }}
                    onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
                  >
                    Houdini
                  </div>
                )}
                {onOpenInMaya && (
                  <div
                    onClick={() => { onOpenInMaya(); onClose() }}
                    style={{
                      padding: '6px 12px', fontSize: 11, cursor: 'pointer',
                      color: 'var(--ink-2)', display: 'flex', alignItems: 'center', gap: 7,
                      transition: 'background 0.06s',
                    }}
                    onMouseEnter={e => { e.currentTarget.style.background = 'var(--accent-soft)' }}
                    onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
                  >
                    Maya
                  </div>
                )}
              </div>
            )}
          </div>
        </>
      )}
      {canDelete && (
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

// ── Saved Items List (Favoris / Récents / Archivés) ───────────────────────────

function SavedList({ items, label, emptyMsg, removeLabel, onNavigate, onRemove }: {
  items:       SavedItem[]
  label:       string
  emptyMsg:    string
  removeLabel: string   // ex: "Désarchiver", "Retirer des Favoris", "Retirer"
  onNavigate:  (s: SavedItem) => void
  onRemove:    (s: SavedItem) => void
}) {
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
          {label} — {items.length === 0 ? emptyMsg : `${items.length} élément${items.length > 1 ? 's' : ''}`}
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
                <div style={{ fontSize: 11, fontWeight: 500, color: 'var(--ink)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{s.label}</div>
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

  const [projects, setProjects]           = useState<string[]>([])
  const [activeProject, setActiveProject] = useState('')
  const [sequences, setSequences]         = useState<string[]>([])

  const { settings } = useSettings()
  const location = useLocation()
  useEffect(() => {
    if (settings?.last_project) setActiveProject(settings.last_project)
  }, [settings?.last_project])

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

  // Saved lists (localStorage)
  const [favorites, setFavorites] = useState<SavedItem[]>(() => readLS<SavedItem[]>('flux_favorites', []))
  const [archived,  setArchived]  = useState<SavedItem[]>(() => readLS<SavedItem[]>('flux_archived',  []))
  const [recents,   setRecents]   = useState<SavedItem[]>(() => readLS<SavedItem[]>('flux_recents',   []))

  // Context menu & delete confirm
  const [ctxMenu,        setCtxMenu]        = useState<CtxMenu | null>(null)
  const [deleteConfirm,  setDeleteConfirm]  = useState<ExplorerItem[] | null>(null)
  const [deleteError,    setDeleteError]    = useState('')
  const [renameTarget,   setRenameTarget]   = useState<ExplorerItem | null>(null)
  const [moveTarget,     setMoveTarget]     = useState<ExplorerItem[] | null>(null)

  // Token Finder & Search
  const [tokenSel, setTokenSel]           = useState<TokenSel>({ class: '', type: '', name: '', instance: '', iter: '', mode: 'asset' })
  const [projectTokens, setProjectTokens] = useState<Record<string, Record<string, string>>>({})
  const [tokenRefreshTick, setTokenRefreshTick] = useState(0)
  const [searchQuery, setSearchQuery]     = useState('')
  const [searchResults, setSearchResults] = useState<FindResult[] | null>(null)
  const [findLoading, setFindLoading]     = useState(false)
  const [resultLabel, setResultLabel]     = useState('')

  const lastClickedRef = useRef<string | null>(null)

  // ── Persist saved lists ────────────────────────────────────────────────────

  useEffect(() => { localStorage.setItem('flux_favorites', JSON.stringify(favorites)) }, [favorites])
  useEffect(() => { localStorage.setItem('flux_archived',  JSON.stringify(archived))  }, [archived])
  useEffect(() => { localStorage.setItem('flux_recents',   JSON.stringify(recents))   }, [recents])

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

  // ── Delete key on selected item ────────────────────────────────────────────

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === 'Delete' && selectedNames.size > 0 && !deleteConfirm && nav.kind === 'inside') {
        const targets = items.filter(it => selectedNames.has(it.name))
        if (targets.length > 0) setDeleteConfirm(targets)
      }
    }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [selectedNames, items, deleteConfirm, nav])

  // ── Dérivés ────────────────────────────────────────────────────────────────

  const breadcrumb: string[] = nav.kind === 'root'
    ? ['PROJETS']
    : ['PROJETS', nav.project, ...nav.subpath]

  const navProject: string = nav.kind === 'inside' ? nav.project : ''
  const contextProject: string | null =
    navProject !== '' ? navProject
    : (selectedNames.size === 1 && projects.includes([...selectedNames][0])) ? [...selectedNames][0]
    : null

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
        setProjects(d.projects)
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

      let seqList: string[]
      if (tokenSel.class) {
        seqList = [tokenSel.class]
      } else {
        try { seqList = (await api.getSequences(proj)).sequences } catch { seqList = [] }
      }

      for (const seq of seqList) {
        let shotList: string[]
        if (tokenSel.type) {
          shotList = [tokenSel.type]
        } else {
          try {
            const d = await api.getShots(proj, seq)
            shotList = d.shots.map(s => s.split('/')[1] ?? s)
          } catch { shotList = [] }
        }
        for (const shot of shotList) {
          const base = ['shot', seq, shot]
          if (tokenSel.name) {
            // Resolve via CLASS token template (e.g. "shot/{seq}/{shot}/anim")
            const template = classTokens[tokenSel.name]
            if (template) {
              const resolved = template.replace('{seq}', seq).replace('{shot}', shot)
              const subpath = resolved.split('/')
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
      // Asset classes = CLASS tokens whose path doesn't contain {seq}
      const assetClassKeys = Object.keys(classTokens).filter(k => !classTokens[k].includes('{seq}'))
      const classes = tokenSel.class ? [tokenSel.class] : assetClassKeys
      const nameLow = tokenSel.name.toLowerCase()

      for (const cls of classes) {
        const classRelPath = classTokens[cls]
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
          if (tokenSel.type) {
            // Look up subfolder from TYPE tokens in tokens.json
            const subfolder = typeTokens[tokenSel.type]
            if (subfolder) {
              const fullPath = [...assetPath, ...subfolder.split('/')]
              results.push({ label: `${folder.name} / ${tokenSel.type}`, pathStr: fullPath.join(' / '), project: proj, subpath: fullPath, isDir: true })
            } else {
              // Unknown type — fall back to text match one level down
              try {
                const d2 = await api.browseProject(proj, assetPath.join('/'))
                const typeLow = tokenSel.type.toLowerCase()
                for (const sub of d2.folders) {
                  if (sub.name.toLowerCase().includes(typeLow)) {
                    const subPath = [...assetPath, sub.name]
                    results.push({ label: `${folder.name} / ${sub.name}`, pathStr: subPath.join(' / '), project: proj, subpath: subPath, isDir: true })
                  }
                }
              } catch {}
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
    const oldKey = currentItemKey(item, nav)
    setFavorites(prev => prev.map(s => savedKey(s) === oldKey ? { ...s, label: newName } : s))
    setRecents(prev   => prev.map(s => savedKey(s) === oldKey ? { ...s, label: newName } : s))
    setRenameTarget(null)
    await loadItems()
  }, [nav, loadItems])

  const handleOpenInHoudini = useCallback(async (item: ExplorerItem) => {
    if (nav.kind !== 'inside') return
    const rel_path = [...nav.subpath, item.name].join('/')
    const tok = await api.getFluxTokensFromPath(nav.project, rel_path)
    await api.createFluxImporterNode({
      project:       nav.project,
      flux_class:    tok.CLASS,
      flux_type:     tok.TYPE,
      flux_name:     tok.NAME,
      flux_instance: tok.INSTANCE,
      flux_iter:     'LAST',
    })
  }, [nav])

  const MAYA_IMPORT_EXTS = new Set(['.obj', '.fbx', '.ma', '.mb', '.abc'])

  const handleOpenInMaya = useCallback(async (item: ExplorerItem) => {
    if (nav.kind !== 'inside') return
    const rel_path = [...nav.subpath, item.name].join('/')
    await api.importFileInMaya(nav.project, rel_path)
  }, [nav])

  const handleMove = useCallback(async (targets: ExplorerItem[], newSubpath: string[]) => {
    if (nav.kind !== 'inside') return
    for (const item of targets) {
      await api.patchItem(nav.project, nav.subpath, item.name, undefined, newSubpath)
      const k = currentItemKey(item, nav)
      setFavorites(prev => prev.filter(s => savedKey(s) !== k))
      setRecents(prev   => prev.filter(s => savedKey(s) !== k))
    }
    setMoveTarget(null)
    setSelectedNames(new Set())
    await loadItems()
  }, [nav, loadItems])

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

  const recentSidebarItems = recents.slice(0, 5)

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>

      {/* En-tête */}
      <div style={{ padding: '12px 20px', borderBottom: '1px solid var(--rule)', flexShrink: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.1em', color: 'var(--ink)' }}>Projets</div>
      </div>

      {/* Barre de navigation */}
      <div style={{ padding: '6px 10px 7px', borderBottom: '1px solid var(--rule)', background: 'var(--paper-2)', flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 5 }}>

        {/* Ligne 1 : back/fwd + breadcrumb + search */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {[
            { Icon: ChevronLeft,  action: goBack,    ok: canBack },
            { Icon: ChevronRight, action: goForward, ok: canForward },
          ].map(({ Icon, action, ok }, i) => (
            <div
              key={i}
              onClick={ok ? action : undefined}
              style={{ width: 24, height: 24, border: '1px solid var(--rule-2)', borderRadius: 5, display: 'flex', alignItems: 'center', justifyContent: 'center', color: ok ? 'var(--ink-2)' : 'var(--ink-4)', boxShadow: 'var(--shadow-xs)', cursor: ok ? 'pointer' : 'default', opacity: ok ? 1 : 0.4, flexShrink: 0 }}
            >
              <Icon size={13} strokeWidth={2} />
            </div>
          ))}

          {/* Breadcrumb */}
          <div style={{ flex: 1, minWidth: 0, display: 'flex', alignItems: 'center', gap: 2, fontFamily: 'var(--mono)', fontSize: 10, height: 24, border: '1px solid var(--rule)', padding: '0 8px', background: 'var(--bg-deep)', borderRadius: 5, boxShadow: 'var(--shadow-inset)', overflow: 'hidden' }}>
            {breadcrumb.map((seg, i) => {
              const isLast = i === breadcrumb.length - 1
              return (
                <span key={i} style={{ display: 'flex', alignItems: 'center', gap: 2, flexShrink: isLast ? 0 : 1, minWidth: isLast ? 'auto' : 0 }}>
                  {i > 0 && <ChevronRight size={9} strokeWidth={1.5} color="var(--ink-4)" style={{ flexShrink: 0 }} />}
                  <span
                    onClick={!isLast ? () => navigateToBreadcrumb(i) : undefined}
                    style={{ color: isLast ? 'var(--ink)' : 'var(--ink-3)', fontWeight: isLast ? 600 : 400, cursor: !isLast ? 'pointer' : 'default', whiteSpace: 'nowrap', overflow: isLast ? 'visible' : 'hidden', textOverflow: 'ellipsis', flexShrink: isLast ? 0 : 1 }}
                  >
                    {seg}
                  </span>
                </span>
              )
            })}
          </div>

          {/* Search */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 5, border: '1px solid var(--rule-2)', padding: '0 6px', height: 24, width: 150, background: 'var(--bg-deep)', borderRadius: 5, boxShadow: 'var(--shadow-inset)', flexShrink: 0 }}>
            <Search size={10} strokeWidth={2} color="var(--ink-4)" style={{ flexShrink: 0 }} />
            <input
              value={searchQuery}
              onChange={e => { setSearchQuery(e.target.value); if (!e.target.value) setSearchResults(null) }}
              onKeyDown={e => { if (e.key === 'Enter') void handleSearch(searchQuery) }}
              placeholder="Rechercher…"
              style={{ flex: 1, background: 'transparent', border: 'none', outline: 'none', fontSize: 10, color: 'var(--ink)', fontFamily: 'var(--mono)' }}
            />
            {searchQuery && (
              <X size={9} strokeWidth={2} color="var(--ink-4)" style={{ flexShrink: 0, cursor: 'pointer' }}
                onClick={() => { setSearchQuery(''); setSearchResults(null) }}
              />
            )}
          </div>
        </div>

        {/* Ligne 2 : Token Finder + Find */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <TokenFinder project={navProject || activeProject} tokens={projectTokens} onChange={setTokenSel} />
          <div
            onClick={() => void handleFind()}
            className="btn primary"
            style={{ height: 30, padding: '0 14px', flexShrink: 0, display: 'flex', alignItems: 'center', fontSize: 10, cursor: findLoading ? 'wait' : 'pointer' }}
          >
            {findLoading ? '…' : 'Find'}
          </div>
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
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.label}</span>
              </div>
            ))}
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
            />
          )}

          {/* Vue "Tous" — explorer normal + résultats de recherche */}
          {sidebarTab === 'tous' && (
            <>
              {searchResults !== null ? (
                <>
                  <div style={{ padding: '7px 12px', borderBottom: '1px solid var(--rule)', flexShrink: 0, display: 'flex', alignItems: 'center', gap: 8, background: 'var(--paper-2)' }}>
                    <div style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink-2)', flex: 1 }}>
                      <span style={{ color: 'var(--ink-4)', fontSize: 9 }}>RÉSULTATS — </span>
                      {resultLabel && <span style={{ color: 'var(--ink-2)', fontWeight: 600 }}>{resultLabel} — </span>}
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
                          <div style={{ fontSize: 11, fontWeight: 500, color: 'var(--ink)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{r.label}</div>
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
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(80px, 1fr))', gap: '4px', alignContent: 'start' }}>
                    {items.filter(item => !isItemArchived(item)).map((item, i) => {
                      const isSel     = selectedNames.has(item.name)
                      const isHovered = hoveredName === item.name
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
                          style={{ position: 'relative', display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '8px 4px 6px', borderRadius: 6, background: isSel ? 'var(--accent-soft)' : 'transparent', border: isSel ? '1px solid var(--accent)' : '1px solid transparent', gap: 5, cursor: 'default', userSelect: 'none', transition: 'background 0.08s' }}
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
                          {item.isDir
                            ? <FolderSvg size={40} selected={isSel} />
                            : <FileSvg   size={34} selected={isSel} ext={getExt(item.name)} />}
                          <div style={{ fontSize: 10, textAlign: 'center', color: isSel ? 'var(--ink)' : 'var(--ink-2)', fontWeight: isSel ? 500 : 400, wordBreak: 'break-all', lineHeight: 1.3, maxWidth: '100%', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' as const, overflow: 'hidden' }}>
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
                {activeProject || '—'}
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
          canEdit={nav.kind === 'inside'}
          canDelete={nav.kind === 'inside'}
          count={ctxMenu.items.length}
          onFavorite={() => ctxMenu.items.forEach(toggleFavorite)}
          onArchive={() => ctxMenu.items.forEach(toggleArchived)}
          onRename={() => setRenameTarget(ctxMenu.items[0])}
          onMove={() => setMoveTarget(ctxMenu.items)}
          onDelete={() => setDeleteConfirm(ctxMenu.items)}
          onOpenInHoudini={nav.kind === 'inside' && ctxMenu.items.length === 1
            ? () => void handleOpenInHoudini(ctxMenu.items[0])
            : undefined}
          onOpenInMaya={
            nav.kind === 'inside' &&
            ctxMenu.items.length === 1 &&
            !ctxMenu.items[0].isDir &&
            MAYA_IMPORT_EXTS.has('.' + (ctxMenu.items[0].name.split('.').pop() ?? '').toLowerCase())
              ? () => void handleOpenInMaya(ctxMenu.items[0])
              : undefined
          }
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
}
