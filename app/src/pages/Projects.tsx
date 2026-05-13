import { useState, useEffect, useCallback } from 'react'
import { ChevronLeft, ChevronRight, Search, Star, LayoutGrid, Clock, Archive, HardDrive, Plus, Minus, ChevronDown } from 'lucide-react'
import { FolderIcon } from '../components/shared/ui'
import { api } from '../api/client'

const SIDEBAR_ITEMS = [
  { ic: Star,       label: 'Favoris' },
  { ic: LayoutGrid, label: 'Tous les projets', active: true },
  { ic: Clock,      label: 'Récents' },
  { ic: Archive,    label: 'Archivés' },
]


const ASSET_TOKENS = ['CHAR', 'PROPS', 'ENV', 'CFXRIG', 'FXRIG']

type Tab = 'project' | 'asset' | 'shot' | 'directory'

const TABS: { id: Tab; label: string }[] = [
  { id: 'project',   label: 'Project' },
  { id: 'asset',     label: 'Asset' },
  { id: 'shot',      label: 'Shot' },
  { id: 'directory', label: 'Directory' },
]

/* ── spinner entier ── */
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

/* ── select simple ── */
function Select({ options, value, onChange }: { options: string[]; value: string; onChange: (v: string) => void }) {
  return (
    <div style={{ position: 'relative', height: 28 }}>
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        style={{
          width: '100%', height: '100%',
          border: '1px solid var(--rule-2)', borderRadius: 5,
          background: 'var(--bg-deep)', color: 'var(--ink)',
          fontFamily: 'var(--mono)', fontSize: 10,
          padding: '0 24px 0 8px',
          appearance: 'none', cursor: 'pointer',
          boxShadow: 'var(--shadow-inset)', outline: 'none',
        }}
      >
        {options.length === 0
          ? <option value="">—</option>
          : options.map(o => <option key={o} value={o}>{o}</option>)}
      </select>
      <ChevronDown size={10} strokeWidth={2} color="var(--ink-3)" style={{ position: 'absolute', right: 7, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }} />
    </div>
  )
}

/* ── champ texte éditable ── */
function InputField({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder: string }) {
  return (
    <input
      value={value}
      onChange={e => onChange(e.target.value)}
      placeholder={placeholder}
      style={{
        width: '100%', height: 28,
        border: '1px solid var(--rule-2)', borderRadius: 5,
        background: 'var(--bg-deep)', color: 'var(--ink)',
        fontFamily: 'var(--mono)', fontSize: 10,
        padding: '0 8px', boxShadow: 'var(--shadow-inset)', outline: 'none',
      }}
    />
  )
}

/* ── bouton utilitaire ── */
function PanelBtn({ primary, children, onClick, disabled }: {
  primary?: boolean; children: React.ReactNode; onClick?: () => void; disabled?: boolean
}) {
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

/* ── onglet Project ── */
function TabProject({ projects, onSetProject, onCreateProject }: {
  projects: string[]
  onSetProject: (name: string) => void
  onCreateProject: (name: string) => Promise<void>
}) {
  const [name, setName] = useState('')
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

  const handleSet = () => {
    const found = projects.find(p => p.toLowerCase() === name.trim().toLowerCase())
    if (found) { onSetProject(found); setStatus('✓ Projet actif') }
    else if (name.trim()) setStatus('✗ Projet introuvable')
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, flex: 1 }}>
      <div>
        <div className="cap" style={{ marginBottom: 4 }}>PROJECT NAME</div>
        <InputField value={name} onChange={setName} placeholder="ex: NEW_PROJECT" />
      </div>
      {status && <div style={{ fontFamily: 'var(--mono)', fontSize: 10, color: status.startsWith('✓') ? 'var(--ok)' : 'var(--err)' }}>{status}</div>}
      <div style={{ flex: 1 }} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <PanelBtn primary onClick={() => void handleCreate()} disabled={!name.trim()}>Create Project</PanelBtn>
        <PanelBtn onClick={handleSet}>Set Project</PanelBtn>
      </div>
    </div>
  )
}

/* ── onglet Asset ── */
function TabAsset({ activeProject, onCreateAsset }: {
  activeProject: string
  onCreateAsset: (project: string, classToken: string, name: string) => Promise<void>
}) {
  const [token, setToken] = useState('CHAR')
  const [name, setName]   = useState('')
  const [status, setStatus] = useState('')

  const handleCreate = async () => {
    if (!activeProject || !name.trim()) return
    try {
      await onCreateAsset(activeProject, token, name.trim())
      setStatus('✓ Créé')
      setName('')
    } catch (e) {
      setStatus('✗ ' + (e instanceof Error ? e.message : 'Erreur'))
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, flex: 1 }}>
      <div>
        <div className="cap" style={{ marginBottom: 4 }}>TYPE</div>
        <Select options={ASSET_TOKENS} value={token} onChange={setToken} />
      </div>
      <div>
        <div className="cap" style={{ marginBottom: 4 }}>NAME</div>
        <InputField value={name} onChange={setName} placeholder="ex: HorseRig" />
      </div>
      {status && <div style={{ fontFamily: 'var(--mono)', fontSize: 10, color: status.startsWith('✓') ? 'var(--ok)' : 'var(--err)' }}>{status}</div>}
      <div style={{ flex: 1 }} />
      <PanelBtn primary onClick={() => void handleCreate()} disabled={!activeProject || !name.trim()}>Create Asset</PanelBtn>
    </div>
  )
}

