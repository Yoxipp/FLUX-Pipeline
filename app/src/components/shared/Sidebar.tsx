import { useState, useEffect, useRef } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { toast } from 'sonner'
import {
  Home, Upload, Download, Layers,
  BookOpen, FolderOpen, Activity,
  ChevronDown, ChevronRight,
  Play, Settings2, Loader, Search, Plug, ArrowDownToLine,
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
          fontFamily: 'var(--sans)', fontSize: 8, fontWeight: 600,
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
  const [dccPaths, setDccPaths]               = useState<Record<string, string>>({})
  const [findingAll, setFindingAll]           = useState(false)
  const [findResult, setFindResult]           = useState<Record<string, boolean | null>>({})
  const [autostartInstalled, setAutostartInstalled] = useState<Record<string, boolean>>({})
  const [autostartLoading, setAutostartLoading]     = useState<Set<string>>(new Set())
  const [pingResult, setPingResult]                 = useState<Record<string, string | null>>({})
  const [houdiniServerOk, setHoudiniServerOk]       = useState<boolean | null>(null)
  const [zbrushServerOk,  setZbrushServerOk]        = useState<boolean | null>(null)
  const [mayaServerOk,    setMayaServerOk]          = useState<boolean | null>(null)

  useEffect(() => {
    api.getSettings().then(s => setDccPaths(s.dcc_paths ?? {})).catch(() => {})
    api.getDccAutostart('houdini').then(r => {
      setAutostartInstalled(prev => ({ ...prev, houdini: r.installed }))
      if (r.installed) {
        api.pingDcc('houdini').then(p => setHoudiniServerOk(p.connected)).catch(() => setHoudiniServerOk(false))
      }
    }).catch(() => {})
    api.getDccAutostart('zbrush').then(r => {
      setAutostartInstalled(prev => ({ ...prev, zbrush: r.installed }))
      if (r.installed) {
        api.pingDcc('zbrush').then(p => setZbrushServerOk(p.connected)).catch(() => setZbrushServerOk(false))
      }
    }).catch(() => {})
    api.getDccAutostart('maya').then(r => {
      setAutostartInstalled(prev => ({ ...prev, maya: r.installed }))
      if (r.installed) {
        api.pingDcc('maya').then(p => setMayaServerOk(p.connected)).catch(() => setMayaServerOk(false))
      }
    }).catch(() => {})
  }, [])

  // Poll Houdini server every 5 s when autostart is installed
  useEffect(() => {
    if (!autostartInstalled.houdini) { setHoudiniServerOk(null); return }
    const poll = () =>
      api.pingDcc('houdini').then(p => setHoudiniServerOk(p.connected)).catch(() => setHoudiniServerOk(false))
    const id = setInterval(poll, 5000)
    return () => clearInterval(id)
  }, [autostartInstalled.houdini])

  // Poll Maya commandPort every 5 s when autostart is installed
  useEffect(() => {
    if (!autostartInstalled.maya) { setMayaServerOk(null); return }
    const poll = () =>
      api.pingDcc('maya').then(p => setMayaServerOk(p.connected)).catch(() => setMayaServerOk(false))
    const id = setInterval(poll, 5000)
    return () => clearInterval(id)
  }, [autostartInstalled.maya])

  // Poll ZBrush bridge when plugin is installed.
  // Uses recursive setTimeout so interval adapts: 1.5s while disconnected (< 2s T5 detection),
  // 8s while connected (avoid spamming ZBrush during freeze).
  const zbrushOkRef = useRef(zbrushServerOk)
  useEffect(() => { zbrushOkRef.current = zbrushServerOk }, [zbrushServerOk])
  useEffect(() => {
    if (!autostartInstalled.zbrush) { setZbrushServerOk(null); return }
    let cancelled = false
    let timer: ReturnType<typeof setTimeout>
    const poll = () => {
      api.pingDcc('zbrush')
        .then(p  => { if (!cancelled) setZbrushServerOk(p.connected) })
        .catch(() => { if (!cancelled) setZbrushServerOk(false) })
        .finally(() => {
          if (!cancelled) {
            const delay = zbrushOkRef.current === true ? 8000 : 1500
            timer = setTimeout(poll, delay)
          }
        })
    }
    poll()
    return () => { cancelled = true; clearTimeout(timer) }
  }, [autostartInstalled.zbrush])

  // Toast transition refs — undefined = initial render sentinel (no toast on first load)
  const prevHoudiniOkToast = useRef<boolean | null | undefined>(undefined)
  const prevZbrushOkToast  = useRef<boolean | null | undefined>(undefined)
  const prevMayaOkToast    = useRef<boolean | null | undefined>(undefined)

  // Auto-navigate to Publisher on ZBrush freeze detected (null/false → true transition)
  const prevZbrushOk = useRef<boolean | null>(null)
  useEffect(() => {
    if (zbrushServerOk === true && prevZbrushOk.current !== true) {
      if (pathname !== '/publisher') navigate('/publisher', { state: { zbrushConnected: true } })
    }
    prevZbrushOk.current = zbrushServerOk
  }, [zbrushServerOk, navigate, pathname])

  // Server status toasts — only on transitions, skip very first render
  useEffect(() => {
    const prev = prevHoudiniOkToast.current
    prevHoudiniOkToast.current = houdiniServerOk
    if (prev === undefined) return
    if (houdiniServerOk === false && prev !== false)
      toast.warning('Houdini — serveur non connecté. Rouvrir Houdini pour l\'activer.', { duration: 7000 })
    else if (houdiniServerOk === true && prev !== true)
      toast.success('Houdini — serveur connecté', { duration: 3000 })
  }, [houdiniServerOk]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const prev = prevZbrushOkToast.current
    prevZbrushOkToast.current = zbrushServerOk
    if (prev === undefined) return
    if (zbrushServerOk === false && prev !== false)
      toast.warning('ZBrush — bridge non connecté. Ouvrir ZBrush pour l\'activer.', { duration: 7000 })
    else if (zbrushServerOk === true && prev !== true)
      toast.success('ZBrush — bridge actif', { duration: 3000 })
  }, [zbrushServerOk]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const prev = prevMayaOkToast.current
    prevMayaOkToast.current = mayaServerOk
    if (prev === undefined) return
    if (mayaServerOk === false && prev !== false)
      toast.warning('Maya — commandPort non connecté. Rouvrir Maya pour l\'activer.', { duration: 7000 })
    else if (mayaServerOk === true && prev !== true)
      toast.success('Maya — commandPort connecté', { duration: 3000 })
  }, [mayaServerOk]) // eslint-disable-line react-hooks/exhaustive-deps

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

  const _setServerOk = (key: string, value: boolean | null) => {
    if (key === 'houdini') setHoudiniServerOk(value)
    if (key === 'zbrush')  setZbrushServerOk(value)
    if (key === 'maya')    setMayaServerOk(value)
  }

  const handleToggleAutostart = async (key: string) => {
    if (key !== 'houdini' && key !== 'zbrush' && key !== 'maya') return
    setAutostartLoading(prev => new Set(prev).add(key))
    try {
      if (autostartInstalled[key]) {
        await api.removeDccAutostart(key)
        setAutostartInstalled(prev => ({ ...prev, [key]: false }))
        _setServerOk(key, null)
      } else {
        await api.installDccAutostart(key)
        setAutostartInstalled(prev => ({ ...prev, [key]: true }))
        // Ping pour confirmer que le bridge tourne déjà (ZBrush peut-être déjà ouvert)
        try {
          const pong = await api.pingDcc(key)
          _setServerOk(key, pong.connected)
          const label = pong.connected
            ? (pong.version ? `v${pong.version}` : '✓')
            : '✗'
          setPingResult(prev => ({ ...prev, [key]: label }))
          setTimeout(() => setPingResult(prev => ({ ...prev, [key]: null })), 3000)
        } catch {
          _setServerOk(key, false)
          setPingResult(prev => ({ ...prev, [key]: '✗' }))
          setTimeout(() => setPingResult(prev => ({ ...prev, [key]: null })), 3000)
        }
      }
    } catch (e) {
      toast.error(`Autostart — ${e instanceof Error ? e.message : String(e)}`, { duration: 8000 })
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
    const name = SOFTWARE.find(s => s.key === key)?.name ?? key
    try {
      const res = await api.launchDcc(key)
      if (res.launched) {
        toast.success(`${name} lancé`, { duration: 4000 })
      } else {
        toast.error(`${name} — introuvable`, { duration: 6000 })
      }
    } catch {
      toast.error(`${name} — erreur de lancement`, { duration: 6000 })
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
          const isZBrush       = s.key === 'zbrush'
          const isMaya         = s.key === 'maya'
          const hasPlug        = isHoudini || isZBrush || isMaya
          const autoInstalled  = !!autostartInstalled[s.key]
          const autoLoading    = autostartLoading.has(s.key)
          const serverOk       = isHoudini ? houdiniServerOk : isZBrush ? zbrushServerOk : isMaya ? mayaServerOk : null
          // ZBrush: freeze-based, server only responds during publish → always accent when installed
          // Houdini/Maya: always-on server → red when installed but unreachable
          const plugOk         = hasPlug && autoInstalled && (isZBrush || serverOk === true)
          const plugFailed     = hasPlug && autoInstalled && !isZBrush && serverOk === false

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
                ? <span style={{ fontSize: 8, color: 'var(--ok)' }}>✓</span>
                : findOk === false
                  ? <span style={{ fontSize: 8, color: 'var(--err)' }}>✗</span>
                  : pingResult[s.key]
                    ? <span style={{ fontSize: 8, color: pingResult[s.key] === '✗' ? 'var(--err)' : 'var(--ok)' }}>
                        {pingResult[s.key]}
                      </span>
                    : null
              }

              {/* path picker — indicateur visuel : accent = path défini */}
              <Tooltip>
                <TooltipTrigger asChild>
              <div
                onClick={() => void handlePickPath(s.key)}
                className="scale-hover-lg"
                style={{
                  width: 16, height: 16, borderRadius: 4,
                  border: '1px solid ' + (hasPath ? 'var(--accent)' : 'var(--rule-2)'),
                  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                  flexShrink: 0,
                  background: hasPath ? 'var(--accent-soft)' : 'transparent',
                  color: hasPath ? 'var(--accent-hi)' : 'var(--ink-4)',
                  cursor: 'pointer',
                  transition: 'background 0.12s, border-color 0.12s, transform 0.12s',
                }}
              >
                <FolderOpen size={8} strokeWidth={2} />
              </div>
                </TooltipTrigger>
                <TooltipContent side="top">
                  {hasPath ? dccPaths[s.key] : 'Définir le chemin…'}
                </TooltipContent>
              </Tooltip>

              {/* port local — plugin/autostart toggle (Houdini + ZBrush) ou placeholder */}
              <Tooltip>
                <TooltipTrigger asChild>
              <div
                onClick={() => { if (hasPlug && !autoLoading) void handleToggleAutostart(s.key) }}
                className="scale-hover-lg"
                style={{
                  width: 16, height: 16, borderRadius: 4,
                  border: '1px solid ' + (plugOk ? 'var(--accent)' : plugFailed ? 'var(--err)' : 'var(--rule-2)'),
                  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                  flexShrink: 0,
                  background: plugOk ? 'var(--accent-soft)' : plugFailed ? 'color-mix(in oklch, var(--err) 8%, transparent)' : 'transparent',
                  color: plugOk ? 'var(--accent-hi)' : plugFailed ? 'var(--err)' : 'var(--ink-4)',
                  cursor: hasPlug ? (autoLoading ? 'default' : 'pointer') : 'not-allowed',
                  opacity: hasPlug ? 1 : 0.4,
                  transition: 'background 0.12s, border-color 0.12s, color 0.12s, transform 0.12s',
                }}
              >
                {autoLoading
                  ? <Loader size={8} strokeWidth={2} style={{ animation: 'spin 1s linear infinite' }} />
                  : isZBrush
                    ? <ArrowDownToLine size={8} strokeWidth={2} />
                    : <Plug size={8} strokeWidth={2} />
                }
              </div>
                </TooltipTrigger>
                <TooltipContent side="top">
                  {!hasPlug ? 'Connexion port local — prochainement' :
                   autoLoading ? '…' :
                   isHoudini
                     ? (autoInstalled ? 'Autostart installé — clic pour désinstaller' : "Installer l'autostart dans 123.py")
                   : isMaya
                     ? (autoInstalled
                         ? (serverOk === true ? 'Connecté — commandPort 7001 actif' : 'Autostart installé — clic pour désinstaller')
                         : 'Installer flux_bridge dans userSetup.py')
                     : (autoInstalled
                         ? (serverOk === true ? 'Freeze actif — publication en cours' : 'Plugin installé — clic pour désinstaller')
                         : 'Installer le plugin ZBrush')}
                </TooltipContent>
              </Tooltip>

              {/* launch — toujours actif, relance une nouvelle instance si déjà connecté */}
              <Tooltip>
                <TooltipTrigger asChild>
              <div
                onClick={() => { if (!isLoading) void handleLaunch(s.key) }}
                className="scale-hover-lg"
                style={{
                  width: 16, height: 16, borderRadius: 4,
                  border: '1px solid ' + (isLoading ? 'var(--rule-2)' : 'var(--accent)'),
                  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                  flexShrink: 0,
                  background: isLoading ? 'var(--paper-2)' : 'var(--accent-soft)',
                  color: isLoading ? 'var(--ink-4)' : 'var(--accent-hi)',
                  boxShadow: 'var(--shadow-xs)',
                  cursor: isLoading ? 'default' : 'pointer',
                  transition: 'background 0.12s, border-color 0.12s, transform 0.12s',
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
            className="scale-hover"
            style={{
              display: 'flex', alignItems: 'center', gap: 6,
              padding: '5px 8px',
              borderRadius: 5,
              border: '1px solid var(--rule-2)',
              background: 'var(--paper-2)',
              color: findingAll ? 'var(--ink-3)' : 'var(--ink-2)',
              cursor: findingAll ? 'default' : 'pointer',
              fontSize: 10, fontFamily: 'var(--sans)',
              transition: 'background 0.12s, border-color 0.12s, transform 0.12s',
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
    </div>
  )
}
