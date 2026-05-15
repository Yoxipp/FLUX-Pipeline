import { useState, useEffect } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import {
  Home, Upload, Download, Layers,
  BookOpen, FolderOpen, Activity,
  ChevronDown, ChevronRight,
  Play, Settings2, Loader, Search, Plug,
} from 'lucide-react'
import type { DccStatusMap } from '../../types'
import { api } from '../../api/client'

interface Props {
  dccStatus: DccStatusMap
  unreadCount: number
}

// Clés correspondant exactement aux DCC_PORTS du backend
const SOFTWARE = [
  { name: 'Maya',               key: 'maya' },
  { name: 'Houdini',            key: 'houdini' },
  { name: 'Nuke',               key: 'nuke' },
  { name: 'Substance Painter',  key: 'substance_painter' },
  { name: 'Substance Designer', key: 'substance_designer' },
  { name: 'ZBrush',             key: 'zbrush' },
  { name: 'Marvelous Designer', key: 'marvelous' },
  { name: 'Photoshop',          key: 'photoshop' },
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
  const [launching, setLaunching]       = useState<Set<string>>(new Set())
  const [launchResult, setLaunchResult] = useState<Record<string, boolean>>({})
  const [dccPaths, setDccPaths]         = useState<Record<string, string>>({})
  const [findingAll, setFindingAll]     = useState(false)
  const [findResult, setFindResult]     = useState<Record<string, boolean | null>>({})

  useEffect(() => {
    api.getSettings().then(s => setDccPaths(s.dcc_paths ?? {})).catch(() => {})
  }, [])

  const handleAutoFindAll = async () => {
    setFindingAll(true)
    await Promise.allSettled(
      SOFTWARE.map(async s => {
        try {
          const res = await api.findDccExe(s.key)
          if (res.found && res.path) {
            setDccPaths(prev => ({ ...prev, [s.key]: res.path! }))
            setFindResult(prev => ({ ...prev, [s.key]: true }))
          } else {
            setFindResult(prev => ({ ...prev, [s.key]: false }))
          }
        } catch {
          setFindResult(prev => ({ ...prev, [s.key]: false }))
        }
      })
    )
    setFindingAll(false)
    setTimeout(() => setFindResult({}), 3000)
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
          const hasPath   = !!dccPaths[s.key]
          const findOk    = findResult[s.key]

          return (
            <div key={s.key} style={{
              display: 'flex', alignItems: 'center', gap: 4,
              padding: '5px 10px 5px 18px',
              fontSize: 11, color: connected ? 'var(--ink-2)' : 'var(--ink-4)',
            }}>
              <span
                className={`dot${connected ? ' ok' : ''}`}
                title={connected ? 'Port local connecté' : 'Port local inactif'}
                style={{ width: 5, height: 5, flexShrink: 0 }}
              />
              <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.name}</span>

              {/* feedback auto-find */}
              {findOk === true  && <span style={{ fontFamily: 'var(--mono)', fontSize: 8, color: 'var(--ok)' }}>✓</span>}
              {findOk === false && <span style={{ fontFamily: 'var(--mono)', fontSize: 8, color: 'var(--err)' }}>✗</span>}

              {/* path picker — indicateur visuel : accent = path défini */}
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

              {/* port local — placeholder connexion (à implémenter) */}
              <div
                title={connected ? 'Connecté au port local' : 'Connexion port local — prochainement'}
                style={{
                  width: 16, height: 16, borderRadius: 4,
                  border: '1px solid ' + (connected ? 'var(--ok)' : 'var(--rule-2)'),
                  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                  flexShrink: 0,
                  background: connected ? 'color-mix(in oklch, var(--ok) 10%, transparent)' : 'transparent',
                  color: connected ? 'var(--ok)' : 'var(--ink-4)',
                  cursor: 'not-allowed',
                  opacity: connected ? 1 : 0.4,
                }}
              >
                <Plug size={8} strokeWidth={2} />
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

        {/* Bouton global auto-détection des chemins */}
        <div style={{ padding: '5px 10px 6px' }}>
          <div
            onClick={() => { if (!findingAll) void handleAutoFindAll() }}
            title="Détecter automatiquement tous les chemins .exe"
            style={{
              display: 'flex', alignItems: 'center', gap: 6,
              padding: '5px 8px',
              borderRadius: 5,
              border: '1px solid var(--rule-2)',
              background: 'var(--paper-2)',
              color: findingAll ? 'var(--ink-3)' : 'var(--ink-2)',
              cursor: findingAll ? 'default' : 'pointer',
              fontSize: 10, fontFamily: 'var(--mono)',
              transition: 'background 0.12s, border-color 0.12s',
            }}
          >
            {findingAll
              ? <Loader size={9} strokeWidth={2} style={{ animation: 'spin 1s linear infinite', flexShrink: 0 }} />
              : <Search size={9} strokeWidth={2} style={{ flexShrink: 0 }} />
            }
            <span>{findingAll ? 'Détection en cours…' : 'Auto-détecter les chemins'}</span>
          </div>
        </div>
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
