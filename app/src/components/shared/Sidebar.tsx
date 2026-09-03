import { useState, useEffect, useRef } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { toast } from 'sonner'
import {
  Home, Upload, Layers,
  BookOpen, FolderOpen, Activity,
  ChevronDown, ChevronRight,
  Play, Settings2, Loader, Search, Plug, ArrowDownToLine, LayoutTemplate, FilePlus2,
  ClipboardList,
} from 'lucide-react'
import type { DccStatusMap, Preset } from '../../types'
import { api } from '../../api/client'
import { useMentions } from '../../hooks/useMentions'
import { useProject } from '../../ProjectContext'
import { useI18n } from '../../i18n'
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
  mari:               'Mari',
}

const SOFTWARE = [
  { name: 'Maya',      key: 'maya' },
  { name: 'Houdini',   key: 'houdini' },
  { name: 'Nuke',      key: 'nuke' },
  { name: 'Marvelous', key: 'marvelous' },
  { name: 'Painter',   key: 'substance_painter' },
  { name: 'Designer',  key: 'substance_designer' },
  { name: 'Mari',      key: 'mari' },
  { name: 'ZBrush',    key: 'zbrush' },
  { name: 'Photoshop', key: 'photoshop' },
]

function dccDot(status: DccStatusMap, key: string): string {
  const entry = status[DCC_STATUS_KEYS[key] ?? key]
  if (!entry) return ''
  return entry.connected ? 'ok' : ''
}

function NavItem({ icon: Icon, label, active, indent = false, notif = 0, notifRed = false, onClick }: {
  icon: React.ElementType; label: string; active?: boolean; indent?: boolean; notif?: number; notifRed?: boolean; onClick?: () => void
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
          // Red badge for @mentions, accent badge for regular notifications.
          background: notifRed ? 'color-mix(in oklch, var(--err) 18%, transparent)' : 'var(--accent-soft)',
          border: '1px solid ' + (notifRed ? 'var(--err)' : 'var(--accent)'),
          color: notifRed ? 'var(--err)' : 'var(--accent-hi)',
          fontFamily: 'var(--sans)', fontSize: 8, fontWeight: 600,
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          boxShadow: 'var(--shadow-xs)',
        }}>{notif}</span>
      )}
    </div>
  )
}

