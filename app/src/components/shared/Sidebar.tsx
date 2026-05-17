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
import { Tooltip, TooltipTrigger, TooltipContent } from './ui'

interface Props {
  dccStatus: DccStatusMap
  unreadCount: number
}

// Mapping frontend key → backend DCC_PORTS key (backend uses capitalized/abbreviated names)
const DCC_STATUS_KEYS: Record<string, string> = {
  maya:               'Maya',
  houdini:            'Houdini',
  nuke:               'Nuke',
  substance_painter:  'SubstanceP',
  substance_designer: 'SubstanceD',
  zbrush:             'ZBrush',
  marvelous:          'Marvelous',
  photoshop:          'Photoshop',
}

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
  const entry = status[DCC_STATUS_KEYS[key] ?? key]
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
  const [launching, setLaunching]             = useState<Set<string>>(new Set())
  const [launchResult, setLaunchResult]       = useState<Record<string, boolean>>({})
  const [dccPaths, setDccPaths]               = useState<Record<string, string>>({})
  const [findingAll, setFindingAll]           = useState(false)
  const [findResult, setFindResult]           = useState<Record<string, boolean | null>>({})
  const [autostartInstalled, setAutostartInstalled] = useState<Record<string, boolean>>({})
  const [autostartLoading, setAutostartLoading]     = useState<Set<string>>(new Set())
  const [autostartError, setAutostartError]         = useState<string | null>(null)
  const [pingResult, setPingResult]                 = useState<Record<string, string | null>>({})

  useEffect(() => {
    api.getSettings().then(s => setDccPaths(s.dcc_paths ?? {})).catch(() => {})
    api.getDccAutostart('houdini').then(r => setAutostartInstalled(prev => ({ ...prev, houdini: r.installed }))).catch(() => {})
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

  const handleToggleAutostart = async (key: string) => {
    if (key !== 'houdini') return
    setAutostartLoading(prev => new Set(prev).add(key))
    try {
      if (autostartInstalled[key]) {
        await api.removeDccAutostart(key)
        setAutostartInstalled(prev => ({ ...prev, [key]: false }))
      } else {
        await api.installDccAutostart(key)
        setAutostartInstalled(prev => ({ ...prev, [key]: true }))
        // Ping HTTP pour confirmer que flux_houdini_server tourne vraiment
        try {
          const pong = await api.pingDcc(key)
          const label = pong.connected
            ? (pong.version ? `v${pong.version}` : '✓')
            : '✗'
          setPingResult(prev => ({ ...prev, [key]: label }))
          setTimeout(() => setPingResult(prev => ({ ...prev, [key]: null })), 3000)
        } catch {
          setPingResult(prev => ({ ...prev, [key]: '✗' }))
          setTimeout(() => setPingResult(prev => ({ ...prev, [key]: null })), 3000)
        }
      }
    } catch (e) {
      setAutostartError(e instanceof Error ? e.message : String(e))
      setTimeout(() => setAutostartError(null), 5000)
    } finally {
      setAutostartLoading(prev => { const n = new Set(prev); n.delete(key); return n })
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
          const hasPath        = !!dccPaths[s.key]
          const findOk         = findResult[s.key]
          const isHoudini      = s.key === 'houdini'
          const autoInstalled  = !!autostartInstalled[s.key]
          const autoLoading    = autostartLoading.has(s.key)

          return (
            <div key={s.key} style={{
              display: 'flex', alignItems: 'center', gap: 4,
              padding: '5px 10px 5px 18px',
              fontSize: 11, color: connected ? 'var(--ink-2)' : 'var(--ink-4)',
            }}>
              <Tooltip>
                <TooltipTrigger asChild>
                  <span
                    className={`dot${connected ? ' ok' : ''}`}
                    style={{ width: 5, height: 5, flexShrink: 0 }}
                  />
                </TooltipTrigger>
                <TooltipContent side="top">
                  {connected ? 'Port local connecté' : 'Port local inactif'}
                </TooltipContent>
              </Tooltip>
              <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.name}</span>

              {/* feedback badge — hasPath permanent, puis find/ping éphémères */}
              {hasPath
                ? <span style={{ fontFamily: 'var(--mono)', fontSize: 8, color: 'var(--ok)' }}>✓</span>
                : findOk === false
                  ? <span style={{ fontFamily: 'var(--mono)', fontSize: 8, color: 'var(--err)' }}>✗</span>
                  : pingResult[s.key]
                    ? <span style={{ fontFamily: 'var(--mono)', fontSize: 8, color: pingResult[s.key] === '✗' ? 'var(--err)' : 'var(--ok)' }}>
                        {pingResult[s.key]}
                      </span>
                    : null
              }

              {/* path picker — indicateur visuel : accent = path défini */}
              <Tooltip>
                <TooltipTrigger asChild>
              <div
                onClick={() => void handlePickPath(s.key)}
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
                </TooltipTrigger>
                <TooltipContent side="top">
                  {hasPath ? dccPaths[s.key] : 'Définir le chemin…'}
                </TooltipContent>
              </Tooltip>

              {/* port local — autostart toggle (Houdini) ou placeholder */}
              <Tooltip>
                <TooltipTrigger asChild>
              <div
                onClick={() => { if (isHoudini && !autoLoading) void handleToggleAutostart(s.key) }}
                style={{
                  width: 16, height: 16, borderRadius: 4,
                  border: '1px solid ' + (isHoudini && autoInstalled ? 'var(--accent)' : 'var(--rule-2)'),
                  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                  flexShrink: 0,
                  background: isHoudini && autoInstalled ? 'var(--accent-soft)' : 'transparent',
                  color: isHoudini && autoInstalled ? 'var(--accent-hi)' : 'var(--ink-4)',
                  cursor: isHoudini ? (autoLoading ? 'default' : 'pointer') : 'not-allowed',
                  opacity: isHoudini ? 1 : 0.4,
                  transition: 'background 0.12s, border-color 0.12s, color 0.12s',
                }}
              >
                {autoLoading
                  ? <Loader size={8} strokeWidth={2} style={{ animation: 'spin 1s linear infinite' }} />
                  : <Plug size={8} strokeWidth={2} />
                }
              </div>
                </TooltipTrigger>
                <TooltipContent side="top">
                  {!isHoudini ? 'Connexion port local — prochainement' :
                   autoLoading ? '…' :
                   autoInstalled ? 'Autostart installé — clic pour désinstaller' :
                   "Installer l'autostart dans 123.py"}
                </TooltipContent>
              </Tooltip>

              {/* launch — toujours actif, relance une nouvelle instance si déjà connecté */}
              <Tooltip>
                <TooltipTrigger asChild>
              <div
                onClick={() => { if (!isLoading) void handleLaunch(s.key) }}
                style={{
                  width: 16, height: 16, borderRadius: 4,
                  border: '1px solid ' + (isLoading ? 'var(--rule-2)' : 'var(--accent)'),
                  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                  flexShrink: 0,
                  background: isLoading ? 'var(--paper-2)' : 'var(--accent-soft)',
                  color: isLoading ? 'var(--ink-4)' : 'var(--accent-hi)',
                  boxShadow: 'var(--shadow-xs)',
                  cursor: isLoading ? 'default' : 'pointer',
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
                </TooltipTrigger>
                <TooltipContent side="top">
                  {isLoading ? 'Lancement…' : connected ? 'Nouvelle instance' : 'Lancer'}
                </TooltipContent>
              </Tooltip>
            </div>
          )
        })}

        {/* Bouton global auto-détection des chemins */}
        <div style={{ padding: '5px 10px 6px' }}>
          <Tooltip>
            <TooltipTrigger asChild>
          <div
            onClick={() => { if (!findingAll) void handleAutoFindAll() }}
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
            </TooltipTrigger>
            <TooltipContent side="top">
              Détecter automatiquement tous les chemins .exe
            </TooltipContent>
          </Tooltip>
        </div>
      </NavGroup>

      <div style={{ flex: 1 }} />

      {/* Toast erreur autostart */}
      {autostartError && (
        <div
          onClick={() => setAutostartError(null)}
          style={{
            margin: '0 8px 6px',
            padding: '5px 8px',
            borderRadius: 5,
            border: '1px solid var(--err)',
            background: 'color-mix(in oklch, var(--err) 8%, transparent)',
            fontSize: 10, fontFamily: 'var(--mono)',
            color: 'var(--err)',
            cursor: 'pointer',
          }}
        >
          {`✗ Autostart — ${autostartError}`}
        </div>
      )}

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
