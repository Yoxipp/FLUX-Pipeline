// Production.tsx — Production Tab shell.
//
// Layout:
//   ┌───────────────────────────────────────────────┬───────┐
//   │              Timeline / Grid                  │ Edit  │
//   ├───────────────────────────────────────────────┴───────┤
//   │              Spec (Tasks / TaskDetail)                │
//   └───────────────────────────────────────────────────────┘
//
// Phase 1 lands the ASSET grid + MenuEdit + MenuSpec end-to-end. The SHOT
// timeline lives behind the mode toggle so Phase 2 slots in without a rewrite.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { ChevronDown, ChevronUp, PanelRightClose, PanelRightOpen } from 'lucide-react'
import { useProject } from '../../ProjectContext'
import { useI18n } from '../../i18n'
import { useProduction } from '../../hooks/useProduction'
import { ProductionAsset } from './ProductionAsset'
import { ProductionShot } from './ProductionShot'
import { MenuEdit } from './MenuEdit'
import { MenuSpec } from './MenuSpec'
import { useSessionState } from '../../hooks/useSessionState'

type Mode = 'asset' | 'shot'
export type Selection =
  | { kind: 'none' }
  | { kind: 'asset';  id: string }
  | { kind: 'group';  id: string }
  | { kind: 'seq';    id: string }
  | { kind: 'shot';   id: string }

const LS = {
  mode:       'flux.production.mode',
  editOpen:   'flux.production.editOpen',
  specOpen:   'flux.production.specOpen',
  category:   'flux.production.category',
  specHeight: 'flux.production.specHeight',
}

const SPEC_DEFAULT_PCT = 25
const SPEC_MIN_PX = 60
const SPEC_MAX_PCT = 80

function useLocalBool(key: string, def: boolean): [boolean, (b: boolean) => void] {
  const [v, setV] = useState<boolean>(() => {
    try { const s = localStorage.getItem(key); if (s === '1') return true; if (s === '0') return false } catch { /* blocked */ }
    return def
  })
  const set = (b: boolean) => {
    setV(b)
    try { localStorage.setItem(key, b ? '1' : '0') } catch { /* blocked */ }
  }
  return [v, set]
}

function useLocalStr<T extends string>(key: string, def: T): [T, (v: T) => void] {
  const [v, setV] = useState<T>(() => {
    try { const s = localStorage.getItem(key); if (s) return s as T } catch { /* blocked */ }
    return def
  })
  const set = (v: T) => {
    setV(v)
    try { localStorage.setItem(key, v) } catch { /* blocked */ }
  }
  return [v, set]
}

export interface FavoriteOpenTarget {
  project: string
  class:   string
  name:    string
  task:    string
  subtask?: string
}

const NO_SELECTION: Selection = { kind: 'none' }