function NavGroup({ title, children, defaultOpen = true }: {
  title: string; children: React.ReactNode; defaultOpen?: boolean
}) {
  // Collapsed state is per-group and persisted so it survives navigation/reload.
  const lsKey = `flux.sidebar.group.${title}`
  const [open, setOpen] = useState<boolean>(() => {
    try {
      const v = localStorage.getItem(lsKey)
      if (v === 'open') return true
      if (v === 'closed') return false
    } catch { /* blocked storage */ }
    return defaultOpen
  })

  const toggle = () => {
    setOpen(prev => {
      const next = !prev
      try { localStorage.setItem(lsKey, next ? 'open' : 'closed') } catch { /* blocked */ }
      return next
    })
  }

  return (
    <div style={{ marginTop: 4 }}>
      <div
        onClick={toggle}
        style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 12px 3px', cursor: 'pointer', userSelect: 'none' }}
        title={open ? 'Replier' : 'Déplier'}
      >
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
  const { unreadMentions } = useMentions()
  const { t } = useI18n()
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
  const [nukeServerOk,    setNukeServerOk]          = useState<boolean | null>(null)

  // New Scene: the active project's presets drive the per-soft menu + button colour.
  const { project: activeProject } = useProject()
  const [presets, setPresets] = useState<Preset[]>([])
  const [newScene, setNewScene] = useState<{ soft: string; x: number; y: number } | null>(null)
  const [hoverTask, setHoverTask] = useState<string | null>(null)

  // Load the active project's presets (for button colour + menu), refresh on edits.
  useEffect(() => {
    if (!activeProject) { setPresets([]); return }
    let alive = true
    const loadPresets = () => {
      api.listPresets(activeProject)
        .then(d => { if (alive) setPresets(d.presets) })
        .catch(() => { if (alive) setPresets([]) })
    }
    loadPresets()
    const onRefresh = () => loadPresets()
    window.addEventListener('flux:refresh', onRefresh)
    return () => { alive = false; window.removeEventListener('flux:refresh', onRefresh) }
  }, [activeProject])

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
    api.getDccAutostart('nuke').then(r => {
      setAutostartInstalled(prev => ({ ...prev, nuke: r.installed }))
      if (r.installed) {
        api.pingDcc('nuke').then(p => setNukeServerOk(p.connected)).catch(() => setNukeServerOk(false))
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

  // Poll Nuke bridge every 5 s when autostart is installed
  useEffect(() => {
    if (!autostartInstalled.nuke) { setNukeServerOk(null); return }
    const poll = () =>
      api.pingDcc('nuke').then(p => setNukeServerOk(p.connected)).catch(() => setNukeServerOk(false))
    const id = setInterval(poll, 5000)
    return () => clearInterval(id)
  }, [autostartInstalled.nuke])

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
      toast.warning('Houdini · serveur non connecté. Rouvrir Houdini pour l\'activer.', { duration: 7000 })
    else if (houdiniServerOk === true && prev !== true)
      toast.success('Houdini · serveur connecté', { duration: 3000 })
  }, [houdiniServerOk]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const prev = prevZbrushOkToast.current
    prevZbrushOkToast.current = zbrushServerOk
    if (prev === undefined) return
    if (zbrushServerOk === false && prev !== false)
      toast.warning('ZBrush · bridge non connecté. Ouvrir ZBrush pour l\'activer.', { duration: 7000 })
    else if (zbrushServerOk === true && prev !== true)
      toast.success('ZBrush · bridge actif', { duration: 3000 })
  }, [zbrushServerOk]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const prev = prevMayaOkToast.current
    prevMayaOkToast.current = mayaServerOk
    if (prev === undefined) return
    if (mayaServerOk === false && prev !== false)
      toast.warning('Maya · commandPort non connecté. Rouvrir Maya pour l\'activer.', { duration: 7000 })
    else if (mayaServerOk === true && prev !== true)
      toast.success('Maya · commandPort connecté', { duration: 3000 })
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
    if (key === 'nuke')    setNukeServerOk(value)
  }

  const handleToggleAutostart = async (key: string) => {
    if (key !== 'houdini' && key !== 'zbrush' && key !== 'maya' && key !== 'nuke') return
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
      toast.error(`Autostart · ${e instanceof Error ? e.message : String(e)}`, { duration: 8000 })
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
        toast.error(`${name} · introuvable`, { duration: 6000 })
      }
    } catch {
      toast.error(`${name} · erreur de lancement`, { duration: 6000 })
    } finally {
      setLaunching(prev => { const next = new Set(prev); next.delete(key); return next })
    }
  }

  // ── New Scene ────────────────────────────────────────────────────────────────
  // Open the per-soft menu of tasks that have presets in the active project.
  const openNewScene = (soft: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (!activeProject) { toast.error('Aucun projet actif — choisis-en un dans le Folder Manager'); return }
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
    setHoverTask(null)
    setNewScene({ soft, x: rect.left, y: rect.top })
  }

  // Launch the chosen preset (or the empty default scene) in *soft*.
  const runNewScene = async (soft: string, preset: Preset | null) => {
    setNewScene(null)
    const name = SOFTWARE.find(s => s.key === soft)?.name ?? soft
    try {
      const res = preset
        ? await api.launchPreset(activeProject, preset.id, soft)
        : await api.launchDcc(soft)
      if (res.launched) toast.success(`${name} lancé${preset ? ` · ${preset.name}` : ''}`, { duration: 4000 })
      else toast.error(`${name} · introuvable`, { duration: 6000 })
    } catch {
      toast.error(`${name} · erreur de lancement`, { duration: 6000 })
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
        <NavItem icon={Home} label={t('nav.home')} active={pathname === '/'} notif={unreadMentions} notifRed onClick={() => navigate('/')} />
      </div>

      <NavGroup title="ASSETS">
        <NavItem icon={FolderOpen} label={t('nav.folderManager')} active={pathname === '/projects'}  indent onClick={() => navigate('/projects')} />
        <NavItem icon={Upload}     label={t('nav.publisher')}     active={pathname === '/publisher'} indent onClick={() => navigate('/publisher')} />
        <NavItem icon={Layers}     label={t('nav.usdAssembler')}  active={pathname === '/usd'}       indent onClick={() => navigate('/usd')} />
      </NavGroup>

      <NavGroup title="PIPELINE">
        <NavItem icon={BookOpen}       label={t('nav.shelfManager')}   active={pathname === '/shelf'}     indent onClick={() => navigate('/shelf')} />
        <NavItem icon={LayoutTemplate} label={t('nav.templateEditor')} active={pathname === '/templates'} indent onClick={() => navigate('/templates')} />
        <NavItem icon={ClipboardList}  label={t('nav.production')}     active={pathname === '/production'} indent onClick={() => navigate('/production')} />
        <NavItem icon={Activity}       label={t('nav.activity')}       active={pathname === '/activity'}  indent notif={unreadCount} onClick={() => navigate('/activity')} />
      </NavGroup>

      <NavGroup title="LAUNCHER">
        {SOFTWARE.map(s => {
          const dot       = dccDot(dccStatus, s.key)
          const connected = dot === 'ok'
          const isLoading = launching.has(s.key)
          const hasPreset      = presets.some(p => p.soft === s.key && p.file)
          const hasPath        = !!dccPaths[s.key]
          const findOk         = findResult[s.key]
          const isHoudini      = s.key === 'houdini'
          const isZBrush       = s.key === 'zbrush'
          const isMaya         = s.key === 'maya'
          const isNuke         = s.key === 'nuke'
          const hasPlug        = isHoudini || isZBrush || isMaya || isNuke
          const autoInstalled  = !!autostartInstalled[s.key]
          const autoLoading    = autostartLoading.has(s.key)
          const serverOk       = isHoudini ? houdiniServerOk : isZBrush ? zbrushServerOk : isMaya ? mayaServerOk : isNuke ? nukeServerOk : null
          // AutoStart state colors: ORANGE = autostart installed but the software isn't
          // launched/connected yet · GREEN = launched + connected. No red state anymore.
          const plugConnected  = hasPlug && autoInstalled && serverOk === true
          const plugWaiting    = hasPlug && autoInstalled && !plugConnected

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

              {/* feedback badge — find/ping éphémères (la coche verte permanente a été retirée) */}
              {findOk === false
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
                  border: '1px solid ' + (plugConnected ? 'var(--ok)' : plugWaiting ? '#e8912a' : 'var(--rule-2)'),
                  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                  flexShrink: 0,
                  background: plugConnected ? 'color-mix(in oklch, var(--ok) 12%, transparent)' : plugWaiting ? 'color-mix(in oklch, #e8912a 14%, transparent)' : 'transparent',
                  color: plugConnected ? 'var(--ok)' : plugWaiting ? '#e8912a' : 'var(--ink-4)',
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
                  {!hasPlug ? 'Connexion port local · prochainement' :
                   autoLoading ? '…' :
                   isHoudini
                     ? (autoInstalled ? 'Autostart installé · clic pour désinstaller' : "Installer l'autostart dans 123.py")
                   : isMaya
                     ? (autoInstalled
                         ? (serverOk === true ? 'Connecté · commandPort 7001 actif' : 'Autostart installé · clic pour désinstaller')
                         : 'Installer flux_bridge dans userSetup.py')
                   : isNuke
                     ? (autoInstalled
                         ? (serverOk === true ? 'Connecté · bridge Nuke 7003' : 'Autostart installé · clic pour désinstaller')
                         : 'Installer le bridge Nuke (init.py)')
                     : (autoInstalled
                         ? (serverOk === true ? 'Freeze actif · publication en cours' : 'Plugin installé · clic pour désinstaller')
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

              {/* New Scene — pick a task/preset (or default) to launch this soft with.
                  Accent-coloured as soon as this soft has at least one linked preset. */}
              <Tooltip>
                <TooltipTrigger asChild>
              <div
                onClick={(e) => openNewScene(s.key, e)}
                className="scale-hover-lg"
                style={{
                  width: 16, height: 16, borderRadius: 4,
                  border: '1px solid ' + (hasPreset ? 'var(--accent)' : 'var(--rule-2)'),
                  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                  flexShrink: 0,
                  background: hasPreset ? 'var(--accent-soft)' : 'transparent',
                  color: hasPreset ? 'var(--accent-hi)' : 'var(--ink-3)', cursor: 'pointer',
                  transition: 'background 0.12s, border-color 0.12s, color 0.12s, transform 0.12s',
                }}
              >
                <FilePlus2 size={9} strokeWidth={2} />
              </div>
                </TooltipTrigger>
                <TooltipContent side="top">New Scene</TooltipContent>
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

      {/* New Scene menu — one row per TASK token; hover a token to list its templates
          (like "Open In >" in the folder manager). DEFAULT also offers the empty scene. */}
      {newScene && (() => {
        const soft = newScene.soft
        const softName = SOFTWARE.find(s => s.key === soft)?.name ?? soft
        const linked = presets.filter(p => p.soft === soft && p.file)
        // Group linked presets by their TASK token (null → DEFAULT bucket).
        const groups = new Map<string, Preset[]>()
        for (const p of linked) {
          const key = (p.task ?? '').toUpperCase() || 'DEFAULT'
          groups.set(key, [...(groups.get(key) ?? []), p])
        }
        if (!groups.has('DEFAULT')) groups.set('DEFAULT', [])   // DEFAULT is always offered
        const tasks = ['DEFAULT', ...[...groups.keys()].filter(k => k !== 'DEFAULT').sort()]

        const row: React.CSSProperties = {
          display: 'flex', alignItems: 'center', gap: 8, width: '100%', textAlign: 'left',
          padding: '6px 9px', background: 'transparent', border: 'none',
          fontSize: 11, fontFamily: 'var(--sans)', cursor: 'pointer', borderRadius: 5,
        }
        const item: React.CSSProperties = { ...row, color: 'var(--ink-2)' }

        return (
          <>
            <div onClick={() => setNewScene(null)} style={{ position: 'fixed', inset: 0, zIndex: 60 }} />
            <div style={{
              position: 'fixed', left: 8, bottom: Math.max(8, window.innerHeight - newScene.y),
              width: 184, zIndex: 61, background: 'var(--paper-2)', border: '1px solid var(--rule-2)',
              borderRadius: 8, boxShadow: 'var(--shadow-md)', padding: 5,
            }}>
              <div style={{ padding: '4px 9px 6px', fontSize: 9, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--ink-4)' }}>
                New Scene · {softName}
              </div>
              {tasks.map(task => {
                const assigned = groups.get(task) ?? []
                const items: { label: string; preset: Preset | null }[] =
                  task === 'DEFAULT'
                    ? [{ label: 'Scène vide', preset: null }, ...assigned.map(p => ({ label: p.name, preset: p }))]
                    : assigned.map(p => ({ label: p.name, preset: p }))
                const open = hoverTask === task
                return (
                  <div
                    key={task}
                    style={{ position: 'relative' }}
                    onMouseEnter={() => setHoverTask(task)}
                    onMouseLeave={() => setHoverTask(h => (h === task ? null : h))}
                  >
                    <div style={{ ...row, background: open ? 'var(--accent-soft)' : 'transparent', color: open ? 'var(--ink)' : 'var(--ink-2)' }}>
                      <span style={{ fontFamily: 'var(--mono)', fontSize: 9, color: 'var(--accent-hi)', flexShrink: 0 }}>{task}</span>
                      <span style={{ flex: 1 }} />
                      <ChevronRight size={11} strokeWidth={2} color="var(--ink-4)" style={{ flexShrink: 0 }} />
                    </div>
                    {open && (
                      <div style={{
                        // Flush against the row (no gap) + a transparent left bridge so the
                        // pointer never crosses dead space between token and submenu.
                        position: 'absolute', left: '100%', top: -1, minWidth: 150, maxWidth: 240,
                        paddingLeft: 6, marginLeft: -2, zIndex: 62,
                      }}>
                        <div style={{
                          background: 'var(--paper-2)', border: '1px solid var(--rule-2)', borderRadius: 8,
                          boxShadow: 'var(--shadow-md)', padding: 5,
                        }}>
                        {items.map((it, i) => (
                          <button
                            key={i}
                            onClick={() => void runNewScene(soft, it.preset)}
                            title={it.preset?.file ?? ''}
                            style={item}
                            onMouseEnter={e => { e.currentTarget.style.background = 'var(--accent-soft)'; e.currentTarget.style.color = 'var(--ink)' }}
                            onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--ink-2)' }}
                          >
                            {it.preset
                              ? <FilePlus2 size={11} strokeWidth={2} color="var(--accent)" style={{ flexShrink: 0 }} />
                              : <Play size={10} strokeWidth={2} color="var(--ink-4)" style={{ flexShrink: 0 }} />}
                            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{it.label}</span>
                          </button>
                        ))}
                        </div>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </>
        )
      })()}
    </div>
  )
}
