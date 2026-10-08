import { useCallback, useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import * as Dialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { useProject } from '../../ProjectContext'
import { useProduction } from '../../hooks/useProduction'
import { useSessionState } from '../../hooks/useSessionState'
import { ProductionShot } from './ProductionShot'
import { MenuEdit } from './MenuEdit'
import { MenuSpec } from './MenuSpec'
import { ProductionTracking } from './ProductionTracking'
import { NewProductionDialog } from './NewProductionDialog'
import { ProductionSettings } from './ProductionSettings'
import type { CreateKind } from './CreateMenu'

export type Selection = { kind: 'none' } | { kind: 'asset' | 'group' | 'seq' | 'shot'; id: string }
export interface FavoriteOpenTarget {
  project: string
  class:   string
  name:    string
  task:    string
  subtask?: string
}


export function Production() {
  const { project } = useProject()
  const location = useLocation()
  const navigate = useNavigate()
  const prod = useProduction(project || null)
  const [storedMode, setStoredMode] = useState<'asset' | 'shot'>(() => localStorage.getItem('flux.production.mode') === 'asset' ? 'asset' : 'shot')
  const requestedMode = new URLSearchParams(location.search).get('mode')
  const mode = requestedMode === 'asset' || requestedMode === 'shot' ? requestedMode : storedMode
  useEffect(() => { setStoredMode(mode); localStorage.setItem('flux.production.mode', mode) }, [mode])
  const [selState, setSelState] = useSessionState<{ project: string; sel: Selection }>('prod.selection', { project: project || '', sel: { kind: 'none' } })
  const selection: Selection = selState.project === (project || '') ? selState.sel : { kind: 'none' }
  const setSelection = useCallback((sel: Selection) => setSelState({ project: project || '', sel }), [project, setSelState])
  const [dialog, setDialog] = useState<'new' | 'edit' | null>(null)
  const [createKind, setCreateKind] = useState<CreateKind | undefined>(undefined)
  const openCreate = (kind?: CreateKind) => { setCreateKind(kind); setDialog('new') }
  const [pendingSpec, setPendingSpec] = useState<{ task: string; subtask?: string } | null>(null)
  const favorite = (location.state as { openFavorite?: FavoriteOpenTarget } | null)?.openFavorite
  useEffect(() => {
    if (!favorite || favorite.project !== project) return
    const asset = prod.state.assets.find(a => a.class.toUpperCase() === favorite.class.toUpperCase() && a.name.toUpperCase() === favorite.name.toUpperCase())
    if (!asset) return
    setStoredMode('asset'); setSelection({ kind: 'asset', id: asset.id })
    setPendingSpec({ task: favorite.task, subtask: favorite.subtask })
    navigate('/production?mode=asset', { replace: true, state: null })
  }, [favorite, project, prod.state.assets])
  const openEntity = (sel: Selection) => {
    setSelection(sel)
    if (sel.kind === 'asset' || sel.kind === 'shot') navigate(`/production?mode=${sel.kind}`, { replace: true })
    setPendingSpec({ task: 'ENTITY' })
  }
  if (!project) return <div style={{ padding: 24, color: 'var(--ink-3)' }}>Sélectionnez un projet.</div>
  return <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, minWidth: 0, zoom: 0.9 }}>
    <MenuSpec state={prod.state} setState={prod.setState} selection={selection} publishesByTask={prod.publishesByTask} loading={prod.loading} workspaceMode={mode}
      initialOpen={pendingSpec} onInitialOpenApplied={() => setPendingSpec(null)}
      main={<ProductionTracking key={`${project}:${mode}`} project={project} mode={mode} state={prod.state} setState={prod.setState} selection={selection} setSelection={setSelection} loading={prod.loading}
        onEdit={() => setDialog('edit')} onNew={openCreate} onSettings={() => setPendingSpec({ task: 'SETTINGS' })}
        onOpenEntity={openEntity}
        onOpenDetail={(sel, task, subtask) => { setSelection(sel); setPendingSpec({ task: task.name, subtask }) }} />}
      settingsPane={<ProductionSettings key={`${project}:${mode}`} state={prod.state} setState={prod.setState} mode={mode} />}
      entityView={id => {
        const asset = prod.state.assets.find(a => a.id === id)
        const shot = prod.state.shots.find(a => a.id === id)
        if (!asset && !shot) return null
        return <ProductionTracking key={`${project}:entity:${id}`} project={project} mode={asset ? 'asset' : 'shot'} onlyEntityId={id} state={prod.state} setState={prod.setState} selection={selection} setSelection={setSelection} loading={prod.loading}
          onEdit={() => setDialog('edit')} onNew={openCreate} onSettings={() => setPendingSpec({ task: 'SETTINGS' })} onOpenEntity={openEntity}
          onOpenDetail={(sel, task, subtask) => { setSelection(sel); setPendingSpec({ task: task.name, subtask }) }} />
      }}
      timeline={mode === 'shot' ? <div style={{ flex: 1, overflow: 'auto' }}><ProductionShot state={prod.state} setState={prod.setState} selection={selection} setSelection={setSelection} onEntityClicked={() => setDialog('edit')} onCreate={openCreate} /></div> : undefined} />
    {dialog === 'new' && <NewProductionDialog key={`${project}:${mode}:${createKind ?? ''}`} initialKind={createKind} project={project} mode={mode} state={prod.state} setState={prod.setState} selection={selection} setSelection={setSelection} onClose={() => setDialog(null)} />}
    <Dialog.Root open={dialog === 'edit'} onOpenChange={open => { if (!open) setDialog(null) }}><Dialog.Portal><Dialog.Overlay className="production-dialog-overlay" /><Dialog.Content className="production-dialog production-entity-dialog">
      <div className="production-dialog-heading"><Dialog.Title>Éditer l’entité</Dialog.Title><Dialog.Close aria-label="Fermer"><X size={16} /></Dialog.Close></div><Dialog.Description>Configuration de l’entité sélectionnée</Dialog.Description>
      <MenuEdit project={project} state={prod.state} setState={prod.setState} selection={selection} setSelection={setSelection} mode={selection.kind === 'asset' || selection.kind === 'group' ? 'asset' : 'shot'} activeCategory={null} publishesByTask={prod.publishesByTask} sequencesOnDisk={prod.sequencesOnDisk} shotsOnDisk={prod.shotsOnDisk} />
    </Dialog.Content></Dialog.Portal></Dialog.Root>
  </div>
}
