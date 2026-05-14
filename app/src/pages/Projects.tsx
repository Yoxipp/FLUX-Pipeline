import { useState, useEffect, useCallback, useRef } from 'react'
import {
  ChevronLeft, ChevronRight, Search,
  Star, LayoutGrid, Clock, Archive,
  HardDrive, Plus, Minus, ChevronDown, X,
} from 'lucide-react'
import { FolderIcon } from '../components/shared/ui'
import { api } from '../api/client'

// ── Types ─────────────────────────────────────────────────────────────────────

type NavLevel =
  | { kind: 'root' }
  | { kind: 'inside'; project: string; subpath: string[] }

interface ExplorerItem { name: string; isDir: boolean }

interface FindResult {
  label:   string
  pathStr: string      // chemin lisible pour l'affichage
  project: string
  subpath: string[]
  isDir:   boolean
}

interface TokenSel { class: string; type: string; name: string; instance: string; iter: string }

type Tab = 'project' | 'asset' | 'shot' | 'directory'
const TABS: { id: Tab; label: string }[] = [
  { id: 'project',   label: 'Projet' },
  { id: 'asset',     label: 'Asset' },
  { id: 'shot',      label: 'Shot' },
  { id: 'directory', label: 'Dossier' },
]

const ASSET_TOKENS   = ['CHAR', 'PROPS', 'ENV', 'CFXRIG', 'FXRIG']
const TOKEN_TYPES    = ['CLASS', 'TYPE', 'NAME', 'SEQ', 'SHOT', 'custom']
const FINDER_CLASSES = ['CHAR', 'PROPS', 'ENV', 'CFXRIG', 'FXRIG']
const FINDER_TYPES   = ['SCULPT', 'BLOCK', 'TOPO', 'RIG', 'TEX', 'LDEV', 'FUR', 'HAIR', 'FEATHERS', 'SK', 'WGHT']
const FINDER_ITERS   = ['LAST', 'V001', 'V002', 'V003', 'V004', 'V005']

// Mapping token CLASS → sous-dossier dans le projet
const CLASS_TO_PATH: Record<string, string[]> = {
  CHAR:   ['assets', 'chara'],
  PROPS:  ['assets', 'props'],
  ENV:    ['assets', 'enviros'],
  CFXRIG: ['assets', 'cfx_rig'],
  FXRIG:  ['assets', 'fx_rig'],
}

const SIDEBAR_ITEMS = [
  { ic: Star,       label: 'Favoris' },
  { ic: LayoutGrid, label: 'Tous', active: true },
  { ic: Clock,      label: 'Récents' },
  { ic: Archive,    label: 'Archivés' },
]

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

function FileSvg({ size = 36, selected = false }: { size?: number; selected?: boolean }) {
  const body   = selected ? 'var(--accent)'    : 'var(--ink-3)'
  const corner = selected ? 'var(--accent-hi)' : 'var(--ink-4)'
  return (
    <svg width={size} height={Math.round(size * 1.22)} viewBox="0 0 30 37" fill="none">
      <path d="M2 0 L20 0 L30 10 L30 35 Q30 37 28 37 L2 37 Q0 37 0 35 L0 2 Q0 0 2 0Z" fill={body} />
      <path d="M20 0 L20 10 L30 10Z" fill={corner} />
    </svg>
  )
}

// ── Token Finder ──────────────────────────────────────────────────────────────