export function Production() {
  const { project } = useProject()
  const { t } = useI18n()
  const location = useLocation() as { state?: { openFavorite?: FavoriteOpenTarget } | null }
  const prod = useProduction(project || null)
  const [mode, setMode]         = useLocalStr<Mode>(LS.mode, 'asset')
  const [editOpen, setEditOpen] = useLocalBool(LS.editOpen, true)
  const [specOpen, setSpecOpen] = useLocalBool(LS.specOpen, true)
  // Session-kept (U3): coming back to Production reselects the same entity (same project only).
  const [selState, setSelState] = useSessionState<{ project: string; sel: Selection }>(
    'prod.selection', { project: project || '', sel: { kind: 'none' } })
  const selection: Selection = selState.project === (project || '') ? selState.sel : NO_SELECTION
  const setSelection = useCallback((sel: Selection) => setSelState({ project: project || '', sel }), [project, setSelState])
  const [activeCategory, setActiveCategoryRaw] = useState<string | null>(() => {
    try { const s = localStorage.getItem(LS.category); return s || null } catch { return null }
  })
  // Spec pane height in *px*, persisted. Falls back to ~25% of viewport at first load.
  const [specHeight, setSpecHeight] = useState<number>(() => {
    try {
      const v = localStorage.getItem(LS.specHeight)
      if (v) { const n = Number(v); if (!Number.isNaN(n) && n > 0) return n }
    } catch { /* blocked */ }
    return Math.max(SPEC_MIN_PX, Math.round((window.innerHeight || 800) * SPEC_DEFAULT_PCT / 100))
  })
  const containerRef = useRef<HTMLDivElement | null>(null)
  const dragStartRef = useRef<{ y: number; h: number } | null>(null)

  const onResizeStart = (e: React.MouseEvent) => {
    e.preventDefault()
    dragStartRef.current = { y: e.clientY, h: specHeight }
    const onMove = (ev: MouseEvent) => {
      const start = dragStartRef.current
      if (!start) return
      const containerH = containerRef.current?.getBoundingClientRect().height ?? window.innerHeight
      const maxPx = Math.round(containerH * SPEC_MAX_PCT / 100)
      const next = Math.max(SPEC_MIN_PX, Math.min(maxPx, start.h + (start.y - ev.clientY)))
      setSpecHeight(next)
    }
    const onUp = () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
      dragStartRef.current = null
      try { localStorage.setItem(LS.specHeight, String(specHeight)) } catch { /* blocked */ }
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }
  // Persist the height whenever it settles (after a drag), also directly on toggles.
  useEffect(() => {
    try { localStorage.setItem(LS.specHeight, String(specHeight)) } catch { /* blocked */ }
  }, [specHeight])
  const setActiveCategory = (c: string | null) => {
    setActiveCategoryRaw(c)
    try { if (c) localStorage.setItem(LS.category, c); else localStorage.removeItem(LS.category) } catch { /* blocked */ }
  }

  // Reset selection + category when the project switches so we never point at a stale id.
  // Not on mount: the session selection and the stored category are restored (U3).
  const prevProjectRef = useRef(project)
  useEffect(() => {
    if (prevProjectRef.current === project) return
    prevProjectRef.current = project
    setSelection({ kind: 'none' }); setActiveCategoryRaw(null)
  }, [project])   // eslint-disable-line react-hooks/exhaustive-deps

  // Deep-link target from Activity (fav row click). Sits pending until the
  // matching asset can be located in the loaded production state, then hands
  // off to MenuSpec via `pendingSpec` so the right tab opens.
  const [pendingFav, setPendingFav] = useState<FavoriteOpenTarget | null>(null)
  useEffect(() => {
    const target = location.state?.openFavorite ?? null
    if (target) {
      setPendingFav(target)
      // Wipe the router state so a subsequent manual nav doesn't re-trigger.
      window.history.replaceState({}, '')
    }
  }, [location.state])

  // Apply the pending target once the target's project is active and the
  // matching asset shows up in state.
  const [pendingSpec, setPendingSpec] = useState<{ task: string; subtask?: string } | null>(null)
  useEffect(() => {
    if (!pendingFav) return
    if (!project || pendingFav.project !== project) return
    setMode('asset')
    setActiveCategory(pendingFav.class.toUpperCase())
    const asset = prod.state.assets.find(a =>
      a.class.toUpperCase() === pendingFav.class.toUpperCase() &&
      a.name.toUpperCase()  === pendingFav.name.toUpperCase(),
    )
    if (!asset) return   // still loading — try again on the next render
    setSelection({ kind: 'asset', id: asset.id })
    setSpecOpen(true)
    setPendingSpec({ task: pendingFav.task, subtask: pendingFav.subtask })
    setPendingFav(null)
  }, [pendingFav, project, prod.state.assets])   // eslint-disable-line react-hooks/exhaustive-deps

  // Open the spec panel whenever any entity is selected but the panel is closed.
  useEffect(() => {
    if (selection.kind !== 'none' && !specOpen) setSpecOpen(true)
  }, [selection.kind])   // eslint-disable-line react-hooks/exhaustive-deps

  const selected = useMemo(() => {
    if (selection.kind === 'asset') return prod.state.assets.find(a => a.id === selection.id) ?? null
    if (selection.kind === 'group') return prod.state.asset_groups.find(g => g.id === selection.id) ?? null
    if (selection.kind === 'seq')   {
      const s = prod.state.sequences.find(x => x.id === selection.id) ?? null
      return s ? { class: 'SEQ', name: s.name } : null
    }
    if (selection.kind === 'shot')  {
      const sh = prod.state.shots.find(x => x.id === selection.id) ?? null
      if (!sh) return null
      const seq = prod.state.sequences.find(q => q.id === sh.seq_id)
      return { class: seq?.name ?? '', name: sh.name }
    }
    return null
  }, [selection, prod.state])

  if (!project) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--ink-3)', fontSize: 12 }}>
        {t('prod.noProject')}
      </div>
    )
  }

  return (
    <div ref={containerRef} style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, minWidth: 0 }}>
      {/* Toolbar */}
      <div style={{
        padding: '10px 16px', borderBottom: '1px solid var(--rule)',
        display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0,
      }}>
        <div style={{ display: 'inline-flex', border: '1px solid var(--rule-2)', borderRadius: 6, overflow: 'hidden' }}>
          {(['asset', 'shot'] as Mode[]).map(m => (
            <button
              key={m}
              onClick={() => {
                if (m === mode) return
                setMode(m)
                setSelection({ kind: 'none' })
              }}
              style={{
                background: mode === m ? 'var(--accent-soft)' : 'transparent',
                color:      mode === m ? 'var(--accent-hi)' : 'var(--ink-2)',
                border: 'none', padding: '6px 14px', fontSize: 11,
                cursor: 'pointer',
                borderRight: m === 'asset' ? '1px solid var(--rule-2)' : 'none',
              }}
            >{t(m === 'asset' ? 'prod.mode.asset' : 'prod.mode.shot')}</button>
          ))}
        </div>
        <div style={{ flex: 1 }} />
        {/* current project — always visible, right side of the toolbar */}
        <div
          title={project}
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            padding: '5px 11px', borderRadius: 999,
            border: '1px solid var(--rule-2)', background: 'var(--paper-2)',
            color: 'var(--ink-2)', fontFamily: 'var(--mono)', fontSize: 10,
            letterSpacing: '0.06em', textTransform: 'uppercase',
            maxWidth: 220,
          }}
        >
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--accent)' }} />
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {project}
          </span>
        </div>
        <button
          onClick={() => setEditOpen(!editOpen)}
          title={editOpen ? 'Replier le menu Edit' : 'Déployer le menu Edit'}
          style={_iconBtn}
        >{editOpen ? <PanelRightClose size={13} strokeWidth={1.75} /> : <PanelRightOpen size={13} strokeWidth={1.75} />}</button>
      </div>

      {/* Middle: main + edit */}
      <div style={{ flex: 1, display: 'flex', minHeight: 0, minWidth: 0 }}>
        <div style={{ flex: 1, minWidth: 0, overflowY: 'auto', overflowX: 'hidden' }}>
          {mode === 'asset' && (
            <ProductionAsset
              state={prod.state}
              setState={prod.setState}
              selection={selection}
              setSelection={setSelection}
              activeCategory={activeCategory}
              setActiveCategory={setActiveCategory}
              onAssetClicked={() => setSpecOpen(true)}
            />
          )}
          {mode === 'shot' && (
            <ProductionShot
              state={prod.state}
              setState={prod.setState}
              selection={selection}
              setSelection={setSelection}
              onEntityClicked={() => setSpecOpen(true)}
            />
          )}
        </div>

        {editOpen && (
          <div style={{
            width: 260, flexShrink: 0, borderLeft: '1px solid var(--rule)',
            background: 'var(--paper-2)', overflowY: 'auto',
          }}>
            <MenuEdit
              project={project}
              state={prod.state}
              setState={prod.setState}
              selection={selection}
              setSelection={setSelection}
              mode={mode}
              activeCategory={activeCategory}
              publishesByTask={prod.publishesByTask}
              sequencesOnDisk={prod.sequencesOnDisk}
              shotsOnDisk={prod.shotsOnDisk}
            />
          </div>
        )}
      </div>

      {/* Bottom: spec (resizable) */}
      <div style={{
        borderTop: '1px solid var(--rule)', background: 'var(--paper-2)',
        flexShrink: 0, display: 'flex', flexDirection: 'column',
        height: specOpen ? specHeight : 30,
        transition: dragStartRef.current ? 'none' : 'height 0.18s',
      }}>
        {/* resize handle (only when the panel is open) */}
        {specOpen && (
          <div
            onMouseDown={onResizeStart}
            title="Redimensionner"
            style={{
              height: 6, cursor: 'ns-resize',
              background: 'transparent',
              flexShrink: 0,
              position: 'relative',
            }}
          >
            <div style={{
              width: 40, height: 3, borderRadius: 2,
              background: 'var(--rule-2)',
              position: 'absolute', left: '50%', top: 1, transform: 'translateX(-50%)',
            }} />
          </div>
        )}
        <div
          onClick={() => setSpecOpen(!specOpen)}
          style={{
            padding: '4px 14px 6px', display: 'flex', alignItems: 'center', gap: 8,
            cursor: 'pointer', borderBottom: specOpen ? '1px solid var(--rule)' : 'none',
            userSelect: 'none', flexShrink: 0,
          }}
        >
          {specOpen ? <ChevronDown size={11} strokeWidth={2} color="var(--ink-4)" /> : <ChevronUp size={11} strokeWidth={2} color="var(--ink-4)" />}
          <span className="cap" style={{ letterSpacing: '0.08em' }}>Spec</span>
          <span style={{ flex: 1 }} />
          {selected && (
            <span style={{ fontSize: 10, color: 'var(--ink-3)', fontFamily: 'var(--mono)' }}>
              {selected.class} · {selected.name}
            </span>
          )}
        </div>
        {specOpen && (
          <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
            <MenuSpec
              state={prod.state}
              setState={prod.setState}
              selection={selection}
              publishesByTask={prod.publishesByTask}
              loading={prod.loading}
              initialOpen={pendingSpec}
              onInitialOpenApplied={() => setPendingSpec(null)}
            />
          </div>
        )}
      </div>
    </div>
  )
}

const _iconBtn: React.CSSProperties = {
  width: 26, height: 22, display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
  borderRadius: 5, border: '1px solid var(--rule-2)', background: 'var(--paper-2)',
  color: 'var(--ink-2)', cursor: 'pointer',
}