/* ── onglet Shot ── */
function TabShot({ activeProject, sequences, onCreateSequence, onCreateShot, onRefreshSequences }: {
  activeProject: string
  sequences: string[]
  onCreateSequence: (project: string, seqN: number) => Promise<void>
  onCreateShot: (project: string, seqN: number, shotN: number) => Promise<void>
  onRefreshSequences: () => void
}) {
  const [seqN, setSeqN]   = useState(10)
  const [shotN, setShotN] = useState(10)
  const [seq, setSeq]     = useState('')
  const [statusSeq, setStatusSeq]   = useState('')
  const [statusShot, setStatusShot] = useState('')

  useEffect(() => {
    setSeq(sequences[0] ?? '')
  }, [sequences])

  const handleCreateSeq = async () => {
    if (!activeProject) return
    try {
      await onCreateSequence(activeProject, seqN)
      setStatusSeq('✓ SQ' + String(seqN).padStart(3, '0'))
      onRefreshSequences()
    } catch (e) {
      setStatusSeq('✗ ' + (e instanceof Error ? e.message : 'Erreur'))
    }
  }

  const handleCreateShot = async () => {
    if (!activeProject || !seq) return
    const seqNum = parseInt(seq.replace(/^SQ0*/, ''), 10) || seqN
    try {
      await onCreateShot(activeProject, seqNum, shotN)
      setStatusShot(`✓ SQ${String(seqNum).padStart(3,'0')}_SH${String(shotN).padStart(3,'0')}`)
    } catch (e) {
      setStatusShot('✗ ' + (e instanceof Error ? e.message : 'Erreur'))
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, flex: 1 }}>

      {/* SEQ */}
      <div style={{ padding: '10px', border: '1px solid var(--rule-2)', borderRadius: 7, background: 'var(--bg-deep)', display: 'flex', flexDirection: 'column', gap: 8, boxShadow: 'var(--shadow-inset)' }}>
        <div className="cap">SEQ</div>
        <Spinner value={seqN} onChange={setSeqN} />
        {statusSeq && <div style={{ fontFamily: 'var(--mono)', fontSize: 9, color: statusSeq.startsWith('✓') ? 'var(--ok)' : 'var(--err)' }}>{statusSeq}</div>}
        <PanelBtn primary onClick={() => void handleCreateSeq()} disabled={!activeProject}>Create Sequence</PanelBtn>
      </div>

      {/* SHOT */}
      <div style={{ padding: '10px', border: '1px solid var(--rule-2)', borderRadius: 7, background: 'var(--bg-deep)', display: 'flex', flexDirection: 'column', gap: 8, boxShadow: 'var(--shadow-inset)' }}>
        <div className="cap">SHOT</div>
        <div>
          <div className="cap" style={{ marginBottom: 4, fontSize: 8 }}>IN SEQUENCE</div>
          <Select options={sequences.length > 0 ? sequences : ['—']} value={seq} onChange={setSeq} />
        </div>
        <div>
          <div className="cap" style={{ marginBottom: 4, fontSize: 8 }}>SHOT NO.</div>
          <Spinner value={shotN} onChange={setShotN} />
        </div>
        {statusShot && <div style={{ fontFamily: 'var(--mono)', fontSize: 9, color: statusShot.startsWith('✓') ? 'var(--ok)' : 'var(--err)' }}>{statusShot}</div>}
        <PanelBtn primary onClick={() => void handleCreateShot()} disabled={!activeProject || !seq}>Create Shot</PanelBtn>
      </div>

      <div style={{ flex: 1 }} />
    </div>
  )
}

/* ── onglet Directory ── */
function TabDirectory() {
  const DIR_FIELDS = [
    { label: 'NAME',       ph: 'ex: NEW_PROJECT' },
    { label: 'TOKEN',      ph: 'ex: SLA' },
    { label: 'TOKEN TYPE', ph: 'Projet' },
  ]
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, flex: 1 }}>
      {DIR_FIELDS.map(({ label, ph }) => (
        <div key={label}>
          <div className="cap" style={{ marginBottom: 4 }}>{label}</div>
          <InputField value="" onChange={() => {}} placeholder={ph} />
        </div>
      ))}
      <div style={{ flex: 1 }} />
      <PanelBtn primary>Add Folder</PanelBtn>
    </div>
  )
}

