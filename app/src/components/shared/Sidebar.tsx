import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { toast } from 'sonner'
import {
  Home, Upload, Layers,
  BookOpen, FolderOpen, Activity,
  ChevronDown, ChevronRight,
  Play, Settings2, Loader, Search, Plug, ArrowDownToLine, LayoutTemplate, FilePlus2,
  ClipboardList, AlertTriangle, Check, X, HardDrive,
} from 'lucide-react'
import type { DccStatusMap, Preset } from '../../types'
import { api } from '../../api/client'
import { useActiveInstances } from '../../hooks/useActiveInstances'
import { useEnabledDccs } from '../../hooks/useEnabledDccs'
import { DCC_STATUS_KEYS, SOFTWARE } from '../../lib/dccs'
import { useMentions } from '../../hooks/useMentions'
import { useProject } from '../../ProjectContext'
import { useI18n } from '../../i18n'
import { Tooltip, TooltipTrigger, TooltipContent } from './ui'

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
  const { isEnabled: isDccEnabled } = useEnabledDccs()
  const [launching, setLaunching]             = useState<Set<string>>(new Set())
  const [dccPaths, setDccPaths]               = useState<Record<string, string>>({})
  const [findingAll, setFindingAll]           = useState(false)
  const [findResult, setFindResult]           = useState<Record<string, boolean | null>>({})
  const [autostartInstalled, setAutostartInstalled] = useState<Record<string, boolean>>({})
  const [autostartLoading, setAutostartLoading]     = useState<Set<string>>(new Set())
  const [reapingMaya, setReapingMaya]               = useState(false)
  const [pingResult, setPingResult]                 = useState<Record<string, string | null>>({})
  const [houdiniServerOk, setHoudiniServerOk]       = useState<boolean | null>(null)
  const [zbrushServerOk,  setZbrushServerOk]        = useState<boolean | null>(null)
  const [mayaServerOk,    setMayaServerOk]          = useState<boolean | null>(null)
  const [nukeServerOk,    setNukeServerOk]          = useState<boolean | null>(null)
  const [painterServerOk, setPainterServerOk]       = useState<boolean | null>(null)
  const [mariServerOk,    setMariServerOk]          = useState<boolean | null>(null)
  const [designerServerOk, setDesignerServerOk]     = useState<boolean | null>(null)
  const [marvelousServerOk, setMarvelousServerOk]   = useState<boolean | null>(null)
  // Photoshop (COM, no plugin): reason drives the row control state.
  const [psReason, setPsReason]                     = useState<'ok' | 'lib_missing' | 'not_running' | null>(null)
  const [psBusy,   setPsBusy]                        = useState(false)

  // New Scene: the active project's presets drive the per-soft menu + button colour.
  const { project: activeProject } = useProject()
  const [presets, setPresets] = useState<Preset[]>([])
  const [newScene, setNewScene] = useState<{ soft: string; x: number; y: number } | null>(null)
  const [hoverTask, setHoverTask] = useState<string | null>(null)

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
    if (key === 'substance_painter') setPainterServerOk(value)
    if (key === 'mari')    setMariServerOk(value)
    if (key === 'substance_designer') setDesignerServerOk(value)
    if (key === 'marvelous') setMarvelousServerOk(value)
  }

  const PLUG_KEYS = ['houdini', 'zbrush', 'maya', 'nuke', 'substance_painter', 'mari', 'substance_designer', 'marvelous']

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

      <NavGroup title="ASSETS">
        <NavItem icon={FolderOpen} label={t('nav.folderManager')} active={pathname === '/projects'}  indent route="/projects" onClick={() => navigate('/projects')} />
        <NavItem icon={Upload}     label={t('nav.publisher')}     active={pathname === '/publisher'} indent route="/publisher" onClick={() => navigate('/publisher')} />
        {/* Action engine test bench (Phase 2): route kept at /action-publish, hidden
            from the menu on purpose. It is NOT a replacement for the Publisher; it
            only proves the generic form + destination preview. Re-add when the rich
            Publisher's logic is wired through the engine. */}
        <NavItem icon={Layers}     label={t('nav.usd')}  active={pathname === '/usd'}       indent route="/usd" onClick={() => navigate('/usd')} />
      </NavGroup>

      <NavGroup title="PIPELINE">
        <NavItem icon={BookOpen}       label={t('nav.shelfManager')}   active={pathname === '/shelf'}     indent route="/shelf" onClick={() => navigate('/shelf')} />
        <NavItem icon={LayoutTemplate} label={t('nav.templateEditor')} active={pathname === '/templates'} indent route="/templates" onClick={() => navigate('/templates')} />
        <NavItem icon={ClipboardList}  label={t('nav.production')}     active={pathname === '/production'} indent route="/production" onClick={() => navigate('/production')} />
        <NavItem icon={Activity}       label={t('nav.activity')}       active={pathname === '/activity'}  indent notif={unreadCount} route="/activity" onClick={() => navigate('/activity')} />
        <NavItem icon={HardDrive}      label="Disque"                  active={pathname === '/disk'}       indent route="/disk" onClick={() => navigate('/disk')} />
      </NavGroup>

      <NavGroup title="LAUNCHER">
        {SOFTWARE.filter(s => isDccEnabled(s.key)).map(s => {
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
          const isPainter      = s.key === 'substance_painter'
          const isMari         = s.key === 'mari'
          const isDesigner     = s.key === 'substance_designer'
          const isMarvelous    = s.key === 'marvelous'
          const isPhotoshop    = s.key === 'photoshop'
          // Plug slot has two kinds: a 'toggle' installs/removes an in-app bridge
          // (Houdini/Maya/Nuke/ZBrush/Painter/Mari/Designer/Marvelous); Photoshop has no
          // plugin (external COM) so it shows a one-line hint instead.
          const hasPlug        = isHoudini || isZBrush || isMaya || isNuke || isPainter || isMari || isDesigner || isMarvelous
          const autoInstalled  = !!autostartInstalled[s.key]
          const autoLoading    = autostartLoading.has(s.key)
          const serverOk       = isHoudini ? houdiniServerOk : isZBrush ? zbrushServerOk : isMaya ? mayaServerOk : isNuke ? nukeServerOk : isPainter ? painterServerOk : isMari ? mariServerOk : isDesigner ? designerServerOk : isMarvelous ? marvelousServerOk : null
          // AutoStart state colors: ORANGE = autostart installed but the software isn't
          // launched/connected yet · GREEN = launched + connected. No red state anymore.
          const plugConnected  = hasPlug && autoInstalled && serverOk === true
          const plugWaiting    = hasPlug && autoInstalled && !plugConnected
          // Zombie Maya still holding the commandPort (continuous detection). Shown
          // as a persistent reap control on the Maya row, not just at launch time.
          const mayaStuck      = isMaya && !!dccStatus[DCC_STATUS_KEYS[s.key] ?? s.key]?.stuck
          // Multi-instance: running instances of this DCC + the one currently targeted.
          const statusKey      = DCC_STATUS_KEYS[s.key] ?? s.key
          const instances      = dccStatus[statusKey]?.instances ?? []
          const activeP        = activePort(statusKey)
          const statusBusy     = !!dccStatus[statusKey]?.busy
          const statusNoBridge = !!dccStatus[statusKey]?.no_bridge

          return (
            <div key={s.key} style={{
              display: 'flex', alignItems: 'center', gap: 4,
              padding: '5px 10px 5px 18px',
              fontSize: 11, color: connected ? 'var(--ink-2)' : 'var(--ink-4)',
            }}>
              <Tooltip>
                <TooltipTrigger asChild>
                  <span
                    className={`dot${statusBusy || statusNoBridge ? ' warn' : connected ? ' ok' : ''}`}
                    style={{ width: 5, height: 5, flexShrink: 0 }}
                  />
                </TooltipTrigger>
                <TooltipContent side="top">
                  {statusBusy ? 'Occupé (un export tourne) : il répondra quand il aura fini'
                    : statusNoBridge ? "Ouvert, mais le bridge FLUX ne tourne pas (installe l'autostart, puis relance le logiciel)"
                    : connected ? `Connecté${instances.length === 1 && instances[0].scene != null ? ` · ${instances[0].label}` : ''}`
                    : 'Fermé'}
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

              {/* port local — bridge toggle (Houdini/Maya/Nuke/ZBrush/Painter/Mari/Designer/Marvelous) */}
              {hasPlug && (
              <Tooltip>
                <TooltipTrigger asChild>
              <div
                onClick={() => { if (!autoLoading) void handleToggleAutostart(s.key) }}
                className="scale-hover-lg"
                style={{
                  width: 16, height: 16, borderRadius: 4,
                  border: '1px solid ' + (plugConnected ? 'var(--ok)' : plugWaiting ? '#e8912a' : 'var(--rule-2)'),
                  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                  flexShrink: 0,
                  background: plugConnected ? 'color-mix(in oklch, var(--ok) 12%, transparent)' : plugWaiting ? 'color-mix(in oklch, #e8912a 14%, transparent)' : 'transparent',
                  color: plugConnected ? 'var(--ok)' : plugWaiting ? '#e8912a' : 'var(--ink-4)',
                  cursor: autoLoading ? 'default' : 'pointer',
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
                  {autoLoading ? '…' :
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
                   : isPainter
                     ? (autoInstalled
                         ? (serverOk === true ? 'Connecté · bridge Painter' : 'Bridge installé · clic pour désinstaller')
                         : 'Installer le bridge Painter (dossier plugins)')
                   : isMari
                     ? (autoInstalled
                         ? (serverOk === true ? 'Connecté · bridge Mari' : 'Bridge installé · clic pour désinstaller')
                         : 'Installer le bridge Mari (dossier Scripts)')
                   : isDesigner
                     ? (autoInstalled
                         ? (serverOk === true ? 'Connecté · bridge Designer' : 'Bridge installé · clic pour désinstaller')
                         : 'Installer le bridge Designer (sduserplugins)')
                   : isMarvelous
                     ? (autoInstalled
                         ? (serverOk === true ? 'Connecté · bridge Marvelous' : 'Bridge installé · à lancer dans Marvelous (voir Publisher) · clic pour désinstaller')
                         : 'Installer le bridge Marvelous (menu Plugins > Plug-in, Marvelous fermé)')
                     : (autoInstalled
                         ? (serverOk === true ? 'Freeze actif · publication en cours' : 'Plugin installé · clic pour désinstaller')
                         : 'Installer le plugin ZBrush')}
                </TooltipContent>
              </Tooltip>
              )}

              {/* Photoshop — no in-app plugin (external COM). Actionable state:
                  GREEN = connected · ORANGE = lib present but PS not running ·
                  grey = lib missing (click installs it). */}
              {isPhotoshop && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <div
                    onClick={() => { if (!psBusy) void handlePhotoshop() }}
                    className="scale-hover-lg"
                    style={{
                      width: 16, height: 16, borderRadius: 4,
                      border: '1px solid ' + (psReason === 'ok' ? 'var(--ok)' : psReason === 'not_running' ? '#e8912a' : 'var(--rule-2)'),
                      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                      flexShrink: 0,
                      background: psReason === 'ok' ? 'color-mix(in oklch, var(--ok) 12%, transparent)' : psReason === 'not_running' ? 'color-mix(in oklch, #e8912a 14%, transparent)' : 'transparent',
                      color: psReason === 'ok' ? 'var(--ok)' : psReason === 'not_running' ? '#e8912a' : 'var(--ink-4)',
                      cursor: psBusy ? 'default' : 'pointer',
                      transition: 'background 0.12s, border-color 0.12s, color 0.12s, transform 0.12s',
                    }}
                  >
                    {psBusy
                      ? <Loader size={8} strokeWidth={2} style={{ animation: 'spin 1s linear infinite' }} />
                      : psReason === 'lib_missing'
                        ? <ArrowDownToLine size={8} strokeWidth={2} />
                        : <Plug size={8} strokeWidth={2} />
                    }
                  </div>
                </TooltipTrigger>
                <TooltipContent side="top">
                  {psBusy ? '…' :
                   psReason === 'ok' ? 'Photoshop connecté (COM)'
                   : psReason === 'not_running' ? 'Lib OK · ouvre Photoshop pour connecter'
                   : psReason === 'lib_missing' ? 'Clic : installer photoshop-python-api'
                   : 'Vérifier Photoshop'}
                </TooltipContent>
              </Tooltip>
              )}

              {/* zombie Maya — instance bloquée occupant le port 7001, reap au clic */}
              {mayaStuck && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <div
                      onClick={() => { if (!reapingMaya) void handleReapMaya() }}
                      className="scale-hover-lg"
                      style={{
                        width: 16, height: 16, borderRadius: 4,
                        border: '1px solid var(--err)',
                        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                        flexShrink: 0,
                        background: 'color-mix(in oklch, var(--err) 14%, transparent)',
                        color: 'var(--err)',
                        cursor: reapingMaya ? 'default' : 'pointer',
                        transition: 'background 0.12s, border-color 0.12s, transform 0.12s',
                      }}
                    >
                      {reapingMaya
                        ? <Loader size={8} strokeWidth={2} style={{ animation: 'spin 1s linear infinite' }} />
                        : <AlertTriangle size={8} strokeWidth={2} />
                      }
                    </div>
                  </TooltipTrigger>
                  <TooltipContent side="top">
                    {reapingMaya ? 'Fermeture…' : 'Instance Maya bloquée sur le port 7001 · cliquer pour la fermer'}
                  </TooltipContent>
                </Tooltip>
              )}

              {/* instance selector — visible seulement quand plusieurs instances tournent.
                  Affiche le nb d'instances ; clic ouvre le menu de choix de la cible. */}
              {instances.length > 1 && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <div
                      onClick={(e) => {
                        e.stopPropagation()
                        const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
                        setInstMenu(instMenu?.statusKey === statusKey ? null : { statusKey, name: s.name, y: rect.top })
                      }}
                      className="scale-hover-lg"
                      style={{
                        minWidth: 16, height: 16, padding: '0 3px', borderRadius: 4,
                        border: '1px solid var(--accent)',
                        display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 2,
                        flexShrink: 0,
                        background: 'var(--accent-soft)', color: 'var(--accent-hi)',
                        fontFamily: 'var(--mono)', fontSize: 8, fontWeight: 600, cursor: 'pointer',
                        transition: 'background 0.12s, border-color 0.12s, transform 0.12s',
                      }}
                    >
                      <Layers size={7} strokeWidth={2} />{instances.length}
                    </div>
                  </TooltipTrigger>
                  <TooltipContent side="top">
                    {instances.length} instances · cible : port {activeP ?? '—'}
                  </TooltipContent>
                </Tooltip>
              )}

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
              <div style={{ padding: '4px 9px 6px', fontSize: 9, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--ink-4)' }}>
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
                    <span style={{ fontFamily: 'var(--mono)', fontSize: 9, color: 'var(--accent-hi)', flexShrink: 0 }}>
                      {inst.port}
                    </span>
                    <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {inst.scene != null ? inst.label : inst.pid ? `pid ${inst.pid}` : inst.label}
                      {inst.version && <span style={{ color: 'var(--ink-4)', fontSize: 9 }}> · {inst.version}</span>}
                    </span>
                    {inst.state === 'busy' && (
                      <span title="Occupé : un export tourne" style={{ fontSize: 8, color: 'var(--warn)', flexShrink: 0 }}>occupé</span>
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
