import { useState, useEffect, useCallback } from 'react'
import {
  ChevronLeft, ChevronRight, Search,
  Star, LayoutGrid, Clock, Archive,
  HardDrive, Plus, Minus, ChevronDown,
} from 'lucide-react'
import { FolderIcon } from '../components/shared/ui'
import { api } from '../api/client'

// ── Types ─────────────────────────────────────────────────────────────────────

type NavLevel =
  | { kind: 'root' }
  | { kind: 'inside'; project: string; subpath: string[] }

interface ExplorerItem { name: string; isDir: boolean }

type Tab = 'project' | 'asset' | 'shot' | 'directory'
const TABS: { id: Tab; label: string }[] = [
  { id: 'project',   label: 'Projet' },
  { id: 'asset',     label: 'Asset' },
  { id: 'shot',      label: 'Shot' },
  { id: 'directory', label: 'Dossier' },
]

const ASSET_TOKENS = ['CHAR', 'PROPS', 'ENV', 'CFXRIG', 'FXRIG']
const TOKEN_TYPES  = ['CLASS', 'TYPE', 'NAME', 'SEQ', 'SHOT', 'custom']

const SIDEBAR_ITEMS = [
  { ic: Star,       label: 'Favoris' },
  { ic: LayoutGrid, label: 'Tous', active: true },
  { ic: Clock,      label: 'Récents' },
  { ic: Archive,    label: 'Archivés' },
]

// ── Icônes SVG — couleur plate, réactive à la sélection ──────────────────────
// Pas de linearGradient → pas de collision d'IDs entre instances.
// Quand selected=true, l'icône vire à var(--accent) pour le feedback visuel.

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

// ── Contexte projet actuel ────────────────────────────────────────────────────

function NavContext({ project }: { project: string }) {
  if (!project) return (
    <div style={{ padding: '6px 8px', borderRadius: 5, border: '1px solid var(--rule-2)', background: 'var(--bg-deep)', fontFamily: 'var(--mono)', fontSize: 9, color: 'var(--ink-4)', fontStyle: 'italic' }}>
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

// "Create Project" uniquement — Set Project est sorti dans le bas du panneau
function TabProject({ onCreateProject }: {
  onCreateProject: (name: string) => Promise<void>
}) {
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
      {status && (
        <div style={{ fontFamily: 'var(--mono)', fontSize: 10, color: status.startsWith('✓') ? 'var(--ok)' : 'var(--err)' }}>
          {status}
        </div>
      )}
      <div style={{ flex: 1 }} />
      <PanelBtn primary onClick={() => void handleCreate()} disabled={!name.trim()}>
        Create Project
      </PanelBtn>
    </div>
  )
}

// Création relative au projet courant dans l'explorer
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
      {status && (
        <div style={{ fontFamily: 'var(--mono)', fontSize: 10, color: status.startsWith('✓') ? 'var(--ok)' : 'var(--err)' }}>
          {status}
        </div>
      )}
      <div style={{ flex: 1 }} />
      <PanelBtn primary onClick={() => void handleCreate()} disabled={!currentProject || !name.trim()}>
        Create Asset
      </PanelBtn>
    </div>
  )
}

