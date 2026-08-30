import { useState, useEffect, useCallback, useRef } from 'react'
import { useLocation } from 'react-router-dom'
import { SoftwareSelector } from '../components/shared/SoftwareSelector'
import { Btn, SecTitle, FolderIcon, Select, SelectTrigger, SelectContent, SelectItem } from '../components/shared/ui'
import { api } from '../api/client'
import { useSettings } from '../hooks/useSettings'
import { toast } from 'sonner'

// ── Utilities ────────────────────────────────────────────────────────────────

/** Click-to-copy monospaced command block. */
function CopyBlock({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <div
      onClick={() => {
        void navigator.clipboard.writeText(text)
        setCopied(true)
        setTimeout(() => setCopied(false), 2000)
      }}
      title="Cliquer pour copier"
      style={{
        fontFamily: 'var(--mono)', fontSize: 8,
        color: copied ? 'var(--ok)' : 'var(--accent-hi)',
        background: 'var(--bg-deep)', border: `1px solid ${copied ? 'var(--ok)' : 'var(--rule-2)'}`,
        borderRadius: 4, padding: '5px 8px', cursor: 'pointer',
        wordBreak: 'break-all', lineHeight: 1.6, userSelect: 'all',
        transition: 'color 0.2s, border-color 0.2s',
      }}
    >
      {copied ? '✓ Copié !' : text}
    </div>
  )
}

function formatToken(raw: string): string {
  return raw
    .normalize('NFD').replace(/\p{Mn}/gu, '')
    .toUpperCase()
    .replace(/[\s-]/g, '_')
    .replace(/[^A-Z0-9_]/g, '')
    .replace(/_+/g, '_')
    .replace(/^_|_$/g, '')
}

function formatSeqLabel(raw: string): string {
  const n = parseInt(raw.replace(/[^0-9]/g, ''), 10)
  if (isNaN(n)) return raw.toUpperCase()
  return `SEQ${String(n).padStart(3, '0')}`
}

function formatShotLabel(raw: string): string {
  const n = parseInt(raw.replace(/[^0-9]/g, ''), 10)
  if (isNaN(n)) return raw.toUpperCase()
  return `SHOT${String(n).padStart(3, '0')}`
}

// Houdini ROP node type → export extension.
// Keys are lowercased; lookup normalises raw type names (strips ::version suffix, lowercases).
const NODE_TYPE_TO_EXT: Record<string, string> = {
  // Geometry
  rop_geometry:           '.bgeo',
  geometry:               '.bgeo',
  filecache:              '.bgeo',
  // Alembic
  rop_alembic:            '.abc',
  alembic:                '.abc',
  // USD
  usdexport:              '.usd',
  usd_rop:                '.usd',
  usdrender:              '.usd',
  lopnet:                 '.usd',
  // Renders
  ifd:                    '.exr',
  karma:                  '.exr',
  karma_rop:              '.exr',
  karma_old:              '.exr',
  opengl:                 '.exr',
  rop_comp:               '.exr',
  rop_opengl:             '.exr',
  // FBX
  filmboxcharacterimport: '.fbx',
  rop_fbx:                '.fbx',
  // HIP
  rop_hip:                '.hip',
}

function resolveNodeExt(rawType: string): string | undefined {
  // Strip namespace (Driver/) and version suffix (::2), lowercase
  const normalised = rawType.split('/').pop()!.split('::')[0].toLowerCase()
  return NODE_TYPE_TO_EXT[normalised]
}

// Export formats offered per software — only what each DCC can actually write.
// USD comes in three flavours: .usd (auto), .usda (ascii), .usdc (binary crate).
const USD_FORMATS = ['.usd', '.usda', '.usdc']

const EXPORT_FORMATS_BY_DCC: Record<string, string[]> = {
  Maya:           ['.abc', '.fbx', '.obj', '.ma', '.mb', ...USD_FORMATS],
  Houdini:        ['.abc', '.bgeo', '.vdb', '.obj', '.fbx', '.exr', '.hip', ...USD_FORMATS],
  Nuke:           ['.exr', '.dpx', '.tif', '.png', '.mov', '.nk'],
  'Substance P.': ['.png', '.exr', '.tga', '.tif', '.jpg'],
  ZBrush:         ['.ztl', '.obj', '.fbx'],
  Marvelous:      ['.obj', '.fbx', '.abc', '.zprj'],
  Photoshop:      ['.psd', '.png', '.tif', '.jpg', '.exr'],
}

// Fallback (e.g. "Fichier local"): a broad, DCC-agnostic superset.
const DEFAULT_EXPORT_FORMATS = ['.abc', '.fbx', '.obj', '.exr', '.png', '.tif', ...USD_FORMATS]

function formatsForDcc(dcc: string): string[] {
  return EXPORT_FORMATS_BY_DCC[dcc] ?? DEFAULT_EXPORT_FORMATS
}

// ── Types ─────────────────────────────────────────────────────────────────────

type PublishMode = 'asset' | 'shot'

interface ComposerSel {
  [key: string]: string
  class: string
  type: string
  name: string
  seq: string
  shot: string
  instance: string
}

const EMPTY_SEL: ComposerSel = { class: '', type: '', name: '', seq: '', shot: '', instance: 'null' }
const EMPTY_NEW_MODE = { type: false, name: false, instance: false, seq: false, shot: false }
const EMPTY_NEW_VALS = { type: '', name: '', instance: '', seq: '', shot: '' }

// ── PublishComposer ───────────────────────────────────────────────────────────

interface ComposerProps {
  project:   string
  tokens:    Record<string, Record<string, string>>
  seqs:      string[]
  shots:     string[]
  mode:      PublishMode
  sel:       ComposerSel
  newMode:   Record<string, boolean>
  newVals:   Record<string, string>
  onModeSwitch: () => void
  onSelect:     (key: string, value: string) => void
  onNewToggle:  (key: string) => void
  onNewVal:     (key: string, value: string) => void
}

interface Mod { key: string; label: string; opts: string[]; allowNew: boolean }

