import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { toast } from 'sonner'
import {
  Home, Upload, Layers,
  BookOpen, FolderOpen, Activity,
  ChevronDown, ChevronRight,
  Play, Settings, Loader, Search, Plug, ArrowDownToLine, FilePlus2,
  ClipboardList, AlertTriangle, Check, X, CalendarDays, Pin, UserRound, RefreshCw,
} from 'lucide-react'
import type { DccStatusMap, Preset } from '../../types'
import { api } from '../../api/client'
import { useActiveInstances } from '../../hooks/useActiveInstances'
import { useEnabledDccs } from '../../hooks/useEnabledDccs'
import { DCC_STATUS_KEYS, SOFTWARE } from '../../lib/dccs'
import { useMentions } from '../../hooks/useMentions'
import { useProject } from '../../ProjectContext'
import { useI18n } from '../../i18n'
import { DccLogo } from './DccLogo'
import * as Menu from '@radix-ui/react-dropdown-menu'
import { openWorkProfile } from './WorkProfileDialog'

interface Props {
  dccStatus: DccStatusMap
  unreadCount: number
}


function dccDot(status: DccStatusMap, key: string): string {
  const entry = status[DCC_STATUS_KEYS[key] ?? key]
  if (!entry) return ''
  return entry.connected ? 'ok' : ''
}

// Drag a page out of the window (or right-click it) to open it in its own window (U4).
// The drop point is checked against the window rectangle: a drop inside does nothing.
function detachIfOutside(e: React.DragEvent, route: string) {
  const { screenX: x, screenY: y } = e
  if (x === 0 && y === 0) return      // cancelled drag (Escape)
  const inside = x >= window.screenX && x <= window.screenX + window.outerWidth
    && y >= window.screenY && y <= window.screenY + window.outerHeight
  if (!inside) window.electronAPI?.detachPage?.(route)
}