/* ── composant principal ── */
export function Projects() {
  const [tab, setTab]                 = useState<Tab>('project')
  const [projects, setProjects]       = useState<string[]>([])
  const [activeProject, setActiveProject] = useState('')
  const [sequences, setSequences]     = useState<string[]>([])

  const loadProjects = useCallback(async () => {
    try {
      const d = await api.getProjects()
      setProjects(d.projects)
      if (!activeProject && d.projects.length > 0) setActiveProject(d.projects[0])
    } catch {}
  }, [activeProject])

  const loadSequences = useCallback(async () => {
    if (!activeProject) return
    try {
      const d = await api.getSequences(activeProject)
      setSequences(d.sequences)
    } catch {}
  }, [activeProject])

  useEffect(() => { void loadProjects() }, [])
  useEffect(() => { void loadSequences() }, [activeProject])

  const handleCreateProject = useCallback(async (name: string) => {
    await api.createProject(name)
    await loadProjects()
    setActiveProject(name)
  }, [loadProjects])

  const handleCreateAsset = useCallback(async (project: string, classToken: string, name: string) => {
    await api.createAsset(project, classToken, name)
  }, [])

  const handleCreateSequence = useCallback(async (project: string, seqN: number) => {
    await api.createSequence(project, seqN)
  }, [])

  const handleCreateShot = useCallback(async (project: string, seqN: number, shotN: number) => {
    await api.createShot(project, seqN, shotN)
  }, [])

  const recentProjects = projects.slice(0, 3)

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>

      <div style={{ padding: '12px 20px', borderBottom: '1px solid var(--rule)', flexShrink: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.1em', color: 'var(--ink)' }}>Projets</div>
      </div>

      {/* barre de navigation */}
      <div style={{ padding: '5px 10px', borderBottom: '1px solid var(--rule)', background: 'var(--paper-2)', flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, height: 26 }}>
          <div style={{ display: 'flex', gap: 3 }}>
            {[ChevronLeft, ChevronRight].map((Icon, i) => (
              <div key={i} style={{ width: 24, height: 24, border: '1px solid var(--rule-2)', borderRadius: 5, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--ink-4)', boxShadow: 'var(--shadow-xs)', cursor: 'pointer' }}>
                <Icon size={13} strokeWidth={2} />
              </div>
            ))}
          </div>

          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4, fontFamily: 'var(--mono)', fontSize: 10, height: 24, border: '1px solid var(--rule)', padding: '0 10px', background: 'var(--bg-deep)', borderRadius: 5, boxShadow: 'var(--shadow-inset)' }}>
            {activeProject
              ? <span style={{ color: 'var(--ink)', fontWeight: 600 }}>{activeProject}</span>
              : <span style={{ color: 'var(--ink-4)' }}>—</span>}
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 6, border: '1px solid var(--rule)', padding: '0 8px', height: 24, width: 150, background: 'var(--bg-deep)', borderRadius: 5, boxShadow: 'var(--shadow-inset)' }}>
            <Search size={11} strokeWidth={2} color="var(--ink-4)" />
            <span style={{ fontSize: 10, color: 'var(--ink-4)', fontStyle: 'italic' }}>Rechercher…</span>
          </div>
        </div>
      </div>

      <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>

        {/* ── sidebar gauche ── */}
        <div style={{ width: 170, borderRight: '1px solid var(--rule)', display: 'flex', flexDirection: 'column', background: 'var(--paper-2)', flexShrink: 0 }}>
          <div style={{ padding: '8px 0 4px' }}>
            {SIDEBAR_ITEMS.map(({ ic: Icon, label, active }, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 10px', margin: '1px 8px 1px 0', background: active ? 'var(--accent-soft)' : 'transparent', borderLeft: active ? '2px solid var(--accent)' : '2px solid transparent', borderRadius: '0 6px 6px 0', fontSize: 11, color: active ? 'var(--ink)' : 'var(--ink-3)', fontWeight: active ? 500 : 400, cursor: 'pointer', transition: 'background 0.1s' }}>
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
                onClick={() => setActiveProject(n)}
                style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '5px 0', fontSize: 11, color: n === activeProject ? 'var(--accent-hi)' : 'var(--ink-3)', cursor: 'pointer' }}
              >
                <FolderIcon size={11} color={n === activeProject ? 'var(--accent)' : 'var(--ink-4)'} />
                <span>{n}</span>
              </div>
            ))}
          </div>

          <div style={{ flex: 1 }} />
          <div style={{ padding: '10px 12px 12px', borderTop: '1px solid var(--rule)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 8 }}>
              <HardDrive size={10} strokeWidth={1.75} color="var(--ink-4)" />
              <div className="cap">WORKSPACE</div>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, marginBottom: 4 }}>
              <span style={{ color: 'var(--ink-3)' }}>Projets</span>
              <span style={{ fontFamily: 'var(--mono)', color: 'var(--ink-2)', fontSize: 10 }}>{projects.length}</span>
            </div>
          </div>
        </div>

        {/* ── grille de dossiers ── */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, borderRight: '1px solid var(--rule)', overflow: 'hidden' }}>
          <div style={{ padding: '10px 14px 6px', flexShrink: 0 }}>
            <div className="cap">DOSSIERS</div>
          </div>
          <div style={{ flex: 1, padding: '4px 14px 14px', overflowY: 'auto', minHeight: 0 }}>
            {projects.length === 0 && (
              <div style={{ padding: 12, fontSize: 11, color: 'var(--ink-4)', fontStyle: 'italic' }}>Aucun projet</div>
            )}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(100px, 1fr))', gap: 6, alignContent: 'start' }}>
              {projects.map((name, i) => {
                const isActive = name === activeProject
                return (
                  <div
                    key={i}
                    onClick={() => setActiveProject(name)}
                    style={{
                      padding: '12px 8px 10px',
                      border: isActive ? '1px solid var(--accent)' : '1px solid var(--rule-2)',
                      background: isActive ? 'var(--accent-soft)' : 'var(--paper-2)',
                      display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 6,
                      borderRadius: 8, cursor: 'pointer',
                      boxShadow: isActive ? 'var(--shadow-sm)' : 'var(--shadow-xs)',
                      transition: 'background 0.1s, box-shadow 0.12s',
                    }}
                  >
                    <FolderIcon size={28} color={isActive ? 'var(--accent)' : 'var(--ink-4)'} />
                    <div style={{ fontSize: 10, fontWeight: isActive ? 600 : 400, color: isActive ? 'var(--ink)' : 'var(--ink-3)', wordBreak: 'break-all' }}>{name}</div>
                  </div>
                )
              })}
            </div>
          </div>
        </div>

        {/* ── panneau droite avec onglets ── */}
        <div style={{ width: 200, display: 'flex', flexDirection: 'column', flexShrink: 0 }}>

          <div style={{ display: 'flex', borderBottom: '1px solid var(--rule)', flexShrink: 0, background: 'var(--paper-2)' }}>
            {TABS.map(t => (
              <div
                key={t.id}
                onClick={() => setTab(t.id)}
                style={{
                  flex: 1, height: 32,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontFamily: 'var(--mono)', fontSize: 8.5,
                  textTransform: 'uppercase', letterSpacing: '0.08em',
                  color: tab === t.id ? 'var(--accent-hi)' : 'var(--ink-4)',
                  borderBottom: tab === t.id ? '2px solid var(--accent)' : '2px solid transparent',
                  background: tab === t.id ? 'var(--accent-soft)' : 'transparent',
                  cursor: 'pointer', transition: 'color 0.12s, background 0.12s',
                }}
              >
                {t.label}
              </div>
            ))}
          </div>

          <div style={{ flex: 1, padding: '12px', display: 'flex', flexDirection: 'column', overflowY: 'auto' }}>
            {tab === 'project' && (
              <TabProject
                projects={projects}
                onSetProject={setActiveProject}
                onCreateProject={handleCreateProject}
              />
            )}
            {tab === 'asset' && (
              <TabAsset
                activeProject={activeProject}
                onCreateAsset={handleCreateAsset}
              />
            )}
            {tab === 'shot' && (
              <TabShot
                activeProject={activeProject}
                sequences={sequences}
                onCreateSequence={handleCreateSequence}
                onCreateShot={handleCreateShot}
                onRefreshSequences={() => void loadSequences()}
              />
            )}
            {tab === 'directory' && <TabDirectory />}

            {/* active project — toujours visible en bas */}
            <div style={{ marginTop: 12, paddingTop: 10, borderTop: '1px solid var(--rule)' }}>
              <div className="cap" style={{ marginBottom: 6 }}>PROJET ACTIF</div>
              <div style={{ padding: '8px 10px', borderRadius: 6, border: '1px solid var(--accent)', background: 'var(--accent-soft)', boxShadow: 'var(--shadow-xs)' }}>
                <div style={{ fontFamily: 'var(--mono)', fontSize: 10, fontWeight: 600, color: 'var(--accent-hi)' }}>
                  {activeProject || '—'}
                </div>
                <div style={{ fontSize: 9, color: 'var(--ink-3)', marginTop: 3 }}>
                  {sequences.length > 0 ? `${sequences.length} séquences` : 'Aucune séquence'}
                </div>
              </div>
            </div>
          </div>

        </div>
      </div>
    </div>
  )
}