function PublishComposer({
  project, tokens, seqs, shots,
  mode, sel, newMode, newVals,
  onModeSwitch, onSelect, onNewToggle, onNewVal,
}: ComposerProps) {
  const [open, setOpen] = useState<string | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)

  const assetClasses  = Object.keys(tokens.CLASS ?? {}).filter(k => !(tokens.CLASS?.[k] ?? '').includes('{seq}'))
  const shotClassNames = Object.keys(tokens.CLASS ?? {}).filter(k =>  (tokens.CLASS?.[k] ?? '').includes('{seq}'))
  const typeKeys      = Object.keys(tokens.TYPE ?? {})
  const instanceKeys  = ['null', ...Object.keys(tokens.INSTANCE ?? {})]

  // Filter NAME tokens to only those belonging to the selected CLASS
  const classPath = (tokens.CLASS?.[sel.class] ?? '').replace(/\\/g, '/')
  const nameKeys = classPath
    ? Object.keys(tokens.NAME ?? {}).filter(k => {
        const rel = (tokens.NAME?.[k] ?? '').replace(/\\/g, '/')
        return rel.startsWith(classPath + '/')
      })
    : Object.keys(tokens.NAME ?? {})

  useEffect(() => {
    if (open === null) return
    const h = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(null)
    }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [open])

  const MODULES: Mod[] = mode === 'asset'
    ? [
        { key: 'class',    label: 'CLASS',    opts: assetClasses, allowNew: false },
        { key: 'type',     label: 'TYPE',     opts: typeKeys,     allowNew: false },
        { key: 'name',     label: 'NAME',     opts: nameKeys,     allowNew: true  },
        { key: 'instance', label: 'INSTANCE', opts: instanceKeys, allowNew: true  },
      ]
    : [
        { key: 'seq',      label: 'SEQ',      opts: seqs,           allowNew: true  },
        { key: 'shot',     label: 'SHOT',     opts: shots,          allowNew: true  },
        { key: 'name',     label: 'NAME',     opts: shotClassNames, allowNew: false },
        { key: 'instance', label: 'INSTANCE', opts: instanceKeys,   allowNew: true  },
      ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
      {/* NEW buttons row */}
      <div style={{ display: 'flex', gap: 4 }}>
        <div style={{ width: 56, flexShrink: 0 }} />
        <div style={{ flex: 1, display: 'flex' }}>
          {MODULES.map((m) => (
            <div key={m.key} style={{ flex: 1, display: 'flex', justifyContent: 'center' }}>
              {m.allowNew ? (
                <div
                  onClick={() => onNewToggle(m.key)}
                  style={{
                    padding: '2px 9px', borderRadius: 4,
                    fontSize: 8, fontFamily: 'var(--mono)', fontWeight: 700,
                    letterSpacing: '0.12em', cursor: 'pointer', userSelect: 'none',
                    background: newMode[m.key] ? 'var(--accent)' : 'transparent',
                    border: `1px solid ${newMode[m.key] ? 'var(--accent)' : 'var(--rule-2)'}`,
                    color: newMode[m.key] ? 'white' : 'var(--ink-4)',
                    transition: 'all 0.1s',
                  }}
                >
                  NEW
                </div>
              ) : (
                <div style={{ height: 20 }} />
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Composer bar */}
      <div style={{ display: 'flex', alignItems: 'stretch', gap: 4 }}>
        {/* Asset / Shot toggle */}
        <div
          onClick={onModeSwitch}
          className="scale-hover"
          style={{
            width: 52, flexShrink: 0, height: 34,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            border: '1px solid var(--rule-2)', borderRadius: 5,
            background: mode === 'shot' ? 'var(--accent-soft)' : 'var(--bg-deep)',
            cursor: 'pointer', fontSize: 8, fontFamily: 'var(--mono)',
            color: mode === 'shot' ? 'var(--accent-hi)' : 'var(--ink-3)',
            fontWeight: 700, letterSpacing: '0.08em', userSelect: 'none',
            boxShadow: 'var(--shadow-xs)', transition: 'all 0.12s',
          }}
        >
          {mode === 'asset' ? 'ASSET' : 'SHOT'}
        </div>

        {/* Token boxes */}
        <div
          ref={rootRef}
          style={{
            flex: 1, display: 'flex',
            border: '1px solid var(--rule-2)', borderRadius: 5,
            background: 'var(--bg-deep)', boxShadow: 'var(--shadow-inset)',
            position: 'relative', overflow: 'visible',
          }}
        >
          {MODULES.map(({ key, label, opts }, i) => {
            const selVal = sel[key]
            const isNew  = !!newMode[key]
            const isOpen = open === key && !isNew
            const filled = isNew ? !!newVals[key] : (!!selVal && selVal !== '')
            const radius = i === 0 ? '4px 0 0 4px' : i === MODULES.length - 1 ? '0 4px 4px 0' : '0'

            return (
              <div
                key={`${mode}-${key}`}
                style={{ flex: 1, position: 'relative', borderLeft: i > 0 ? '1px solid var(--rule-2)' : 'none' }}
              >
                {isNew ? (
                  <div style={{
                    height: 34, padding: '0 7px',
                    display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 1,
                    background: 'var(--accent-soft)', borderRadius: radius,
                    border: '1px solid var(--accent)', margin: -1, boxSizing: 'border-box',
                  }}>
                    <span style={{ fontSize: 7, color: 'var(--accent-hi)', textTransform: 'uppercase', letterSpacing: '0.1em', lineHeight: 1 }}>
                      {label}
                    </span>
                    <input
                      autoFocus
                      value={newVals[key]}
                      onChange={e => onNewVal(key, e.target.value)}
                      placeholder="nouveau…"
                      onClick={e => e.stopPropagation()}
                      style={{
                        background: 'transparent', border: 'none', outline: 'none',
                        fontFamily: 'var(--mono)', fontSize: 9, fontWeight: 700,
                        color: 'var(--accent-hi)', width: '100%', padding: 0,
                      }}
                    />
                  </div>
                ) : (
                  <div
                    onClick={() => setOpen(isOpen ? null : key)}
                    className="scale-hover"
                    style={{
                      height: 34, padding: '0 6px',
                      display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 1,
                      cursor: 'pointer',
                      background: filled ? 'var(--accent-soft)' : 'transparent',
                      transition: 'background 0.08s, transform 0.08s', borderRadius: radius,
                    }}
                  >
                    <span style={{ fontSize: 7, color: 'var(--ink-4)', textTransform: 'uppercase', letterSpacing: '0.1em', lineHeight: 1 }}>
                      {label}
                    </span>
                    <span style={{
                      fontSize: 9, fontFamily: 'var(--mono)',
                      color: filled ? 'var(--accent-hi)' : 'var(--ink-4)',
                      fontWeight: filled ? 600 : 400,
                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', lineHeight: 1.3,
                    }}>
                      {selVal || '-'}
                    </span>
                  </div>
                )}

                {isOpen && (
                  <div style={{
                    position: 'absolute', top: 'calc(100% + 4px)', left: 0, zIndex: 500,
                    minWidth: 120, background: 'var(--paper)',
                    border: '1px solid var(--rule-2)', borderRadius: 5,
                    boxShadow: 'var(--shadow)', overflow: 'hidden',
                  }}>
                    {selVal && key !== 'instance' && (
                      <div
                        onClick={() => { onSelect(key, ''); setOpen(null) }}
                        style={{ padding: '5px 8px', fontSize: 9, fontFamily: 'var(--mono)', color: 'var(--ink-4)', borderBottom: '1px solid var(--rule)', cursor: 'pointer' }}
                      >
                        effacer
                      </div>
                    )}
                    {opts.length === 0 ? (
                      <div style={{ padding: '7px 8px', fontSize: 9, color: 'var(--ink-4)', fontStyle: 'italic' }}>
                        {key === 'name' && !sel.class
                          ? 'Sélectionne une CLASS'
                          : project ? 'Vide' : 'Projet requis'}
                      </div>
                    ) : opts.map(o => (
                      <div
                        key={o}
                        onClick={() => { onSelect(key, o); setOpen(null) }}
                        style={{
                          padding: '5px 8px', fontSize: 9, fontFamily: 'var(--mono)',
                          color: selVal === o ? 'var(--accent-hi)' : 'var(--ink-2)',
                          background: selVal === o ? 'var(--accent-soft)' : 'transparent',
                          cursor: 'pointer', whiteSpace: 'nowrap',
                        }}
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
      </div>
    </div>
  )
}

// ── Publisher ─────────────────────────────────────────────────────────────────

export function Publisher() {
  const { settings } = useSettings()
  const location = useLocation()
  const [dcc, setDcc]           = useState('Maya')
  const [projects, setProjects] = useState<string[]>([])
  const [project, setProject]   = useState('')
  const [tokens, setTokens]     = useState<Record<string, Record<string, string>>>({})

  // Composer state
  const [mode, setMode]       = useState<PublishMode>('asset')
  const [sel, setSel]         = useState<ComposerSel>(EMPTY_SEL)
  const [newMode, setNewMode] = useState<Record<string, boolean>>(EMPTY_NEW_MODE)
  const [newVals, setNewVals] = useState<Record<string, string>>(EMPTY_NEW_VALS)
  const [seqs, setSeqs]   = useState<string[]>([])
  const [shots, setShots] = useState<string[]>([])

  // Export config (shared for all DCCs)
  const [exportExt, setExportExt]   = useState('.abc')
  const [isSequence, setIsSequence] = useState(false)
  const [frameStart, setFrameStart] = useState(1)
  const [frameEnd, setFrameEnd]     = useState(100)
  const [frameStep, setFrameStep]   = useState(1)

  // Source / description / state
  const [sourcePath, setSourcePath]   = useState('')
  const [description, setDescription] = useState('')
  const [publishing, setPublishing]   = useState(false)

  // ZBrush-specific
  const [zbrushConnected, setZbrushConnected] = useState(false)
  const [zbrushVersion, setZbrushVersion]     = useState<string | null>(null)
  const [zbObjOptions, setZbObjOptions] = useState({
    uvs: true, normals: true, flip_v: false, groups: false, materials: false,
    scope: 'selected' as 'all' | 'selected' | 'visible',
  })
  const [zbFbxOptions, setZbFbxOptions] = useState({
    fbx_version: '2019', animation: false, materials: true,
    scope: 'all' as 'all' | 'selected' | 'visible',
  })


  // Houdini-specific
  const [ropNodePath, setRopNodePath]             = useState('')
  const [houdiniConnected, setHoudiniConnected]   = useState(false)
  const [houdiniVersion, setHoudiniVersion]       = useState<string | null>(null)
  const [detectedNodeType, setDetectedNodeType]   = useState<string | null>(null)

  // Maya-specific
  const [mayaConnected, setMayaConnected]           = useState(false)
  const [mayaScope, setMayaScope]                   = useState<'scene' | 'selection'>('selection')
  const [lightUsd, setLightUsd]                     = useState(false)   // Maya UsdSkel light export
  const [mayaConnectCmd, setMayaConnectCmd]         = useState<string | null>(null)
  const [mayaAutostartInstalled, setMayaAutostartInstalled] = useState<boolean | null>(null)
  const [mayaStartupFile, setMayaStartupFile]       = useState<string | null>(null)

  // Projects
  useEffect(() => {
    api.getProjects()
      .then(d => {
        setProjects(d.projects)
        if (d.projects.length > 0) setProject(d.projects[0])
      })
      .catch(() => {})
  }, [])

  // Tokens for selected project
  useEffect(() => {
    if (!project) { setTokens({}); return }
    api.getTokens(project).then(d => setTokens(d.tokens)).catch(() => setTokens({}))
  }, [project])

  // Sequences (shot mode)
  useEffect(() => {
    if (!project || mode !== 'shot') { setSeqs([]); return }
    api.getSequences(project).then(d => setSeqs(d.sequences)).catch(() => setSeqs([]))
  }, [project, mode])

  // Shots for selected SEQ
  useEffect(() => {
    if (!project || mode !== 'shot' || !sel.seq) { setShots([]); return }
    api.getShots(project, sel.seq)
      .then(d => setShots(d.shots.map(s => s.split('/')[1] ?? s)))
      .catch(() => setShots([]))
  }, [project, mode, sel.seq])

  // ZBrush connection — single effect handles both navigation state and manual DCC switch.
  // Merged to avoid race condition where the dcc-change cleanup (→ false) overwrites
  // the navigation-state set (→ true) that fired in the same render cycle.
  useEffect(() => {
    // Sidebar navigated here after detecting the freeze — mark connected immediately, no ping.
    if (location.state?.zbrushConnected) {
      setDcc('ZBrush')
      setZbrushConnected(true)
      return
    }
    // Manual DCC switch — one-shot ping, no polling interval.
    if (dcc !== 'ZBrush') { setZbrushConnected(false); setZbrushVersion(null); return }
    let cancelled = false
    api.pingDcc('zbrush')
      .then(p => { if (!cancelled) { setZbrushConnected(p.connected); setZbrushVersion(p.version ?? null) } })
      .catch(() => { if (!cancelled) setZbrushConnected(false) })
    return () => { cancelled = true }
  }, [dcc, location.key]) // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch the Maya connect command once on mount (backend path is stable)
  useEffect(() => {
    api.getMayaConnectCmd().then(r => setMayaConnectCmd(r.cmd)).catch(() => {})
  }, [])

  // Re-check autostart status whenever Maya panel is active — catches Sidebar install/uninstall
  useEffect(() => {
    if (dcc !== 'Maya') return
    api.getDccAutostart('maya')
      .then(r => { setMayaAutostartInstalled(r.installed); setMayaStartupFile(r.startup_file ?? null) })
      .catch(() => { setMayaAutostartInstalled(false) })
  }, [dcc])

  // Maya connection — poll every 3 s when Maya DCC is active (commandPort can open any time)
  useEffect(() => {
    if (dcc !== 'Maya') { setMayaConnected(false); return }
    let cancelled = false
    const poll = async () => {
      try {
        const p = await api.pingDcc('maya')
        if (!cancelled) setMayaConnected(p.connected)
      } catch {
        if (!cancelled) setMayaConnected(false)
      }
    }
    void poll()
    const id = setInterval(() => void poll(), 3000)
    return () => { cancelled = true; clearInterval(id) }
  }, [dcc])

  // Reset exportExt when switching DCC if current format isn't in the new list
  useEffect(() => {
    const formats = formatsForDcc(dcc)
    if (!formats.includes(exportExt)) setExportExt(formats[0])
  }, [dcc]) // eslint-disable-line react-hooks/exhaustive-deps

  // Houdini polling — connection + selected node + auto-format
  useEffect(() => {
    if (dcc !== 'Houdini') return
    let cancelled = false
    const poll = async () => {
      try {
        const ping = await api.pingDcc('houdini')
        if (cancelled) return
        setHoudiniConnected(ping.connected)
        setHoudiniVersion(ping.version)
        if (!ping.connected) {
          // Drop stale node context so a later publish doesn't target a dead node.
          setRopNodePath('')
          setDetectedNodeType(null)
        }
        if (ping.connected) {
          const state = await api.getHoudiniState()
          if (cancelled) return
          if (state.selected_nodes?.length > 0) {
            const nodePath = state.selected_nodes[0]
            setRopNodePath(nodePath)

            // Primary: type from state (updated server)
            let rawType: string | undefined = (state.selected_node_types ?? {})[nodePath]

            // Fallback: infer from node name in path — works with any server version.
            // e.g. "/out/rop_alembic1" → name "rop_alembic1" → matches key "rop_alembic"
            if (!rawType) {
              const nodeName = nodePath.split('/').pop()?.toLowerCase() ?? ''
              const sortedKeys = Object.keys(NODE_TYPE_TO_EXT).sort((a, b) => b.length - a.length)
              rawType = sortedKeys.find(key => nodeName.includes(key))
            }

            setDetectedNodeType(rawType ?? null)
            const ext = rawType ? resolveNodeExt(rawType) : undefined
            if (ext) setExportExt(ext)
          } else {
            setDetectedNodeType(null)
          }
        }
      } catch { /* Houdini offline */ }
    }
    void poll()
    const id = setInterval(() => void poll(), 3000)
    return () => { cancelled = true; clearInterval(id) }
  }, [dcc])

  // ── Composer callbacks ──────────────────────────────────────────────────────

  const handleModeSwitch = useCallback(() => {
    setMode(prev => prev === 'asset' ? 'shot' : 'asset')
    setSel(EMPTY_SEL)
    setNewMode(EMPTY_NEW_MODE)
    setNewVals(EMPTY_NEW_VALS)
  }, [])

  const handleSelect = useCallback((key: string, value: string) => {
    setSel(prev => {
      const next = { ...prev, [key]: value }
      if (key === 'class') { next.type = ''; next.name = '' }
      if (key === 'type')  { next.name = '' }
      if (key === 'seq')   { next.shot = '' }
      return next
    })
  }, [])

  const handleNewToggle = useCallback((key: string) => {
    const wasActive = newMode[key]
    setNewMode(prev => ({ ...prev, [key]: !prev[key] }))
    if (wasActive) setNewVals(prev => ({ ...prev, [key]: '' }))
  }, [newMode])

  const handleNewVal = useCallback((key: string, value: string) => {
    setNewVals(prev => ({ ...prev, [key]: value }))
  }, [])

  // ── Filename assembly ───────────────────────────────────────────────────────

  const getEffective = useCallback((key: string): string => {
    if (newMode[key]) {
      const raw = newVals[key] || ''
      if (key === 'seq')  return formatSeqLabel(raw)
      if (key === 'shot') return formatShotLabel(raw)
      return formatToken(raw)
    }
    return sel[key] || ''
  }, [newMode, newVals, sel])

  const buildFilename = useCallback((): string => {
    const instance = getEffective('instance') || 'null'
    if (mode === 'asset') {
      return `${getEffective('class')}_${getEffective('type')}_${getEffective('name')}_${instance}`
    }
    return `${getEffective('name')}_${getEffective('seq')}_${getEffective('shot')}_${instance}`
  }, [mode, getEffective])

  // ── Token pre-creation before publish ──────────────────────────────────────

  const createNewTokens = useCallback(async () => {
    if (mode === 'shot') {
      if (newMode.seq && newVals.seq) {
        const num = parseInt(newVals.seq.replace(/[^0-9]/g, ''), 10)
        if (!isNaN(num)) {
          await api.createSequence(project, num)
          const d = await api.getSequences(project)
          setSeqs(d.sequences)
        }
      }
      if (newMode.shot && newVals.shot) {
        const seqLabel = newMode.seq ? formatSeqLabel(newVals.seq) : sel.seq
        const seqNum   = parseInt(seqLabel.replace(/[^0-9]/g, ''), 10)
        const shotNum  = parseInt(newVals.shot.replace(/[^0-9]/g, ''), 10)
        if (!isNaN(seqNum) && !isNaN(shotNum)) {
          await api.createShot(project, seqNum, shotNum)
          if (seqLabel) {
            const d = await api.getShots(project, seqLabel)
            setShots(d.shots.map(s => s.split('/')[1] ?? s))
          }
        }
      }
      return
    }
    // asset mode
    const newName = newMode.name     ? formatToken(newVals.name     || '') : ''
    const newInst = newMode.instance ? formatToken(newVals.instance || '') : ''
    if (newName && sel.class) {
      try { await api.createAsset(project, sel.class, newName) } catch { /* may already exist */ }
    }
    if (newInst && newInst !== 'null') {
      await api.addToken({ project, token_type: 'INSTANCE', token_value: newInst, rel_path: newInst.toLowerCase() })
    }
  }, [mode, project, sel.class, sel.seq, newMode, newVals])

  // ── Publish ─────────────────────────────────────────────────────────────────

  const handleCancelZBrush = useCallback(() => {
    setZbrushConnected(false)
    setZbrushVersion(null)
    api.cancelZBrush().catch(() => {}) // fire-and-forget — ZBrush may not be in freeze
  }, [])

  const reset = useCallback(() => {
    setSel(EMPTY_SEL)
    setNewMode(EMPTY_NEW_MODE)
    setNewVals(EMPTY_NEW_VALS)
    setSourcePath('')
    setDescription('')
  }, [])

  const handlePublish = useCallback(async () => {
    if (!project) { toast.error('Sélectionne un projet'); return }

    const filename = buildFilename()
    const parts = filename.split('_').filter(Boolean)
    if (parts.length < 4) {
      toast.error(mode === 'asset' ? 'Complète CLASS, TYPE et NAME' : 'Complète SEQ, SHOT et le type')
      return
    }

    setPublishing(true)

    try {
      await createNewTokens()

      if (dcc === 'Maya') {
        if (!mayaConnected) {
          toast.error('Maya non connecté : ouvre Maya avec le bridge FLUX actif (commandPort 7001)')
          return
        }
        if (lightUsd && mode === 'asset') {
          const assetName = (newMode.name ? formatToken(newVals.name || '') : sel.name) || parts[2]
          const res = await api.exportMayaLightUsd({
            project_name: project,
            asset:        assetName,
            frame_start:  isSequence ? frameStart : undefined,
            frame_end:    isSequence ? frameEnd : undefined,
          })
          toast.success(`USD léger ${res.version} → ${res.asset}`)
          return
        }
        const isAnimAbc = isSequence && exportExt === '.abc'
        const res = await api.publishMaya({
          project_name: project,
          filename,
          extension:    exportExt,
          scope:        mayaScope,
          is_sequence:  isAnimAbc,
          frame_range:  isAnimAbc ? [frameStart, frameEnd] : undefined,
          description:  description || undefined,
          user:         settings?.username ?? undefined,
        })
        toast.success(`v${res.version_str} → Maya`)
      } else if (dcc === 'Houdini') {
        if (!houdiniConnected) {
          toast.error('Houdini non connecté : lance le serveur FLUX dans Houdini')
          return
        }
        const res = await api.publishHoudiniRop({
          project_name:  project,
          filename,
          extension:     exportExt,
          rop_node_path: ropNodePath || undefined,
          is_sequence:   isSequence,
          frame_range:   isSequence ? [frameStart, frameEnd, frameStep] : undefined,
          description:   description || undefined,
          user:          settings?.username ?? undefined,
        })
        toast.success(`v${res.version_str} → ${res.rop_node}`)
      } else if (dcc === 'ZBrush') {
        if (!zbrushConnected) {
          toast.error('ZBrush non connecté : active le bridge FLUX dans ZBrush')
          return
        }
        const exportOptions =
          exportExt === '.obj' ? zbObjOptions :
          exportExt === '.fbx' ? zbFbxOptions : {}
        const res = await api.publishZBrush({
          project_name:   project,
          filename,
          extension:      exportExt,
          export_options: exportOptions,
          description:    description || undefined,
          user:           settings?.username ?? undefined,
        })
        toast.success(`v${res.version_str} → ZBrush`)
        setZbrushConnected(false)
        setZbrushVersion(null)
        window.electronAPI?.windowMinimize()
      } else if (dcc === 'Fichier local') {
        if (!sourcePath.trim()) {
          toast.error('Indique le fichier source')
          return
        }
        const res = await api.publish({
          source_path:  sourcePath,
          project_name: project,
          description:  description || undefined,
          user:         settings?.username ?? undefined,
        })
        if (res.success) toast.success(res.message)
        else toast.error(res.message)
      } else {
        toast.error(`Publication depuis ${dcc} non encore disponible`)
        return
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Erreur inconnue')
    } finally {
      setPublishing(false)
    }
  }, [
    project, mode, buildFilename, createNewTokens, dcc,
    exportExt, ropNodePath, isSequence, frameStart, frameEnd, frameStep,
    description, settings?.username, sourcePath,
    zbrushConnected, zbObjOptions, zbFbxOptions,
    mayaConnected, mayaScope, lightUsd, sel, newMode, newVals, houdiniConnected,
  ])

  const filename = buildFilename()

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>

      {/* Header */}
      <div style={{ padding: '12px 20px', borderBottom: '1px solid var(--rule)', display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.1em', color: 'var(--ink)' }}>Publish</div>
        <div style={{ flex: 1 }} />
        <Btn kbd sm>Ctrl+P</Btn>
      </div>

      <SoftwareSelector active={dcc} onChange={setDcc} />

      <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>

        {/* ── Left: Composer + source + description ── */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', borderRight: '1px solid var(--rule)', minWidth: 0, overflow: 'hidden' }}>

          <div style={{ flex: 1, padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 14, overflowY: 'auto', minHeight: 0 }}>

            {/* Project selector */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <div className="cap">PROJET</div>
              <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
                <span style={{ position: 'absolute', left: 8, pointerEvents: 'none', display: 'flex', zIndex: 1 }}>
                  <FolderIcon color="var(--accent)" />
                </span>
                <Select value={project} onValueChange={setProject}>
                  <SelectTrigger style={{ width: 200, paddingLeft: 26 }} />
                  <SelectContent>
                    {projects.length === 0
                      ? <SelectItem value="__none__">Aucun projet</SelectItem>
                      : projects.map(p => <SelectItem key={p} value={p}>{p}</SelectItem>)
                    }
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* Publish Composer */}
            <PublishComposer
              project={project}
              tokens={tokens}
              seqs={seqs}
              shots={shots}
              mode={mode}
              sel={sel}
              newMode={newMode}
              newVals={newVals}
              onModeSwitch={handleModeSwitch}
              onSelect={handleSelect}
              onNewToggle={handleNewToggle}
              onNewVal={handleNewVal}
            />

            {/* Source / DCC info */}
            {dcc === 'ZBrush' ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {/* Connection status */}
                <div>
                  <div className="cap" style={{ marginBottom: 6 }}>CONNEXION ZBRUSH</div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <div style={{
                      width: 7, height: 7, borderRadius: '50%', flexShrink: 0,
                      background: zbrushConnected ? 'var(--ok)' : 'var(--err)',
                    }} />
                    <div style={{ fontSize: 10, fontFamily: 'var(--mono)', color: 'var(--ink-3)' }}>
                      {zbrushConnected
                        ? `Connecté${zbrushVersion ? ` · ${zbrushVersion}` : ''}`
                        : 'Non connecté : installe le plugin via le bouton Plug dans la sidebar'}
                    </div>
                  </div>
                </div>

                {/* OBJ options */}
                {exportExt === '.obj' && (
                  <div>
                    <div className="cap" style={{ marginBottom: 6 }}>OPTIONS OBJ</div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px 14px', marginBottom: 8 }}>
                      {([
                        ['uvs',       'UVs'],
                        ['normals',   'Normales'],
                        ['flip_v',    'Flip V'],
                        ['groups',    'Groupes subtools'],
                        ['materials', 'Matériaux (.mtl)'],
                      ] as [keyof typeof zbObjOptions, string][]).map(([key, label]) => (
                        <label key={key} style={{ display: 'flex', alignItems: 'center', gap: 5, cursor: 'pointer' }}>
                          <input
                            type="checkbox"
                            checked={zbObjOptions[key] as boolean}
                            onChange={e => setZbObjOptions(prev => ({ ...prev, [key]: e.target.checked }))}
                            style={{ accentColor: 'var(--accent)', cursor: 'pointer' }}
                          />
                          <span style={{ fontSize: 10, fontFamily: 'var(--mono)', color: 'var(--ink-3)' }}>{label}</span>
                        </label>
                      ))}
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontSize: 9, fontFamily: 'var(--mono)', color: 'var(--ink-4)', letterSpacing: '0.06em' }}>SCOPE</span>
                      <div style={{ display: 'flex', gap: 4 }}>
                        {(['selected', 'visible', 'all'] as const).map(s => (
                          <div key={s} onClick={() => setZbObjOptions(prev => ({ ...prev, scope: s }))} style={{
                            padding: '3px 8px', borderRadius: 4, cursor: 'pointer',
                            fontFamily: 'var(--mono)', fontSize: 9, fontWeight: zbObjOptions.scope === s ? 600 : 400,
                            border: zbObjOptions.scope === s ? '1px solid var(--accent)' : '1px solid var(--rule-2)',
                            background: zbObjOptions.scope === s ? 'var(--accent-soft)' : 'transparent',
                            color: zbObjOptions.scope === s ? 'var(--accent-hi)' : 'var(--ink-3)',
                            transition: 'all 0.1s',
                          }}>{s}</div>
                        ))}
                      </div>
                    </div>
                  </div>
                )}

                {/* FBX options */}
                {exportExt === '.fbx' && (
                  <div>
                    <div className="cap" style={{ marginBottom: 6 }}>OPTIONS FBX</div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ fontSize: 9, fontFamily: 'var(--mono)', color: 'var(--ink-4)', letterSpacing: '0.06em' }}>VERSION</span>
                        <div style={{ display: 'flex', gap: 4 }}>
                          {(['2019', '2020', '2022'] as const).map(v => (
                            <div
                              key={v}
                              onClick={() => setZbFbxOptions(prev => ({ ...prev, fbx_version: v }))}
                              style={{
                                padding: '3px 8px', borderRadius: 4, cursor: 'pointer',
                                fontFamily: 'var(--mono)', fontSize: 9, fontWeight: zbFbxOptions.fbx_version === v ? 600 : 400,
                                border: zbFbxOptions.fbx_version === v ? '1px solid var(--accent)' : '1px solid var(--rule-2)',
                                background: zbFbxOptions.fbx_version === v ? 'var(--accent-soft)' : 'transparent',
                                color: zbFbxOptions.fbx_version === v ? 'var(--accent-hi)' : 'var(--ink-3)',
                                transition: 'all 0.1s',
                              }}
                            >{v}</div>
                          ))}
                        </div>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ fontSize: 9, fontFamily: 'var(--mono)', color: 'var(--ink-4)', letterSpacing: '0.06em' }}>SCOPE</span>
                        <div style={{ display: 'flex', gap: 4 }}>
                          {(['all', 'selected', 'visible'] as const).map(s => (
                            <div key={s} onClick={() => setZbFbxOptions(prev => ({ ...prev, scope: s }))} style={{
                              padding: '3px 8px', borderRadius: 4, cursor: 'pointer',
                              fontFamily: 'var(--mono)', fontSize: 9, fontWeight: zbFbxOptions.scope === s ? 600 : 400,
                              border: zbFbxOptions.scope === s ? '1px solid var(--accent)' : '1px solid var(--rule-2)',
                              background: zbFbxOptions.scope === s ? 'var(--accent-soft)' : 'transparent',
                              color: zbFbxOptions.scope === s ? 'var(--accent-hi)' : 'var(--ink-3)',
                              transition: 'all 0.1s',
                            }}>{s}</div>
                          ))}
                        </div>
                      </div>
                      <div style={{ display: 'flex', gap: 14 }}>
                        {([
                          ['animation', 'Animation'],
                          ['materials', 'Matériaux'],
                        ] as [keyof typeof zbFbxOptions, string][]).filter(([k]) => typeof zbFbxOptions[k] === 'boolean').map(([key, label]) => (
                          <label key={key} style={{ display: 'flex', alignItems: 'center', gap: 5, cursor: 'pointer' }}>
                            <input
                              type="checkbox"
                              checked={zbFbxOptions[key] as boolean}
                              onChange={e => setZbFbxOptions(prev => ({ ...prev, [key]: e.target.checked }))}
                              style={{ accentColor: 'var(--accent)', cursor: 'pointer' }}
                            />
                            <span style={{ fontSize: 10, fontFamily: 'var(--mono)', color: 'var(--ink-3)' }}>{label}</span>
                          </label>
                        ))}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            ) : dcc === 'Maya' ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>

                {/* Connection dot */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <div style={{
                    width: 7, height: 7, borderRadius: '50%', flexShrink: 0,
                    background: mayaConnected ? 'var(--ok)' : 'var(--err)',
                    transition: 'background 0.3s',
                  }} />
                  <div style={{ fontSize: 10, fontFamily: 'var(--mono)', color: mayaConnected ? 'var(--ok)' : 'var(--ink-3)' }}>
                    {mayaConnected ? '✓ Connecté · commandPort 7001' : 'Port 7001 injoignable'}
                  </div>
                </div>

                {/* Step-by-step guide when not connected — only render once autostart state resolved */}
                {!mayaConnected && mayaAutostartInstalled !== null && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>

                    {/* Step 1 — Plug */}
                    <div style={{
                      display: 'flex', gap: 7, padding: '6px 8px', borderRadius: 5,
                      background: mayaAutostartInstalled ? 'var(--paper-2)' : 'var(--accent-soft)',
                      border: `1px solid ${mayaAutostartInstalled ? 'var(--rule-2)' : 'var(--accent)'}`,
                    }}>
                      <div style={{
                        width: 16, height: 16, borderRadius: '50%', flexShrink: 0,
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        background: mayaAutostartInstalled ? 'var(--ok)' : 'var(--accent)',
                        fontSize: 8, fontWeight: 700, color: 'white',
                      }}>
                        {mayaAutostartInstalled ? '✓' : '1'}
                      </div>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                        <div style={{ fontSize: 9, fontFamily: 'var(--mono)', fontWeight: 600, color: mayaAutostartInstalled ? 'var(--ink-3)' : 'var(--accent-hi)' }}>
                          {mayaAutostartInstalled ? 'Autostart installé' : 'Installer l\'autostart Maya'}
                        </div>
                        <div style={{ fontSize: 8, fontFamily: 'var(--mono)', color: 'var(--ink-4)', lineHeight: 1.4 }}>
                          {mayaAutostartInstalled
                            ? (mayaStartupFile ?? 'userSetup.py mis à jour')
                            : 'Sidebar → bouton Plug ⬡ à côté de Maya'}
                        </div>
                      </div>
                    </div>

                    {/* Step 2 — Restart Maya */}
                    {mayaAutostartInstalled && (
                      <div style={{
                        display: 'flex', gap: 7, padding: '6px 8px', borderRadius: 5,
                        background: 'var(--accent-soft)', border: '1px solid var(--accent)',
                      }}>
                        <div style={{
                          width: 16, height: 16, borderRadius: '50%', flexShrink: 0,
                          display: 'flex', alignItems: 'center', justifyContent: 'center',
                          background: 'var(--accent)', fontSize: 8, fontWeight: 700, color: 'white',
                        }}>2</div>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                          <div style={{ fontSize: 9, fontFamily: 'var(--mono)', fontWeight: 600, color: 'var(--accent-hi)' }}>
                            Redémarre Maya
                          </div>
                          <div style={{ fontSize: 8, fontFamily: 'var(--mono)', color: 'var(--ink-4)', lineHeight: 1.4 }}>
                            Le commandPort s'ouvre automatiquement au démarrage
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Quick open — paste in Maya Script Editor */}
                    {mayaConnectCmd && (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                        <div style={{ fontSize: 8, fontFamily: 'var(--mono)', color: 'var(--ink-3)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                          Ouvrir le port immédiatement · Maya Script Editor (Python) :
                        </div>
                        <CopyBlock text={mayaConnectCmd} />
                      </div>
                    )}

                    {/* Diagnostic — check where Maya actually loads scripts from */}
                    {mayaAutostartInstalled && mayaStartupFile && (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                        <div style={{ fontSize: 8, fontFamily: 'var(--mono)', color: 'var(--ink-4)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                          Si ça ne marche toujours pas, vérifie le chemin Maya (Script Editor Python) :
                        </div>
                        <CopyBlock text={`import maya.cmds as cmds; print(cmds.internalVar(userScriptDir=True))`} />
                        <div style={{ fontSize: 8, fontFamily: 'var(--mono)', color: 'var(--ink-4)', lineHeight: 1.5 }}>
                          Compare avec : <span style={{ color: 'var(--accent-hi)', wordBreak: 'break-all' }}>{mayaStartupFile.replace(/userSetup\.py$/i, '')}</span>
                          <br />Si différent → le bloc est écrit au mauvais endroit.
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ) : dcc === 'Houdini' ? (
              <div>
                <div className="cap" style={{ marginBottom: 6 }}>NODE ROP</div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 7 }}>
                  <div style={{
                    width: 7, height: 7, borderRadius: '50%', flexShrink: 0,
                    background: houdiniConnected ? 'var(--ok)' : 'var(--err)',
                  }} />
                  <div style={{ fontSize: 10, fontFamily: 'var(--mono)', color: 'var(--ink-3)' }}>
                    {houdiniConnected
                      ? `Connecté${houdiniVersion ? ` · Houdini ${houdiniVersion}` : ''}`
                      : 'Houdini non connecté : lance le serveur FLUX dans Houdini'}
                  </div>
                </div>
                <input
                  value={ropNodePath}
                  onChange={e => setRopNodePath(e.target.value)}
                  placeholder="/out/rop_alembic1  (auto-rempli depuis la sélection)"
                  style={{
                    width: '100%', height: 28,
                    background: 'var(--bg-deep)', border: '1px solid var(--rule-2)',
                    borderRadius: 5, padding: '0 8px',
                    fontFamily: 'var(--sans)', fontSize: 10, color: 'var(--ink-2)',
                    boxShadow: 'var(--shadow-inset)', outline: 'none',
                  }}
                />
                {detectedNodeType && (
                  <div style={{ marginTop: 4, fontSize: 9, fontFamily: 'var(--mono)', color: resolveNodeExt(detectedNodeType) ? 'var(--ok)' : 'var(--ink-4)' }}>
                    {resolveNodeExt(detectedNodeType)
                      ? `→ ${resolveNodeExt(detectedNodeType)} (${detectedNodeType})`
                      : `type non reconnu : ${detectedNodeType}`}
                  </div>
                )}
              </div>
            ) : dcc === 'Fichier local' ? (
              <div>
                <div className="cap" style={{ marginBottom: 6 }}>FICHIER SOURCE</div>
                <input
                  value={sourcePath}
                  onChange={e => setSourcePath(e.target.value)}
                  placeholder="Chemin absolu vers le fichier à publier…"
                  style={{
                    width: '100%', height: 28,
                    background: 'var(--bg-deep)', border: '1px solid var(--rule-2)',
                    borderRadius: 5, padding: '0 8px',
                    fontFamily: 'var(--sans)', fontSize: 10, color: 'var(--ink-2)',
                    boxShadow: 'var(--shadow-inset)', outline: 'none',
                  }}
                />
              </div>
            ) : (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 10px', borderRadius: 6, background: 'var(--paper-2)', border: '1px solid var(--rule-2)' }}>
                <div style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--ink-4)', flexShrink: 0 }} />
                <div style={{ fontSize: 10, fontFamily: 'var(--mono)', color: 'var(--ink-4)' }}>
                  La publication depuis <span style={{ color: 'var(--ink-2)' }}>{dcc}</span> se déclenche directement depuis le logiciel
                </div>
              </div>
            )}

            {/* Published by */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{ fontSize: 9, fontFamily: 'var(--mono)', color: 'var(--ink-4)', letterSpacing: '0.06em' }}>PUBLIÉ PAR</div>
              <div style={{ fontSize: 10, fontFamily: 'var(--mono)', color: 'var(--ink-3)' }}>
                {settings?.username ?? '-'}
              </div>
            </div>
          </div>

          {/* Description + result */}
          <div style={{ padding: '0 20px 16px', flexShrink: 0 }}>
            <SecTitle>Description</SecTitle>
            <textarea
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="Décris la modification effectuée…"
              style={{
                width: '100%', height: 90, resize: 'none',
                background: 'var(--paper-2)', border: '1px solid var(--rule-2)',
                borderRadius: 6, padding: '10px 12px',
                fontFamily: 'var(--sans)', fontSize: 11, color: 'var(--ink-2)',
                outline: 'none', boxShadow: 'var(--shadow-inset)',
              }}
            />
          </div>
        </div>

        {/* ── Right: Format + Séquence + Aperçu (shared for all DCCs) ── */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, overflow: 'hidden' }}>

          {/* FORMAT */}
          <div style={{ padding: '16px 20px 12px', flexShrink: 0 }}>
            <SecTitle>FORMAT</SecTitle>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {formatsForDcc(dcc).map(ext => (
                <div key={ext} onClick={() => setExportExt(ext)} className="scale-hover" style={{
                  padding: '5px 10px', borderRadius: 6, cursor: 'pointer', fontSize: 11,
                  fontFamily: 'var(--mono)', fontWeight: exportExt === ext ? 600 : 400,
                  border: exportExt === ext ? '1px solid var(--accent)' : '1px solid var(--rule-2)',
                  background: exportExt === ext ? 'var(--accent-soft)' : 'var(--paper-2)',
                  color: exportExt === ext ? 'var(--accent-hi)' : 'var(--ink-3)',
                  transition: 'all 0.1s',
                }}>{ext}</div>
              ))}
            </div>
          </div>

          {/* SÉQUENCE ANIMÉE — ZBrush: never; Maya: .abc only; Houdini: always */}
          <div style={{ padding: '0 20px 12px', flexShrink: 0, opacity: (dcc === 'ZBrush' || (dcc === 'Maya' && exportExt !== '.abc')) ? 0.35 : 1, pointerEvents: (dcc === 'ZBrush' || (dcc === 'Maya' && exportExt !== '.abc')) ? 'none' : undefined }}>
            <SecTitle>SÉQUENCE ANIMÉE</SecTitle>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: isSequence ? 10 : 0 }}>
              <div onClick={() => setIsSequence(v => !v)} style={{
                width: 32, height: 18, borderRadius: 9, cursor: 'pointer', flexShrink: 0,
                background: isSequence ? 'var(--accent)' : 'var(--rule-2)',
                position: 'relative', transition: 'background 0.15s',
              }}>
                <div style={{
                  position: 'absolute', top: 2, left: isSequence ? 16 : 2,
                  width: 14, height: 14, borderRadius: '50%', background: 'white',
                  transition: 'left 0.15s', boxShadow: '0 1px 3px rgba(0,0,0,.3)',
                }} />
              </div>
              <div style={{ fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--ink-3)' }}>
                {isSequence ? 'Activé · dossier versionné + $F4' : 'Désactivé · fichier unique LAST'}
              </div>
            </div>
            {isSequence && (
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                {([['Start', frameStart, setFrameStart], ['End', frameEnd, setFrameEnd], ['Step', frameStep, setFrameStep]] as const).map(([lbl, val, set]) => (
                  <div key={lbl} style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                    <div style={{ fontSize: 9, color: 'var(--ink-4)', fontFamily: 'var(--mono)', textTransform: 'uppercase' }}>{lbl}</div>
                    <input type="number" value={val} onChange={e => set(Number(e.target.value))} style={{
                      width: 56, height: 26, background: 'var(--bg-deep)', border: '1px solid var(--rule-2)',
                      borderRadius: 5, padding: '0 6px', fontFamily: 'var(--mono)', fontSize: 11,
                      color: 'var(--ink)', boxShadow: 'var(--shadow-inset)', outline: 'none',
                    }} />
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* SCOPE — Maya only */}
          {dcc === 'Maya' && (
            <div style={{ padding: '0 20px 12px', flexShrink: 0 }}>
              <SecTitle>SCOPE</SecTitle>
              <div style={{ display: 'flex', gap: 4 }}>
                {(['selection', 'scene'] as const).map(s => (
                  <div
                    key={s}
                    onClick={() => setMayaScope(s)}
                    style={{
                      padding: '5px 10px', borderRadius: 6, cursor: 'pointer',
                      fontFamily: 'var(--mono)', fontSize: 11, fontWeight: mayaScope === s ? 600 : 400,
                      border: mayaScope === s ? '1px solid var(--accent)' : '1px solid var(--rule-2)',
                      background: mayaScope === s ? 'var(--accent-soft)' : 'var(--paper-2)',
                      color: mayaScope === s ? 'var(--accent-hi)' : 'var(--ink-3)',
                      transition: 'all 0.1s',
                    }}
                  >{s}</div>
                ))}
              </div>
            </div>
          )}

          {/* EXPORT USD LÉGER — Maya asset only */}
          {dcc === 'Maya' && mode === 'asset' && (
            <div style={{ padding: '0 20px 12px', flexShrink: 0 }}>
              <SecTitle>EXPORT USD LÉGER</SecTitle>
              <div
                onClick={() => setLightUsd(v => !v)}
                style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', userSelect: 'none' }}
              >
                <div style={{
                  width: 28, height: 16, borderRadius: 8, flexShrink: 0,
                  background: lightUsd ? 'var(--accent)' : 'var(--rule-2)',
                  position: 'relative', transition: 'background 0.15s',
                }}>
                  <div style={{
                    position: 'absolute', top: 2, left: lightUsd ? 14 : 2,
                    width: 12, height: 12, borderRadius: '50%', background: 'white',
                    transition: 'left 0.15s',
                  }} />
                </div>
                <span style={{ fontSize: 10, fontFamily: 'var(--mono)', color: lightUsd ? 'var(--accent-hi)' : 'var(--ink-3)' }}>
                  UsdSkel (model + skel + animation des joints)
                </span>
              </div>
            </div>
          )}

          {/* APERÇU OUTPUT */}
          <div style={{ flex: 1, padding: '0 20px 16px', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
            <SecTitle>APERÇU OUTPUT</SecTitle>
            <div className="subcard" style={{ flex: 1, padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 4, minHeight: 0, overflowY: 'auto' }}>
              {isSequence ? (<>
                <div style={{ fontSize: 10, fontFamily: 'var(--mono)', color: 'var(--ink-3)' }}>{filename}_v001/</div>
                <div style={{ fontSize: 10, fontFamily: 'var(--mono)', color: 'var(--ink)', paddingLeft: 12 }}>
                  {filename}_v001.$F4{exportExt}
                </div>
              </>) : (
                <div style={{ fontSize: 10, fontFamily: 'var(--mono)', color: 'var(--ink)' }}>
                  {filename}_LAST{exportExt}
                </div>
              )}
              {dcc === 'Houdini' && ropNodePath && (
                <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid var(--rule)', fontSize: 9, fontFamily: 'var(--mono)', color: 'var(--ink-4)' }}>
                  ROP : {ropNodePath}
                </div>
              )}
              {dcc === 'ZBrush' && (
                <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid var(--rule)', fontSize: 9, fontFamily: 'var(--mono)', color: zbrushConnected ? 'var(--ok)' : 'var(--err)' }}>
                  {zbrushConnected ? `● ZBrush connecté${zbrushVersion ? ` · ${zbrushVersion}` : ''}` : '✕ ZBrush non connecté'}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Bottom bar */}
      <div style={{ borderTop: '1px solid var(--rule)', padding: '9px 20px', display: 'flex', gap: 8, justifyContent: 'flex-end', flexShrink: 0 }}>
        <Btn ghost onClick={reset}>Réinitialiser</Btn>
        {dcc === 'ZBrush' && (
          <Btn ghost onClick={handleCancelZBrush}>Annuler</Btn>
        )}
        <Btn primary onClick={() => void handlePublish()}>
          {publishing ? 'Publication…' : 'Publish →'}
        </Btn>
      </div>
    </div>
  )
}
