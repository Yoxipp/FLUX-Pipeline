import { useState, useEffect } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import {
  Home, Upload, Download, Layers,
  BookOpen, FolderOpen, Activity,
  ChevronDown, ChevronRight,
  Play, Settings2, Loader, Search,
} from 'lucide-react'
import type { DccStatusMap } from '../../types'
import { api } from '../../api/client'

interface Props {
  dccStatus: DccStatusMap
  unreadCount: number
}

// Clés correspondant exactement aux DCC_PORTS du backend
const SOFTWARE = [
  { name: 'Maya',               v: '2025.3', key: 'maya' },
  { name: 'Houdini',            v: '20.5',   key: 'houdini' },
  { name: 'Nuke',               v: '15.0',   key: 'nuke' },
  { name: 'Substance Painter',  v: '10.1',   key: 'substance_painter' },
  { name: 'Substance Designer', v: '13.1',   key: 'substance_designer' },
  { name: 'ZBrush',             v: '2024.0', key: 'zbrush' },
  { name: 'Marvelous Designer', v: '12.2',   key: 'marvelous' },
  { name: 'Photoshop',          v: '2025',   key: 'photoshop' },
]

function dccDot(status: DccStatusMap, key: string): string {
  const entry = status[key]
  if (!entry) return ''
  return entry.connected ? 'ok' : ''
}

function NavItem({ icon: Icon, label, active, indent = false, notif = 0, onClick }: {
  icon: React.ElementType; label: string; active?: boolean; indent?: boolean; notif?: number; onClick?: () => void
}) {
  return (
    <div
      className={`nav${active ? ' active' : ''}`}
      style={indent ? { paddingLeft: 24 } : {}}
      onClick={onClick}
    >
      <span className="glyph"><Icon size={13} strokeWidth={1.75} /></span>
      <span style={{ flex: 1 }}>{label}</span>
      {notif > 0 && (
        <span style={{
          minWidth: 17, height: 17, padding: '0 4px', borderRadius: 6,
          background: 'var(--accent-soft)',
          border: '1px solid var(--accent)',
          color: 'var(--accent-hi)',
          fontFamily: 'var(--mono)', fontSize: 8, fontWeight: 600,
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          boxShadow: 'var(--shadow-xs)',
        }}>{notif}</span>
      )}
    </div>
  )
}