function NavItem({ icon: Icon, label, active, indent = false, notif = 0, notifRed = false, onClick, route }: {
  icon: React.ElementType; label: string; active?: boolean; indent?: boolean; notif?: number; notifRed?: boolean; onClick?: () => void
  route?: string
}) {
  const detachable = !!route && !!window.electronAPI?.detachPage
  return (
    <div
      className={`nav${active ? ' active' : ''}`}
      style={indent ? { paddingLeft: 24 } : {}}
      onClick={onClick}
      draggable={detachable}
      onDragStart={detachable ? (e => { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', route!) }) : undefined}
      onDragEnd={detachable ? (e => detachIfOutside(e, route!)) : undefined}
      onContextMenu={detachable ? (e => { e.preventDefault(); window.electronAPI?.detachPage?.(route!) }) : undefined}
      title={detachable ? 'Glisser hors de la fenetre ou clic droit : ouvrir dans une fenetre' : undefined}
    >
      <span className="glyph"><Icon size={13} strokeWidth={1.75} /></span>
      <span style={{ flex: 1 }}>{label}</span>
      {notif > 0 && (
        <span style={{
          minWidth: 17, height: 17, padding: '0 4px', borderRadius: 6,
          // Red badge for @mentions, accent badge for regular notifications.
          background: notifRed ? 'color-mix(in oklch, var(--err) 18%, transparent)' : 'var(--accent-soft)',
          border: '1px solid ' + (notifRed ? 'var(--err)' : 'var(--rule-3)'),
          color: notifRed ? 'var(--err)' : 'var(--accent-hi)',
          fontFamily: 'var(--sans)', fontSize: 10, fontWeight: 600,
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

const LS_PRODUCTION_PINNED = 'flux.sidebar.productionPinned'

export function Sidebar({ dccStatus, unreadCount }: Props) {
  const navigate = useNavigate()
  const { pathname, search } = useLocation()
  const [productionExpanded, setProductionExpanded] = useState(false)
  // Retake B1 (2026-10-09): pin only on Production, persisted per machine.
  const [productionPinned, setProductionPinned] = useState<boolean>(() => {
    try { return localStorage.getItem(LS_PRODUCTION_PINNED) === '1' } catch { return false }
  })
  const toggleProductionPinned = () => {
    setProductionPinned(prev => {
      const next = !prev
      try { localStorage.setItem(LS_PRODUCTION_PINNED, next ? '1' : '0') } catch { /* storage unavailable */ }
      return next
    })
  }
  const openingProduction = useRef(false)
  useEffect(() => {
    if (openingProduction.current) { openingProduction.current = false; return }
    // Unpinned: the group closes when leaving Production, never when moving inside it (Assets / Shots).
    if (!productionPinned && pathname !== '/production') setProductionExpanded(false)
  }, [pathname, search, productionPinned])
  const productionMode = new URLSearchParams(search).get('mode') ?? localStorage.getItem('flux.production.mode') ?? 'shot'
  const { unreadMentions } = useMentions()
  const { t } = useI18n()
  const { isEnabled: isDccEnabled } = useEnabledDccs()
  const [launcherMenu, setLauncherMenu] = useState<{ soft: string; x: number; y: number } | null>(null)
  const [launching, setLaunching]             = useState<Set<string>>(new Set())
  const [dccPaths, setDccPaths]               = useState<Record<string, string>>({})
  const [findingAll, setFindingAll]           = useState(false)
  const [findResult, setFindResult]           = useState<Record<string, boolean | null>>({})
  const [autostartInstalled, setAutostartInstalled] = useState<Record<string, boolean>>({})
  const [autostartLoading, setAutostartLoading]     = useState<Set<string>>(new Set())
  const [reapingMaya, setReapingMaya]               = useState(false)
  const [houdiniServerOk, setHoudiniServerOk]       = useState<boolean | null>(null)
  const [zbrushServerOk,  setZbrushServerOk]        = useState<boolean | null>(null)
  const [mayaServerOk,    setMayaServerOk]          = useState<boolean | null>(null)
  const [nukeServerOk,    setNukeServerOk]          = useState<boolean | null>(null)
  const [painterServerOk, setPainterServerOk]       = useState<boolean | null>(null)
  const [mariServerOk,    setMariServerOk]          = useState<boolean | null>(null)
  const [designerServerOk, setDesignerServerOk]     = useState<boolean | null>(null)
  const [marvelousServerOk, setMarvelousServerOk]   = useState<boolean | null>(null)
  const [unrealServerOk,  setUnrealServerOk]        = useState<boolean | null>(null)
  const [unrealBusy,      setUnrealBusy]            = useState(false)
  // Photoshop (COM, no plugin): reason drives the row control state.
  const [psReason, setPsReason]                     = useState<'ok' | 'lib_missing' | 'not_running' | null>(null)
  const [psBusy,   setPsBusy]                        = useState(false)

  // New Scene: the active project's presets drive the per-soft menu + button colour.
  const { project: activeProject } = useProject()
  const [presets, setPresets] = useState<Preset[]>([])

  // Multi-instance (cluster C): which instance each DCC targets. The selector row
  // control only appears when a DCC exposes more than one running instance.
  const { activePort, setActivePort } = useActiveInstances(dccStatus)

  // Close an instance: normal close first (the DCC may ask to save); if it stays,
  // the toast offers "Forcer" (kill, unsaved work lost).
  const closeInstance = useCallback(async (statusKey: string, name: string, port: number, force = false) => {
    const label = `${name} :${port}`
    try {
      const r = await api.closeDccInstance(statusKey, port, force)
      if (r.closed) { toast.success(`${label} ferme`); return }
      if (r.needs_force) {
        toast.warning(`${label} ne s'est pas ferme`, {
          description: "Une fenetre d'enregistrement est peut-etre ouverte dans le logiciel, ou la session n'a pas de fenetre. "
            + 'Forcer ferme sans enregistrer.',
          duration: 12000,
          action: { label: 'Forcer', onClick: () => { void closeInstance(statusKey, name, port, true) } },
        })
        return
      }
      toast.error(r.message, { duration: 8000 })
    } catch (e) {
      toast.error(`Fermeture de ${label} : ${e instanceof Error ? e.message : String(e)}`, { duration: 8000 })
    }
  }, [])
  const [instMenu, setInstMenu] = useState<{ statusKey: string; name: string; y: number } | null>(null)

  // Load the active project's presets (for button colour + menu), refresh on edits.
  useEffect(() => {
    if (!activeProject) { setPresets([]); return }
    let alive = true
    const loadPresets = () => {
      api.listPresets(activeProject, true)
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
    api.getDccAutostart('substance_painter').then(r => {
      setAutostartInstalled(prev => ({ ...prev, substance_painter: r.installed }))
      if (r.installed) {
        api.pingDcc('substance_painter').then(p => setPainterServerOk(p.connected)).catch(() => setPainterServerOk(false))
      }
    }).catch(() => {})
    api.getDccAutostart('mari').then(r => {
      setAutostartInstalled(prev => ({ ...prev, mari: r.installed }))
      if (r.installed) {
        api.pingDcc('mari').then(p => setMariServerOk(p.connected)).catch(() => setMariServerOk(false))
      }
    }).catch(() => {})
    api.getDccAutostart('substance_designer').then(r => {
      setAutostartInstalled(prev => ({ ...prev, substance_designer: r.installed }))
      if (r.installed) {
        api.pingDcc('substance_designer').then(p => setDesignerServerOk(p.connected)).catch(() => setDesignerServerOk(false))
      }
    }).catch(() => {})
    api.getDccAutostart('marvelous').then(r => {
      setAutostartInstalled(prev => ({ ...prev, marvelous: r.installed }))
      if (r.installed) {
        api.pingDcc('marvelous').then(p => setMarvelousServerOk(p.connected)).catch(() => setMarvelousServerOk(false))
      }
    }).catch(() => {})
    api.getDccAutostart('unreal').then(r => {
      setAutostartInstalled(prev => ({ ...prev, unreal: r.installed }))
      if (r.installed) {
        api.pingDcc('unreal').then(p => setUnrealServerOk(p.connected)).catch(() => setUnrealServerOk(false))
      }
    }).catch(() => {})
  }, [])

  // "Installer tous les bridges" (Settings) changed the bridges: refresh the plug icons.
  useEffect(() => {
    const onBridges = () => {
      for (const key of ['houdini', 'zbrush', 'maya', 'nuke', 'substance_painter', 'mari', 'substance_designer', 'marvelous', 'unreal']) {
        api.getDccAutostart(key)
          .then(r => setAutostartInstalled(prev => ({ ...prev, [key]: r.installed })))
          .catch(() => {})
      }
    }
    window.addEventListener('flux:bridges-changed', onBridges)
    return () => window.removeEventListener('flux:bridges-changed', onBridges)
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

  // Poll Painter bridge every 5 s when the plugin is installed
  useEffect(() => {
    if (!autostartInstalled.substance_painter) { setPainterServerOk(null); return }
    const poll = () =>
      api.pingDcc('substance_painter').then(p => setPainterServerOk(p.connected)).catch(() => setPainterServerOk(false))
    const id = setInterval(poll, 5000)
    return () => clearInterval(id)
  }, [autostartInstalled.substance_painter])

  // Poll Mari bridge every 5 s when the plugin is installed
  useEffect(() => {
    if (!autostartInstalled.mari) { setMariServerOk(null); return }
    const poll = () =>
      api.pingDcc('mari').then(p => setMariServerOk(p.connected)).catch(() => setMariServerOk(false))
    const id = setInterval(poll, 5000)
    return () => clearInterval(id)
  }, [autostartInstalled.mari])

  // Poll Designer bridge every 5 s when the plugin is installed
  useEffect(() => {
    if (!autostartInstalled.substance_designer) { setDesignerServerOk(null); return }
    const poll = () =>
      api.pingDcc('substance_designer').then(p => setDesignerServerOk(p.connected)).catch(() => setDesignerServerOk(false))
    const id = setInterval(poll, 5000)
    return () => clearInterval(id)
  }, [autostartInstalled.substance_designer])

  // Poll Marvelous bridge every 5 s when the script is written
  useEffect(() => {
    if (!autostartInstalled.marvelous) { setMarvelousServerOk(null); return }
    const poll = () =>
      api.pingDcc('marvelous').then(p => setMarvelousServerOk(p.connected)).catch(() => setMarvelousServerOk(false))
    const id = setInterval(poll, 5000)
    return () => clearInterval(id)
  }, [autostartInstalled.marvelous])

  // Poll the Unreal bridge every 5 s when the host project plugin is installed
  useEffect(() => {
    if (!autostartInstalled.unreal) { setUnrealServerOk(null); return }
    const poll = () =>
      api.pingDcc('unreal').then(p => setUnrealServerOk(p.connected)).catch(() => setUnrealServerOk(false))
    const id = setInterval(poll, 5000)
    return () => clearInterval(id)
  }, [autostartInstalled.unreal])

  // Poll Photoshop COM state every 5 s (no plugin; state = lib/running/ok).
  useEffect(() => {
    const poll = () =>
      api.photoshopStatus().then(s => setPsReason(s.reason)).catch(() => setPsReason(null))
    poll()
    const id = setInterval(poll, 5000)
    return () => clearInterval(id)
  }, [])

  // Photoshop control click: install the lib when missing, else refresh state.
  const handlePhotoshop = useCallback(async () => {
    if (psBusy) return
    setPsBusy(true)
    try {
      if (psReason === 'lib_missing') {
        const r = await api.photoshopInstall()
        if (r.ok) toast.success('photoshop-python-api installé')
        else toast.error(r.message)
      }
      const s = await api.photoshopStatus()
      setPsReason(s.reason)
      if (s.reason === 'ok') toast.success(`Photoshop connecté${s.version ? ` (${s.version})` : ''}`)
      else if (s.reason === 'not_running') toast('Ouvre Photoshop pour connecter')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Vérification Photoshop échouée')
    } finally {
      setPsBusy(false)
    }
  }, [psBusy, psReason])

  // Poll ZBrush bridge when plugin is installed, every 1.5s: the bridge answers pings
  // without touching ZBrush, and an Export FLUX click must open the Publisher quickly.
  const [zbrushPublishing, setZbrushPublishing] = useState(false)
  useEffect(() => {
    if (!autostartInstalled.zbrush) { setZbrushServerOk(null); setZbrushPublishing(false); return }
    let cancelled = false
    let timer: ReturnType<typeof setTimeout>
    const poll = () => {
      api.pingDcc('zbrush')
        .then(p  => { if (!cancelled) { setZbrushServerOk(p.connected); setZbrushPublishing(!!p.publishing) } })
        .catch(() => { if (!cancelled) { setZbrushServerOk(false); setZbrushPublishing(false) } })
        .finally(() => { if (!cancelled) timer = setTimeout(poll, 1500) })
    }
    poll()
    return () => { cancelled = true; clearTimeout(timer) }
  }, [autostartInstalled.zbrush])

  // Toast transition refs — undefined = initial render sentinel (no toast on first load)
  const prevHoudiniOkToast = useRef<boolean | null | undefined>(undefined)
  const prevZbrushOkToast  = useRef<boolean | null | undefined>(undefined)
  const prevMayaOkToast    = useRef<boolean | null | undefined>(undefined)

  // Auto-navigate to the Publisher (ZBrush selected) when Export FLUX is clicked in
  // ZBrush: the bridge answers "publishing" while it waits in its freeze loop.
  const prevZbrushPublishing = useRef(false)
  useEffect(() => {
    if (zbrushPublishing && !prevZbrushPublishing.current) {
      navigate('/publisher', { state: { zbrushConnected: true } })
    }
    prevZbrushPublishing.current = zbrushPublishing
  }, [zbrushPublishing, navigate])

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

  // "Installer tous les bridges" (2026-10-09), same endpoint as the Settings button.
  const [installingAll, setInstallingAll] = useState(false)
  const handleInstallAllBridges = async () => {
    setInstallingAll(true)
    try {
      const { results } = await api.installAllBridges()
      const count = (s: string) => results.filter(r => r.status === s).length
      const summary = t('settings.bridges.summary', { ok: count('ok'), skip: count('skip'), error: count('error') })
      if (count('error')) toast.error(summary)
      else toast.success(summary)
      window.dispatchEvent(new CustomEvent('flux:bridges-changed'))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setInstallingAll(false)
    }
  }

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
    if (key === 'substance_painter') setPainterServerOk(value)
    if (key === 'mari')    setMariServerOk(value)
    if (key === 'substance_designer') setDesignerServerOk(value)
    if (key === 'marvelous') setMarvelousServerOk(value)
    if (key === 'unreal')  setUnrealServerOk(value)
  }

  const PLUG_KEYS = ['houdini', 'zbrush', 'maya', 'nuke', 'substance_painter', 'mari', 'substance_designer', 'marvelous', 'unreal']

  const handleToggleAutostart = async (key: string) => {
    if (!PLUG_KEYS.includes(key)) return
    setAutostartLoading(prev => new Set(prev).add(key))
    try {
      if (autostartInstalled[key]) {
        await api.removeDccAutostart(key)
        setAutostartInstalled(prev => ({ ...prev, [key]: false }))
        _setServerOk(key, null)
      } else {
        await api.installDccAutostart(key)
        setAutostartInstalled(prev => ({ ...prev, [key]: true }))
        if (key === 'houdini') {
          toast.success('Plug Houdini installé', {
            description: 'Relance Houdini quand tu le souhaites pour charger le plug et les modifications. Ta session reste ouverte.',
            duration: 10000,
          })
        }
        // Ping to confirm the bridge already runs (the software may already be open).
        const name = SOFTWARE.find(x => x.key === key)?.name ?? key
        try {
          const pong = await api.pingDcc(key)
          _setServerOk(key, pong.connected)
          if (key !== 'houdini') toast.success(pong.connected ? `${name} · bridge connecté` : `${name} · bridge installé`, { duration: 3000 })
        } catch {
          _setServerOk(key, false)
          if (key !== 'houdini') toast.success(`${name} · bridge installé`, { duration: 3000 })
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

  // Before launching Maya, check for a stuck ("zombie") Maya still holding the
  // commandPort (port 7001). A close-before-ready or force-killed session can leave
  // a headless maya.exe holding the port so every new Maya fails to bind it. When
  // detected we don't launch silently — we ask first (a toast with a "close it &
  // launch" action), then reap and proceed. For non-Maya, or a free port, launch now.
  const guardMayaPort = async (key: string, proceed: () => Promise<void>): Promise<void> => {
    if (key !== 'maya') { await proceed(); return }
    let stuck = false
    try { stuck = (await api.getMayaPortStatus()).stuck } catch { stuck = false }
    if (!stuck) { await proceed(); return }
    toast.warning('Une instance Maya bloquée occupe le port 7001', {
      description: 'Ferme-la pour pouvoir lancer une nouvelle session Maya connectée à FLUX.',
      duration: 12000,
      action: {
        label: 'La fermer et lancer',
        onClick: () => { void (async () => {
          try {
            const r = await api.reapMayaPort()
            if (r.killed) { toast.success('Instance Maya bloquée fermée'); await proceed() }
            else toast.error('Impossible de fermer l’instance bloquée', { duration: 6000 })
          } catch { toast.error('Impossible de fermer l’instance bloquée', { duration: 6000 }) }
        })() },
      },
    })
  }

  // Reap a stuck Maya from the persistent row indicator (independent of any launch).
  // The status monitor surfaces `stuck` continuously, so this can be triggered even
  // when Maya was launched outside FLUX or the user never relaunches from here.
  const handleReapMaya = async (): Promise<void> => {
    if (reapingMaya) return
    setReapingMaya(true)
    try {
      const r = await api.reapMayaPort()
      if (r.killed) toast.success('Instance Maya bloquée fermée')
      else toast.error('Impossible de fermer l’instance bloquée', { duration: 6000 })
    } catch {
      toast.error('Impossible de fermer l’instance bloquée', { duration: 6000 })
    } finally {
      setReapingMaya(false)
    }
  }

  const handleLaunch = async (key: string) => {
    setLaunching(prev => new Set(prev).add(key))
    const name = SOFTWARE.find(s => s.key === key)?.name ?? key
    try {
      await guardMayaPort(key, async () => {
        const res = await api.launchDcc(key)
        if (res.launched) {
          toast.success(`${name} lancé`, { duration: 4000 })
        } else {
          toast.error(`${name} · introuvable`, { duration: 6000 })
        }
      })
    } catch {
      toast.error(`${name} · erreur de lancement`, { duration: 6000 })
    } finally {
      setLaunching(prev => { const next = new Set(prev); next.delete(key); return next })
    }
  }

  // Unreal (ADR 0052): the FLUX stage actor shows a shot stage; reload re-reads changed layers.
  const handleUnrealOpenStage = async () => {
    const path = await window.electronAPI?.openFile([{ name: 'USD', extensions: ['usd', 'usda', 'usdc'] }])
    if (!path) return
    setUnrealBusy(true)
    const pending = toast.loading('Unreal charge le stage…')
    try {
      const r = await api.unrealOpenStage(path)
      toast.success(`Stage ouvert dans Unreal (${r.seconds} s)`, { duration: 4000 })
    } catch (e) {
      toast.error(`Unreal · ${e instanceof Error ? e.message : String(e)}`, { duration: 8000 })
    } finally {
      toast.dismiss(pending)
      setUnrealBusy(false)
    }
  }

  const handleUnrealReload = async () => {
    setUnrealBusy(true)
    try {
      const r = await api.unrealReload()
      const count = r.changed?.length ?? 0
      toast.success(r.mode === 'full' ? `Stage rechargé en entier (${r.seconds} s)`
        : count ? `${count} layer(s) rechargé(s) (${r.seconds} s)` : 'Rien n’a changé sur le disque', { duration: 4000 })
    } catch (e) {
      toast.error(`Unreal · ${e instanceof Error ? e.message : String(e)}`, { duration: 8000 })
    } finally {
      setUnrealBusy(false)
    }
  }

  // Launch the chosen preset (or the empty default scene) in *soft*.
  const runNewScene = async (soft: string, preset: Preset | null) => {
    const name = SOFTWARE.find(s => s.key === soft)?.name ?? soft
    // A FLUX render preset whose scene is not on disk yet is built first (about a minute).
    const building = preset?.builtin && !preset.exists
      ? toast.loading(`Création de la scène ${preset.name}…`) : undefined
    try {
      await guardMayaPort(soft, async () => {
        const res = preset
          ? await api.launchPreset(activeProject, preset.id, soft)
          : await api.launchDcc(soft)
        if (res.launched) toast.success(`${name} lancé${preset ? ` · ${preset.name}` : ''}`, { duration: 4000 })
        else toast.error(`${name} · introuvable`, { duration: 6000 })
      })
    } catch (e) {
      toast.error(`${name} · ${e instanceof Error ? e.message : 'erreur de lancement'}`, { duration: 6000 })
    } finally {
      if (building !== undefined) toast.dismiss(building)
      if (preset?.builtin) window.dispatchEvent(new Event('flux:refresh'))
    }
  }

  // Everything a software offers, in one click menu (ADR 0044).
  const renderLauncherMenu = (soft: string) => {
    const name = SOFTWARE.find(x => x.key === soft)?.name ?? soft
    const statusKey = DCC_STATUS_KEYS[soft] ?? soft
    const connected = dccDot(dccStatus, soft) === 'ok'
    const installed = !!autostartInstalled[soft]
    const plugOk = installed && (soft === 'houdini' ? houdiniServerOk : soft === 'zbrush' ? zbrushServerOk : soft === 'maya' ? mayaServerOk
      : soft === 'nuke' ? nukeServerOk : soft === 'substance_painter' ? painterServerOk : soft === 'mari' ? mariServerOk
      : soft === 'substance_designer' ? designerServerOk : soft === 'marvelous' ? marvelousServerOk
      : soft === 'unreal' ? unrealServerOk : null) === true
    const instances = dccStatus[statusKey]?.instances ?? []
    const mayaStuck = soft === 'maya' && !!dccStatus[statusKey]?.stuck
    // New Scene: presets of the active project for this soft, grouped by TASK token.
    const linked = presets.filter(p => p.soft === soft && p.file)
    const groups = new Map<string, Preset[]>()
    for (const p of linked) {
      const key = (p.task ?? '').toUpperCase() || 'DEFAULT'
      groups.set(key, [...(groups.get(key) ?? []), p])
    }
    const tasks = [...groups.keys()].filter(k => k !== 'DEFAULT').sort()
    const presetItem = (p: Preset) => (
      <Menu.Item key={p.id} className="launcher-menu-item" title={p.file ?? ''} onSelect={() => void runNewScene(soft, p)}>
        <FilePlus2 size={13} />{p.name}
      </Menu.Item>
    )
    return <>
      <Menu.Label className="launcher-menu-label">{name}</Menu.Label>
      <Menu.Item className="launcher-menu-item launcher-menu-primary" disabled={launching.has(soft)} onSelect={() => void handleLaunch(soft)}>
        <Play size={13} fill="currentColor" />{connected ? 'Nouvelle instance' : 'Lancer'}
      </Menu.Item>
      {soft === 'unreal' && <>
        <Menu.Item className="launcher-menu-item" disabled={!connected || unrealBusy} onSelect={() => void handleUnrealOpenStage()}>
          <FolderOpen size={13} />Ouvrir un stage USD…<span className="launcher-menu-hint">{connected ? '' : 'Unreal fermé'}</span>
        </Menu.Item>
        <Menu.Item className="launcher-menu-item" disabled={!connected || unrealBusy} onSelect={() => void handleUnrealReload()}>
          <RefreshCw size={13} />Recharger le stage
        </Menu.Item>
      </>}
      {soft !== 'unreal' && <Menu.Sub>
        <Menu.SubTrigger className="launcher-menu-item" disabled={!activeProject}>
          <FilePlus2 size={13} />Nouvelle scène<span className="launcher-menu-hint">{activeProject ? '' : 'aucun projet'}</span><ChevronRight size={12} />
        </Menu.SubTrigger>
        <Menu.Portal>
          <Menu.SubContent className="launcher-menu" sideOffset={4} collisionPadding={10}>
            <Menu.Item className="launcher-menu-item" onSelect={() => void runNewScene(soft, null)}><Play size={13} />Scène vide</Menu.Item>
            {(groups.get('DEFAULT') ?? []).map(presetItem)}
            {tasks.map(task => (
              <Menu.Sub key={task}>
                <Menu.SubTrigger className="launcher-menu-item"><span className="launcher-menu-token">{task}</span><span style={{ flex: 1 }} /><ChevronRight size={12} /></Menu.SubTrigger>
                <Menu.Portal>
                  <Menu.SubContent className="launcher-menu" sideOffset={4} collisionPadding={10}>
                    {(groups.get(task) ?? []).map(presetItem)}
                  </Menu.SubContent>
                </Menu.Portal>
              </Menu.Sub>
            ))}
          </Menu.SubContent>
        </Menu.Portal>
      </Menu.Sub>}
      {instances.length > 1 && (
        <Menu.Item className="launcher-menu-item" onSelect={() => setInstMenu({ statusKey, name, y: launcherAnchorY(soft) })}>
          <Layers size={13} />Instances<span className="launcher-menu-hint">{instances.length} · port {activePort(statusKey) ?? '-'}</span>
        </Menu.Item>
      )}
      {mayaStuck && (
        <Menu.Item className="launcher-menu-item launcher-menu-danger" disabled={reapingMaya} onSelect={() => void handleReapMaya()}>
          <AlertTriangle size={13} />Fermer l'instance bloquée (port 7001)
        </Menu.Item>
      )}
      <Menu.Separator className="launcher-menu-separator" />
      <Menu.Item className="launcher-menu-item" onSelect={() => void handlePickPath(soft)} title={dccPaths[soft] ?? ''}>
        <FolderOpen size={13} />{dccPaths[soft] ? 'Changer le chemin…' : 'Définir le chemin…'}
        {!dccPaths[soft] && <span className="launcher-menu-hint warn">manquant</span>}
      </Menu.Item>
      {soft !== 'photoshop'
        ? <Menu.Item className="launcher-menu-item" disabled={autostartLoading.has(soft)} onSelect={() => void handleToggleAutostart(soft)}>
            <Plug size={13} />{installed ? 'Désinstaller le bridge' : 'Installer le bridge'}
            <span className="launcher-menu-hint">{installed ? (plugOk ? 'connecté' : 'en attente') : ''}</span>
          </Menu.Item>
        : <Menu.Item className="launcher-menu-item" disabled={psBusy} onSelect={() => void handlePhotoshop()}>
            {psReason === 'lib_missing' ? <ArrowDownToLine size={13} /> : <Plug size={13} />}
            {psReason === 'lib_missing' ? 'Installer photoshop-python-api' : 'Vérifier Photoshop'}
            <span className="launcher-menu-hint">{psReason === 'ok' ? 'connecté' : psReason === 'not_running' ? 'fermé' : ''}</span>
          </Menu.Item>}
      <Menu.Item className="launcher-menu-item" disabled={findingAll} onSelect={() => void handleAutoFindAll()}>
        <Search size={13} />Auto-détecter les chemins
      </Menu.Item>
      <Menu.Item className="launcher-menu-item" disabled={installingAll} onSelect={() => void handleInstallAllBridges()}>
        <Plug size={13} />{installingAll ? 'Installation des bridges…' : 'Installer tous les bridges'}
      </Menu.Item>
      <Menu.Separator className="launcher-menu-separator" />
      <Menu.Item className="launcher-menu-item" onSelect={openWorkProfile}><UserRound size={13} />Profil de travail…</Menu.Item>
    </>
  }

  // Vertical anchor of a launcher row (the instance picker opens next to it).
  const launcherAnchorY = (soft: string): number => {
    const el = document.querySelector(`[aria-label="${SOFTWARE.find(x => x.key === soft)?.name ?? soft} : actions"]`)
    return el ? el.getBoundingClientRect().top : window.innerHeight / 2
  }

  return (
    <div style={{
      width: 200, borderRight: '1px solid var(--rule)',
      background: 'var(--paper)',
      display: 'flex', flexDirection: 'column',
      flexShrink: 0,
    }}>
      <div style={{ padding: '10px 0 0' }}>
        <NavItem icon={Home} label={t('nav.home')} active={pathname === '/'} notif={unreadMentions} notifRed route="/" onClick={() => navigate('/')} />
      </div>

      {/* 2026-10-01: Production first, then the project folders, the team, the tools.
          Retake 08 (2026-10-08): the PIPELINE group sits above ASSETS. */}
      <NavGroup title="PIPELINE">
        <div className="production-nav-row">
          <NavItem icon={ClipboardList} label={t('nav.production')} active={pathname === '/production'} indent route="/production" onClick={() => { setProductionExpanded(v => !v); if (pathname !== '/production') { openingProduction.current = true; navigate('/production') } }} />
          <button className="production-nav-pin" aria-label={productionPinned ? t('nav.production.unpin') : t('nav.production.pin')} title={productionPinned ? t('nav.production.unpin') : t('nav.production.pin')} aria-pressed={productionPinned} onClick={() => { if (productionPinned && pathname !== '/production') setProductionExpanded(false); toggleProductionPinned() }}><Pin size={13} strokeWidth={1.75} fill={productionPinned ? 'currentColor' : 'none'} style={{ transform: 'rotate(45deg)' }} /></button>
        </div>
        {(productionPinned || productionExpanded) && <div className="production-nav-children" aria-label={t('nav.production.modes')}>{(['asset', 'shot'] as const).map(mode => <button key={mode} className={`nav production-mode${pathname === '/production' && productionMode === mode ? ' active' : ''}`} style={{ paddingLeft: 14, width: '100%', border: 0, textAlign: 'left' }} onClick={() => navigate(`/production?mode=${mode}`)}>{t(mode === 'asset' ? 'prod.mode.asset' : 'prod.mode.shot')}</button>)}</div>}
        <NavItem icon={FolderOpen} label={t('nav.folderManager')} active={pathname === '/projects'}  indent route="/projects" onClick={() => navigate('/projects')} />
        <NavItem icon={CalendarDays}   label={t('nav.calendar')}       active={pathname === '/calendar'}  indent route="/calendar" onClick={() => navigate('/calendar')} />
        <NavItem icon={Activity}       label={t('nav.activity')}       active={pathname === '/activity'}  indent notif={unreadCount} route="/activity" onClick={() => navigate('/activity')} />
      </NavGroup>

      <NavGroup title="ASSETS">
        <NavItem icon={Upload}     label={t('nav.publisher')}     active={pathname === '/publisher'} indent route="/publisher" onClick={() => navigate('/publisher')} />
        {/* Action engine test bench (Phase 2): route kept at /action-publish, hidden
            from the menu on purpose. It is NOT a replacement for the Publisher. */}
        <NavItem icon={Layers}     label={t('nav.usd')}  active={pathname === '/usd'}       indent route="/usd" onClick={() => navigate('/usd')} />
        <NavItem icon={BookOpen}       label={t('nav.shelfManager')}   active={pathname === '/shelf'}     indent route="/shelf" onClick={() => navigate('/shelf')} />
      </NavGroup>

      <NavGroup title="LAUNCHER">
        {/* ADR 0044: the official mark (accent) + one wide Play button. A click on Play opens
            every action of the software (launch, new scene, instances, path, bridge); nothing
            happens on hover. Only states to act on stay visible (flag on the button). */}
        {SOFTWARE.filter(s => isDccEnabled(s.key)).map(s => {
          const statusKey      = DCC_STATUS_KEYS[s.key] ?? s.key
          const connected      = dccDot(dccStatus, s.key) === 'ok'
          const isLoading      = launching.has(s.key)
          const hasPath        = !!dccPaths[s.key]
          const findOk         = findResult[s.key]
          const mayaStuck      = s.key === 'maya' && !!dccStatus[statusKey]?.stuck
          const instances      = dccStatus[statusKey]?.instances ?? []
          const statusBusy     = !!dccStatus[statusKey]?.busy
          const statusNoBridge = !!dccStatus[statusKey]?.no_bridge
          const state = mayaStuck ? 'err' : statusBusy || (statusNoBridge && !connected) ? 'warn' : connected ? 'ok' : ''
          const stateText = mayaStuck ? 'Instance bloquée sur le port 7001'
            : statusBusy ? 'Occupé (un export tourne)'
            : statusNoBridge && !connected ? 'Ouvert sans le bridge FLUX'
            : connected ? `Connecté${instances.length === 1 && instances[0].scene != null ? ` · ${instances[0].label}` : ''}`
            : 'Fermé'
          const flag = mayaStuck ? 'err' : (!hasPath || findOk === false) ? 'warn' : ''
          const open = launcherMenu?.soft === s.key
          return (
            <div key={s.key} className="dcc-row"
              onContextMenu={e => { e.preventDefault(); setLauncherMenu({ soft: s.key, x: e.clientX, y: e.clientY }) }}>
              <span className="dcc-logo-slot" title={`${s.name} · ${stateText}`} style={{ opacity: connected ? 1 : 0.62 }}>
                <DccLogo dcc={s.key} size={18} title={s.name} />
                {state && <span className={`dcc-state ${state}`} />}
              </span>
              {/* Launch = starts the software at once; the gear opens every other action. */}
              <button type="button" className={`dcc-play${connected ? ' live' : ''}`} disabled={isLoading}
                aria-label={`Lancer ${s.name}`} title={`${connected ? 'Nouvelle instance' : 'Lancer'} · ${stateText}`}
                onClick={() => void handleLaunch(s.key)}>
                {isLoading
                  ? <Loader size={11} strokeWidth={2} style={{ animation: 'spin 1s linear infinite' }} />
                  : <Play size={11} strokeWidth={2} fill="currentColor" />}
                {instances.length > 1 && <span className="dcc-count">×{instances.length}</span>}
              </button>
              <Menu.Root open={open} onOpenChange={o => setLauncherMenu(o ? { soft: s.key, x: 0, y: 0 } : null)} modal={false}>
                <Menu.Trigger asChild>
                  <button type="button" className="dcc-gear" aria-label={`${s.name} : actions`} title="Plus d'actions">
                    <Settings size={13} strokeWidth={1.8} />
                    {flag && <span className={`dcc-flag ${flag}`} />}
                  </button>
                </Menu.Trigger>
                <Menu.Portal>
                  <Menu.Content className="launcher-menu" side="right" align="start" sideOffset={6} collisionPadding={10}>
                    {renderLauncherMenu(s.key)}
                  </Menu.Content>
                </Menu.Portal>
              </Menu.Root>
            </div>
          )
        })}
      </NavGroup>

      <div style={{ flex: 1 }} />

      {/* Instance picker — choose which running instance of a DCC the pipeline targets,
          or close one (X: like the window's close button; "Forcer" only if it stays). */}
      {instMenu && (() => {
        const insts = dccStatus[instMenu.statusKey]?.instances ?? []
        const current = activePort(instMenu.statusKey)
        return (
          <>
            <div onClick={() => setInstMenu(null)} style={{ position: 'fixed', inset: 0, zIndex: 60 }} />
            <div style={{
              position: 'fixed', left: 8, bottom: Math.max(8, window.innerHeight - instMenu.y),
              width: 184, zIndex: 61, background: 'var(--paper-2)', border: '1px solid var(--rule-2)',
              borderRadius: 8, boxShadow: 'var(--shadow-md)', padding: 5,
            }}>
              <div style={{ padding: '4px 9px 6px', fontSize: 10.5, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--ink-4)' }}>
                Instance · {instMenu.name}
              </div>
              {insts.map((inst) => {
                const active = inst.port === current
                return (
                  <button
                    key={inst.id}
                    onClick={() => { setActivePort(instMenu.statusKey, inst.port); setInstMenu(null) }}
                    title={[inst.scene, inst.pid ? `pid ${inst.pid}` : ''].filter(Boolean).join(' · ')}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 8, width: '100%', textAlign: 'left',
                      padding: '6px 9px', borderRadius: 5, border: 'none', cursor: 'pointer',
                      fontSize: 11, fontFamily: 'var(--sans)',
                      background: active ? 'var(--accent-soft)' : 'transparent',
                      color: active ? 'var(--ink)' : 'var(--ink-2)',
                    }}
                    onMouseEnter={e => { if (!active) e.currentTarget.style.background = 'var(--accent-soft)' }}
                    onMouseLeave={e => { if (!active) e.currentTarget.style.background = 'transparent' }}
                  >
                    <span style={{ fontFamily: 'var(--mono)', fontSize: 10.5, color: 'var(--accent-hi)', flexShrink: 0 }}>
                      {inst.port}
                    </span>
                    <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {inst.scene != null ? inst.label : inst.pid ? `pid ${inst.pid}` : inst.label}
                      {inst.version && <span style={{ color: 'var(--ink-4)', fontSize: 10.5 }}> · {inst.version}</span>}
                    </span>
                    {inst.state === 'busy' && (
                      <span title="Occupé : un export tourne" style={{ fontSize: 10, color: 'var(--warn)', flexShrink: 0 }}>occupé</span>
                    )}
                    {active && <Check size={11} strokeWidth={2.5} color="var(--accent-hi)" style={{ flexShrink: 0 }} />}
                    <span
                      role="button"
                      title={`Fermer ${instMenu.name} :${inst.port}`}
                      onClick={e => { e.stopPropagation(); setInstMenu(null); void closeInstance(instMenu.statusKey, instMenu.name, inst.port) }}
                      style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: 16, height: 16,
                               borderRadius: 4, color: 'var(--ink-4)', flexShrink: 0 }}
                      onMouseEnter={e => { e.currentTarget.style.color = 'var(--err)'; e.currentTarget.style.background = 'var(--paper)' }}
                      onMouseLeave={e => { e.currentTarget.style.color = 'var(--ink-4)'; e.currentTarget.style.background = 'transparent' }}
                    >
                      <X size={10} strokeWidth={2.25} />
                    </span>
                  </button>
                )
              })}
            </div>
          </>
        )
      })()}
    </div>
  )
}