function TabShot({ currentProject, sequences, onCreateSequence, onCreateShot, onRefreshSequences }: {
  currentProject: string
  sequences: string[]
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
  // Navigation
  const [navStack, setNavStack] = useState<NavLevel[]>([{ kind: 'root' }])
  const [navIdx, setNavIdx]     = useState(0)
  const nav = navStack[navIdx]

  // Explorer
  const [items, setItems]               = useState<ExplorerItem[]>([])
  const [selectedName, setSelectedName] = useState<string | null>(null)
  const [loading, setLoading]           = useState(false)

  // Projets
  const [projects, setProjects]           = useState<string[]>([])
  const [activeProject, setActiveProject] = useState('')
  const [sequences, setSequences]         = useState<string[]>([])

  // Panneau droit
  const [tab, setTab] = useState<Tab>('project')

  // ── Dérivés ────────────────────────────────────────────────────────────────

  const breadcrumb: string[] = nav.kind === 'root'
    ? ['PROJETS']
    : ['PROJETS', nav.project, ...nav.subpath]

  // Projet du contexte de navigation — utilisé pour création et "Set Project"
  const navProject: string = nav.kind === 'inside' ? nav.project : ''

  // Projet à définir via "Set Project" : priorité à la nav, sinon item sélectionné
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
  }, [navIdx])

  const goBack = useCallback(() => {
    if (navIdx > 0) { setNavIdx(i => i - 1); setSelectedName(null) }
  }, [navIdx])

  const goForward = useCallback(() => {
    if (navIdx < navStack.length - 1) { setNavIdx(i => i + 1); setSelectedName(null) }
  }, [navIdx, navStack.length])

  const navigateToBreadcrumb = useCallback((segIdx: number) => {
    if (segIdx === 0) {
      navigateTo({ kind: 'root' })
    } else if (nav.kind === 'inside') {
      navigateTo({ kind: 'inside', project: nav.project, subpath: nav.subpath.slice(0, segIdx - 1) })
    }
  }, [nav, navigateTo])

  // ── Chargement ─────────────────────────────────────────────────────────────

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
    } catch {
      setItems([])
    } finally {
      setLoading(false)
    }
  }, [nav])

  useEffect(() => { void loadItems() }, [loadItems])

  const loadSequences = useCallback(async () => {
    if (!activeProject) return
    try {
      const d = await api.getSequences(activeProject)
      setSequences(d.sequences)
    } catch {}
  }, [activeProject])

  useEffect(() => { void loadSequences() }, [activeProject])

  // ── Handlers ───────────────────────────────────────────────────────────────

  const handleDoubleClick = useCallback((item: ExplorerItem) => {
    if (!item.isDir) return
    if (nav.kind === 'root') {
      navigateTo({ kind: 'inside', project: item.name, subpath: [] })
    } else {
      navigateTo({ kind: 'inside', project: nav.project, subpath: [...nav.subpath, item.name] })
    }
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

      {/* Barre de navigation */}
      <div style={{ padding: '5px 10px', borderBottom: '1px solid var(--rule)', background: 'var(--paper-2)', flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, height: 26 }}>

          {[
            { Icon: ChevronLeft,  action: goBack,    ok: canBack },
            { Icon: ChevronRight, action: goForward, ok: canForward },
          ].map(({ Icon, action, ok }, i) => (
            <div
              key={i}
              onClick={ok ? action : undefined}
              style={{ width: 24, height: 24, border: '1px solid var(--rule-2)', borderRadius: 5, display: 'flex', alignItems: 'center', justifyContent: 'center', color: ok ? 'var(--ink-2)' : 'var(--ink-4)', boxShadow: 'var(--shadow-xs)', cursor: ok ? 'pointer' : 'default', opacity: ok ? 1 : 0.4 }}
            >
              <Icon size={13} strokeWidth={2} />
            </div>
          ))}

          {/* Breadcrumb */}
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 2, fontFamily: 'var(--mono)', fontSize: 10, height: 24, border: '1px solid var(--rule)', padding: '0 10px', background: 'var(--bg-deep)', borderRadius: 5, boxShadow: 'var(--shadow-inset)', overflow: 'hidden' }}>
            {breadcrumb.map((seg, i) => {
              const isLast = i === breadcrumb.length - 1
              return (
                <span key={i} style={{ display: 'flex', alignItems: 'center', gap: 2, flexShrink: isLast ? 1 : 0, minWidth: 0 }}>
                  {i > 0 && <ChevronRight size={9} strokeWidth={1.5} color="var(--ink-4)" style={{ flexShrink: 0 }} />}
                  <span
                    onClick={!isLast ? () => navigateToBreadcrumb(i) : undefined}
                    style={{ color: isLast ? 'var(--ink)' : 'var(--ink-3)', fontWeight: isLast ? 600 : 400, cursor: !isLast ? 'pointer' : 'default', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
                  >
                    {seg}
                  </span>
                </span>
              )
            })}
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 6, border: '1px solid var(--rule)', padding: '0 8px', height: 24, width: 150, background: 'var(--bg-deep)', borderRadius: 5, boxShadow: 'var(--shadow-inset)' }}>
            <Search size={11} strokeWidth={2} color="var(--ink-4)" />
            <span style={{ fontSize: 10, color: 'var(--ink-4)', fontStyle: 'italic' }}>Rechercher…</span>
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

        {/* Grille explorateur */}
        <div
          style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, borderRight: '1px solid var(--rule)', overflow: 'hidden' }}
          onClick={() => setSelectedName(null)}
        >
          {loading ? (
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
          )}
        </div>

        {/* Panneau droit */}
        <div style={{ width: 200, display: 'flex', flexDirection: 'column', flexShrink: 0 }}>

          {/* Onglets */}
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

          {/* Contenu de l'onglet — scrollable */}
          <div style={{ flex: 1, padding: '12px', display: 'flex', flexDirection: 'column', overflowY: 'auto', minHeight: 0 }}>
            {tab === 'project' && (
              <TabProject onCreateProject={handleCreateProject} />
            )}
            {tab === 'asset' && (
              <TabAsset currentProject={navProject} onCreateAsset={handleCreateAsset} />
            )}
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

          {/* Projet actif + Set Project — toujours visible en bas */}
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
            <PanelBtn
              onClick={() => contextProject && handleSetProject(contextProject)}
              disabled={!contextProject}
            >
              Set Project
            </PanelBtn>
          </div>

        </div>
      </div>
    </div>
  )
}