function NavGroup({ title, children, open = true }: {
  title: string; children: React.ReactNode; open?: boolean
}) {
  return (
    <div style={{ marginTop: 4 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 12px 3px' }}>
        <div className="cap" style={{ flex: 1 }}>{title}</div>
        {open
          ? <ChevronDown size={10} strokeWidth={2} color="var(--ink-4)" />
          : <ChevronRight size={10} strokeWidth={2} color="var(--ink-4)" />
        }
      </div>
      {open && children}
    </div>
  )
}

export function Sidebar({ dccStatus, unreadCount }: Props) {
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const [launching, setLaunching]     = useState<Set<string>>(new Set())
  const [launchResult, setLaunchResult] = useState<Record<string, boolean>>({})
  const [dccPaths, setDccPaths]       = useState<Record<string, string>>({})
  const [finding, setFinding]         = useState<Set<string>>(new Set())
  const [findResult, setFindResult]   = useState<Record<string, boolean | null>>({})

  useEffect(() => {
    api.getSettings().then(s => setDccPaths(s.dcc_paths ?? {})).catch(() => {})
  }, [])

  const handleAutoFind = async (key: string) => {
    setFinding(prev => new Set(prev).add(key))
    try {
      const res = await api.findDccExe(key)
      if (res.found && res.path) {
        setDccPaths(prev => ({ ...prev, [key]: res.path! }))
        setFindResult(prev => ({ ...prev, [key]: true }))
      } else {
        setFindResult(prev => ({ ...prev, [key]: false }))
      }
    } catch {
      setFindResult(prev => ({ ...prev, [key]: false }))
    } finally {
      setFinding(prev => { const next = new Set(prev); next.delete(key); return next })
      setTimeout(() => setFindResult(prev => { const n = { ...prev }; delete n[key]; return n }), 2500)
    }
  }

  const handlePickPath = async (key: string) => {
    const path = await window.electronAPI?.openFile([{ name: 'Executable', extensions: ['exe', 'app', ''] }])
    if (!path) return
    await api.updateSettings({ dcc_path: { [key]: path } })
    setDccPaths(prev => ({ ...prev, [key]: path }))
  }

  const handleLaunch = async (key: string) => {
    setLaunching(prev => new Set(prev).add(key))
    try {
      const res = await api.launchDcc(key)
      setLaunchResult(prev => ({ ...prev, [key]: res.launched }))
    } catch {
      setLaunchResult(prev => ({ ...prev, [key]: false }))
    } finally {
      setLaunching(prev => { const next = new Set(prev); next.delete(key); return next })
    }
  }

  return (
    <div style={{
      width: 200, borderRight: '1px solid var(--rule)',
      background: 'var(--paper)',
      display: 'flex', flexDirection: 'column',
      flexShrink: 0,
    }}>
      <div style={{ padding: '10px 0 0' }}>
        <NavItem icon={Home} label="Accueil" active={pathname === '/'} onClick={() => navigate('/')} />
      </div>

      <NavGroup title="ASSETS">
        <NavItem icon={Upload}   label="Publisher"      active={pathname === '/publisher'} indent onClick={() => navigate('/publisher')} />
        <NavItem icon={Download} label="Importer"       active={pathname === '/importer'}  indent onClick={() => navigate('/importer')} />
        <NavItem icon={Layers}   label="USD Assembleur" active={pathname === '/usd'}       indent onClick={() => navigate('/usd')} />
      </NavGroup>

      <NavGroup title="PIPELINE">
        <NavItem icon={BookOpen}   label="Shelf Manager"  active={pathname === '/shelf'}    indent onClick={() => navigate('/shelf')} />
        <NavItem icon={FolderOpen} label="Folder Manager" active={pathname === '/projects'} indent onClick={() => navigate('/projects')} />
        <NavItem icon={Activity}   label="Activité"       active={pathname === '/activity'} indent notif={unreadCount} onClick={() => navigate('/activity')} />
      </NavGroup>

      <NavGroup title="LAUNCHER">
        {SOFTWARE.map(s => {
          const dot       = dccDot(dccStatus, s.key)
          const connected = dot === 'ok'
          const isLoading = launching.has(s.key)

          const hasPath    = !!dccPaths[s.key]
          const isFinding  = finding.has(s.key)
          const findOk     = findResult[s.key]

          return (
            <div key={s.key} style={{
              display: 'flex', alignItems: 'center', gap: 4,
              padding: '5px 10px 5px 18px',
              fontSize: 11, color: connected ? 'var(--ink-2)' : 'var(--ink-4)',
            }}>
              <span className={`dot${connected ? ' ok' : ''}`} style={{ width: 5, height: 5, flexShrink: 0 }} />
              <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.name}</span>

              {/* auto-find feedback badge — replaces version when active */}
              {findOk === true  && <span style={{ fontFamily: 'var(--mono)', fontSize: 8, color: 'var(--ok)' }}>✓</span>}
              {findOk === false && <span style={{ fontFamily: 'var(--mono)', fontSize: 8, color: 'var(--err)' }}>✗</span>}
              {findOk === undefined && <span style={{ fontFamily: 'var(--mono)', fontSize: 9, color: 'var(--ink-4)' }}>{s.v}</span>}

              {/* auto-find */}
              <div
                onClick={() => { if (!isFinding) void handleAutoFind(s.key) }}
                title="Auto-détecter le chemin"
                style={{
                  width: 16, height: 16, borderRadius: 4,
                  border: '1px solid var(--rule-2)',
                  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                  flexShrink: 0,
                  background: 'transparent',
                  color: 'var(--ink-4)',
                  cursor: isFinding ? 'default' : 'pointer',
                  transition: 'background 0.12s, border-color 0.12s, color 0.12s',
                }}
                onMouseEnter={e => { if (!isFinding) { const el = e.currentTarget as HTMLElement; el.style.borderColor = 'var(--rule-2)'; el.style.background = 'var(--paper-2)'; el.style.color = 'var(--ink-2)' } }}
                onMouseLeave={e => { const el = e.currentTarget as HTMLElement; el.style.borderColor = 'var(--rule-2)'; el.style.background = 'transparent'; el.style.color = 'var(--ink-4)' }}
              >
                {isFinding
                  ? <Loader size={8} strokeWidth={2} style={{ animation: 'spin 1s linear infinite' }} />
                  : <Search size={8} strokeWidth={2} />
                }
              </div>

              {/* path picker */}
              <div
                onClick={() => void handlePickPath(s.key)}
                title={hasPath ? dccPaths[s.key] : 'Définir le chemin…'}
                style={{
                  width: 16, height: 16, borderRadius: 4,
                  border: '1px solid ' + (hasPath ? 'var(--accent)' : 'var(--rule-2)'),
                  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                  flexShrink: 0,
                  background: hasPath ? 'var(--accent-soft)' : 'transparent',
                  color: hasPath ? 'var(--accent-hi)' : 'var(--ink-4)',
                  cursor: 'pointer',
                  transition: 'background 0.12s, border-color 0.12s',
                }}
              >
                <FolderOpen size={8} strokeWidth={2} />
              </div>

              {/* launch */}
              <div
                onClick={() => { if (!connected && !isLoading) void handleLaunch(s.key) }}
                title={connected ? 'Connecté' : isLoading ? 'Lancement…' : 'Lancer'}
                style={{
                  width: 16, height: 16, borderRadius: 4,
                  border: '1px solid ' + (connected ? 'var(--rule-2)' : isLoading ? 'var(--rule-2)' : 'var(--accent)'),
                  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                  flexShrink: 0,
                  background: connected ? 'var(--paper-2)' : isLoading ? 'var(--paper-2)' : 'var(--accent-soft)',
                  color: connected ? 'var(--ink-3)' : isLoading ? 'var(--ink-4)' : 'var(--accent-hi)',
                  boxShadow: 'var(--shadow-xs)',
                  cursor: connected || isLoading ? 'default' : 'pointer',
                  transition: 'background 0.12s, border-color 0.12s',
                }}
              >
                {isLoading
                  ? <Loader size={8} strokeWidth={2} style={{ animation: 'spin 1s linear infinite' }} />
                  : connected
                    ? <Settings2 size={8} strokeWidth={2} />
                    : <Play size={8} strokeWidth={2} />
                }
              </div>
            </div>
          )
        })}
      </NavGroup>

      <div style={{ flex: 1 }} />

      {/* Résultat de lancement — mini toast en bas */}
      {Object.entries(launchResult).map(([key, ok]) => {
        const name = SOFTWARE.find(s => s.key === key)?.name ?? key
        return (
          <div
            key={key}
            onClick={() => setLaunchResult(prev => { const n = { ...prev }; delete n[key]; return n })}
            style={{
              margin: '0 8px 6px',
              padding: '5px 8px',
              borderRadius: 5,
              border: `1px solid ${ok ? 'var(--ok)' : 'var(--err)'}`,
              background: ok ? 'color-mix(in oklch, var(--ok) 8%, transparent)' : 'color-mix(in oklch, var(--err) 8%, transparent)',
              fontSize: 10, fontFamily: 'var(--mono)',
              color: ok ? 'var(--ok)' : 'var(--err)',
              cursor: 'pointer',
            }}
          >
            {ok ? `✓ ${name} lancé` : `✗ ${name} — introuvable`}
          </div>
        )
      })}
    </div>
  )
}