function TokenFinder({ project, onChange }: {
  project:  string
  onChange: (sel: TokenSel) => void
}) {
  const [sel, setSel]     = useState<TokenSel>({ class: '', type: '', name: '', instance: '', iter: '' })
  const [open, setOpen]   = useState<number | null>(null)
  const [names, setNames] = useState<string[]>([])
  const rootRef           = useRef<HTMLDivElement>(null)

  // NAME = project-only, toutes les classes en parallèle
  useEffect(() => {
    if (!project) { setNames([]); return }
    Promise.all(
      FINDER_CLASSES.map(cls =>
        api.getAssets(project, cls).then(d => d.assets).catch(() => [] as string[])
      )
    ).then(arrays => setNames([...new Set(arrays.flat())]))
  }, [project])

  // Fermer dropdown sur clic extérieur
  useEffect(() => {
    if (open === null) return
    const h = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(null)
    }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [open])

  const update = (key: keyof TokenSel, value: string) => {
    const next = { ...sel, [key]: value }
    setSel(next)
    onChange(next)
    setOpen(null)
  }

  const clear = (key: keyof TokenSel) => {
    const next = { ...sel, [key]: '' }
    setSel(next)
    onChange(next)
    setOpen(null)
  }

  const MODULES: { key: keyof TokenSel; label: string; opts: string[] }[] = [
    { key: 'class',    label: 'CLASS',    opts: FINDER_CLASSES },
    { key: 'type',     label: 'TYPE',     opts: FINDER_TYPES },
    { key: 'name',     label: 'NAME',     opts: names },
    { key: 'instance', label: 'INSTANCE', opts: ['null'] },
    { key: 'iter',     label: 'ITER',     opts: FINDER_ITERS },
  ]

  return (
    <div
      ref={rootRef}
      style={{ flex: 1, display: 'flex', border: '1px solid var(--rule-2)', borderRadius: 5, background: 'var(--bg-deep)', boxShadow: 'var(--shadow-inset)', position: 'relative', overflow: 'visible' }}
    >
      {MODULES.map(({ key, label, opts }, i) => {
        const value  = sel[key]
        const isOpen = open === i
        return (
          <div
            key={i}
            style={{ flex: 1, position: 'relative', borderLeft: i > 0 ? '1px solid var(--rule-2)' : 'none' }}
          >
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
                  <div
                    onClick={() => clear(key)}
                    style={{ padding: '5px 8px', fontSize: 9, fontFamily: 'var(--mono)', color: 'var(--ink-4)', borderBottom: '1px solid var(--rule)', cursor: 'pointer' }}
                  >
                    — effacer
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
  )
}

// ── Sous-composants partagés ──────────────────────────────────────────────────

function Spinner({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', height: 28, border: '1px solid var(--rule-2)', borderRadius: 5, overflow: 'hidden', background: 'var(--bg-deep)', boxShadow: 'var(--shadow-inset)' }}>
      <div onClick={() => onChange(Math.max(0, value - 1))} style={{ width: 26, height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', borderRight: '1px solid var(--rule-2)', cursor: 'pointer', color: 'var(--ink-3)', flexShrink: 0 }}>
        <Minus size={10} strokeWidth={2} />
      </div>
      <div style={{ flex: 1, textAlign: 'center', fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink)' }}>
        {String(value).padStart(3, '0')}
      </div>
      <div onClick={() => onChange(value + 1)} style={{ width: 26, height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', borderLeft: '1px solid var(--rule-2)', cursor: 'pointer', color: 'var(--ink-3)', flexShrink: 0 }}>
        <Plus size={10} strokeWidth={2} />
      </div>
    </div>
  )
}

function SelectEl({ options, value, onChange }: { options: string[]; value: string; onChange: (v: string) => void }) {
  return (
    <div style={{ position: 'relative', height: 28 }}>
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        style={{ width: '100%', height: '100%', border: '1px solid var(--rule-2)', borderRadius: 5, background: 'var(--bg-deep)', color: 'var(--ink)', fontFamily: 'var(--mono)', fontSize: 10, padding: '0 24px 0 8px', appearance: 'none', cursor: 'pointer', boxShadow: 'var(--shadow-inset)', outline: 'none' }}
      >
        {options.length === 0
          ? <option value="">—</option>
          : options.map(o => <option key={o} value={o}>{o}</option>)}
      </select>
      <ChevronDown size={10} strokeWidth={2} color="var(--ink-3)" style={{ position: 'absolute', right: 7, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }} />
    </div>
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

function PanelBtn({ primary, children, onClick, disabled }: { primary?: boolean; children: React.ReactNode; onClick?: () => void; disabled?: boolean }) {
  return (
    <div
      className={`btn${primary ? ' primary' : ' ghost'}`}
      onClick={disabled ? undefined : onClick}
      style={{ width: '100%', justifyContent: 'center', opacity: disabled ? 0.5 : 1, cursor: disabled ? 'default' : 'pointer' }}
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
  const [seqN, setSeqN]         = useState(10)
  const [shotN, setShotN]       = useState(10)
  const [seq, setSeq]           = useState('')
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
    const seqNum = parseInt(seq.replace(/^SQ0*/, ''), 10) || seqN
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

function TabDirectory({ currentProject }: { currentProject: string }) {
  const [name, setName]           = useState('')
  const [token, setToken]         = useState('')
  const [tokenType, setTokenType] = useState('CLASS')
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, flex: 1 }}>
      <NavContext project={currentProject} />
      <div>
        <div className="cap" style={{ marginBottom: 4 }}>NAME</div>
        <InputField value={name} onChange={setName} placeholder="ex: NEW_FOLDER" />
      </div>
      <div>
        <div className="cap" style={{ marginBottom: 4 }}>TOKEN</div>
        <InputField value={token} onChange={setToken} placeholder="ex: SLA" />
      </div>
      <div>
        <div className="cap" style={{ marginBottom: 4 }}>TOKEN TYPE</div>
        <SelectEl options={TOKEN_TYPES} value={tokenType} onChange={setTokenType} />
      </div>
      <div style={{ flex: 1 }} />
      <PanelBtn primary disabled={!name.trim() || !currentProject}>Add Folder</PanelBtn>
    </div>
  )
}

// ── Composant principal ───────────────────────────────────────────────────────

export function Projects() {
  const [navStack, setNavStack] = useState<NavLevel[]>([{ kind: 'root' }])
  const [navIdx, setNavIdx]     = useState(0)
  const nav = navStack[navIdx]

  const [items, setItems]               = useState<ExplorerItem[]>([])
  const [selectedName, setSelectedName] = useState<string | null>(null)
  const [loading, setLoading]           = useState(false)

  const [projects, setProjects]           = useState<string[]>([])
  const [activeProject, setActiveProject] = useState('')
  const [sequences, setSequences]         = useState<string[]>([])

  const [tab, setTab] = useState<Tab>('project')

  // Token Finder & Search
  const [tokenSel, setTokenSel]           = useState<TokenSel>({ class: '', type: '', name: '', instance: '', iter: '' })
  const [searchQuery, setSearchQuery]     = useState('')
  const [searchResults, setSearchResults] = useState<FindResult[] | null>(null)
  const [findLoading, setFindLoading]     = useState(false)
  const [resultLabel, setResultLabel]     = useState('')

  // ── Dérivés ────────────────────────────────────────────────────────────────

  const breadcrumb: string[] = nav.kind === 'root'
    ? ['PROJETS']
    : ['PROJETS', nav.project, ...nav.subpath]

  const navProject: string = nav.kind === 'inside' ? nav.project : ''
  const contextProject: string | null =
    navProject !== '' ? navProject
    : (selectedName !== null && projects.includes(selectedName)) ? selectedName
    : null

  const canBack    = navIdx > 0
  const canForward = navIdx < navStack.length - 1

  // ── Navigation ─────────────────────────────────────────────────────────────

  const navigateTo = useCallback((level: NavLevel) => {
    setNavStack(prev => [...prev.slice(0, navIdx + 1), level])
    setNavIdx(i => i + 1)
    setSelectedName(null)
    setSearchResults(null)
    setSearchQuery('')
  }, [navIdx])

  const goBack = useCallback(() => {
    if (navIdx > 0) { setNavIdx(i => i - 1); setSelectedName(null); setSearchResults(null); setSearchQuery('') }
  }, [navIdx])

  const goForward = useCallback(() => {
    if (navIdx < navStack.length - 1) { setNavIdx(i => i + 1); setSelectedName(null); setSearchResults(null); setSearchQuery('') }
  }, [navIdx, navStack.length])

  const navigateToBreadcrumb = useCallback((segIdx: number) => {
    if (segIdx === 0) navigateTo({ kind: 'root' })
    else if (nav.kind === 'inside')
      navigateTo({ kind: 'inside', project: nav.project, subpath: nav.subpath.slice(0, segIdx - 1) })
  }, [nav, navigateTo])

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

  // ── Find logic ─────────────────────────────────────────────────────────────

  const handleFind = useCallback(async () => {
    const proj = navProject || activeProject
    if (!proj) return

    setFindLoading(true)
    setSearchResults([])
    setResultLabel('Finder')

    const results: FindResult[] = []
    const classes = tokenSel.class ? [tokenSel.class] : FINDER_CLASSES
    const nameLow = tokenSel.name.toLowerCase()
    const typeLow = tokenSel.type.toLowerCase()

    for (const cls of classes) {
      const basePath = CLASS_TO_PATH[cls]
      if (!basePath) continue

      let folders: { name: string }[] = []
      try {
        const d = await api.browseProject(proj, basePath.join('/'))
        folders = d.folders
      } catch { continue }

      // Filtrer par NAME (match partiel insensible à la casse)
      const matching = nameLow
        ? folders.filter(f => f.name.toLowerCase().includes(nameLow))
        : folders

      for (const folder of matching) {
        const folderPath = [...basePath, folder.name]

        if (typeLow) {
          // Chercher le dossier de type à l'intérieur
          let found = false
          try {
            const d2 = await api.browseProject(proj, folderPath.join('/'))
            for (const sub of d2.folders) {
              if (sub.name.toLowerCase().includes(typeLow)) {
                results.push({
                  label:   `${folder.name} / ${sub.name}`,
                  pathStr: [...folderPath, sub.name].join(' / '),
                  project: proj,
                  subpath: [...folderPath, sub.name],
                  isDir:   true,
                })
                found = true
              }
            }
          } catch {}
          if (!found) {
            results.push({ label: folder.name, pathStr: folderPath.join(' / '), project: proj, subpath: folderPath, isDir: true })
          }
        } else {
          results.push({ label: folder.name, pathStr: folderPath.join(' / '), project: proj, subpath: folderPath, isDir: true })
        }
      }
    }

    setSearchResults(results)
    setFindLoading(false)
  }, [tokenSel, navProject, activeProject])

  // Recherche textuelle — browse les chemins clés du projet et filtre par nom
  const handleSearch = useCallback(async (query: string) => {
    if (!query.trim()) { setSearchResults(null); return }
    const proj = navProject || activeProject
    if (!proj) return

    setFindLoading(true)
    setSearchResults([])
    setResultLabel(`«${query}»`)

    const results: FindResult[] = []
    const q = query.toLowerCase()

    // Chemins à parcourir (root + dossiers de premier niveau + chaque classe)
    const pathsToSearch: string[][] = [
      [],
      ['assets'], ['shot'], ['comp'], ['lighting'],
      ...Object.values(CLASS_TO_PATH),
    ]

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

    // Tri : exact > starts-with > contains
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
    if (nav.kind === 'root') navigateTo({ kind: 'inside', project: item.name, subpath: [] })
    else navigateTo({ kind: 'inside', project: nav.project, subpath: [...nav.subpath, item.name] })
  }, [nav, navigateTo])

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

  const recentProjects = projects.slice(0, 3)

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>

      {/* En-tête */}
      <div style={{ padding: '12px 20px', borderBottom: '1px solid var(--rule)', flexShrink: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.1em', color: 'var(--ink)' }}>Projets</div>
      </div>

      {/* Barre de navigation — 2 lignes */}
      <div style={{ padding: '6px 10px 7px', borderBottom: '1px solid var(--rule)', background: 'var(--paper-2)', flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 5 }}>

        {/* Ligne 1 : back/fwd + breadcrumb (tronqué) + search */}
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

          {/* Breadcrumb tronqué */}
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
              onChange={e => {
                setSearchQuery(e.target.value)
                if (!e.target.value) setSearchResults(null)
              }}
              onKeyDown={e => { if (e.key === 'Enter') void handleSearch(searchQuery) }}
              placeholder="Rechercher…"
              style={{ flex: 1, background: 'transparent', border: 'none', outline: 'none', fontSize: 10, color: 'var(--ink)', fontFamily: 'var(--mono)' }}
            />
            {searchQuery && (
              <X
                size={9}
                strokeWidth={2}
                color="var(--ink-4)"
                style={{ flexShrink: 0, cursor: 'pointer' }}
                onClick={() => { setSearchQuery(''); setSearchResults(null) }}
              />
            )}
          </div>
        </div>

        {/* Ligne 2 : Token Finder + bouton Find */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <TokenFinder project={navProject || activeProject} onChange={setTokenSel} />
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
            {SIDEBAR_ITEMS.map(({ ic: Icon, label, active }, i) => (
              <div
                key={i}
                style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 10px', margin: '1px 8px 1px 0', background: active ? 'var(--accent-soft)' : 'transparent', borderLeft: active ? '2px solid var(--accent)' : '2px solid transparent', borderRadius: '0 6px 6px 0', fontSize: 11, color: active ? 'var(--ink)' : 'var(--ink-3)', fontWeight: active ? 500 : 400, cursor: 'pointer' }}
              >
                <Icon size={12} strokeWidth={1.75} color={active ? 'var(--accent)' : 'var(--ink-4)'} />
                <span>{label}</span>
              </div>
            ))}
          </div>

          <div style={{ height: 1, background: 'var(--rule)', margin: '6px 0' }} />

          <div style={{ padding: '2px 12px 0' }}>
            <div className="cap" style={{ marginBottom: 6 }}>RÉCENTS</div>
            {recentProjects.map((n, i) => (
              <div
                key={i}
                onClick={() => navigateTo({ kind: 'inside', project: n, subpath: [] })}
                style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '5px 0', fontSize: 11, color: n === activeProject ? 'var(--accent-hi)' : 'var(--ink-3)', cursor: 'pointer' }}
              >
                <FolderIcon size={11} color={n === activeProject ? 'var(--accent)' : 'var(--ink-4)'} />
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{n}</span>
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

        {/* Grille / Résultats de recherche */}
        <div
          style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, borderRight: '1px solid var(--rule)', overflow: 'hidden' }}
          onClick={() => { if (searchResults === null) setSelectedName(null) }}
        >
          {/* ── Page de résultats temporaire ── */}
          {searchResults !== null ? (
            <>
              {/* Header résultats */}
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
                  <X size={9} strokeWidth={2} />
                  Fermer
                </div>
              </div>

              {/* Liste des résultats */}
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
          ) : (
            /* ── Vue explorer normale ── */
            loading ? (
              <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--ink-4)', fontSize: 11, fontStyle: 'italic' }}>
                Chargement…
              </div>
            ) : items.length === 0 ? (
              <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--ink-4)', fontSize: 11, fontStyle: 'italic' }}>
                Vide
              </div>
            ) : (
              <div style={{ flex: 1, padding: '10px 12px', overflowY: 'auto', minHeight: 0 }}>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(80px, 1fr))', gap: '4px', alignContent: 'start' }}>
                  {items.map((item, i) => {
                    const isSel = item.name === selectedName
                    return (
                      <div
                        key={i}
                        onClick={e => { e.stopPropagation(); setSelectedName(item.name) }}
                        onDoubleClick={e => { e.stopPropagation(); handleDoubleClick(item) }}
                        style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '8px 4px 6px', borderRadius: 6, background: isSel ? 'var(--accent-soft)' : 'transparent', border: isSel ? '1px solid var(--accent)' : '1px solid transparent', gap: 5, cursor: 'default', userSelect: 'none', transition: 'background 0.08s' }}
                      >
                        {item.isDir
                          ? <FolderSvg size={40} selected={isSel} />
                          : <FileSvg   size={34} selected={isSel} />}
                        <div style={{ fontSize: 10, textAlign: 'center', color: isSel ? 'var(--ink)' : 'var(--ink-2)', fontWeight: isSel ? 500 : 400, wordBreak: 'break-all', lineHeight: 1.3, maxWidth: '100%', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' as const, overflow: 'hidden' }}>
                          {item.name}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )
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
            {tab === 'directory' && <TabDirectory currentProject={navProject} />}
          </div>

          {/* Projet actif + Set Project — fixe en bas */}
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
    </div>
  )
}
