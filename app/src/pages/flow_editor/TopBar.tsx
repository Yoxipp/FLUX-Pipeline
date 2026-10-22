// TopBar.tsx — top bar of the Flows editor (03_EDITEUR §1, 44 px), like a DCC file menu
// (ADR 0058): File > New, Open (flows by category: Pipe = shipped + team, Project, Perso),
// Save, Save as, Save and Increment, Migrate v1 actions (Team TD). Then the network tools
// (backdrop, subnet, sticky note), the view toggles (background dots, wire style), search
// and the way to the old editor. P1: the graph is read-only (editing comes with P4), Save
// rewrites the loaded document. P2: Run (the open document, no version created), Essai a
// blanc (the saved file), Stop, and the Runs dock toggle (03_EDITEUR §7).

import * as Menu from '@radix-ui/react-dropdown-menu'
import { ArrowUpFromLine, ChevronDown, ChevronRight, FilePlus, FlaskConical, FolderOpen, Grid3x3, History, ListChecks, Play, Save, Spline, Square, BoxSelect, StickyNote, Boxes } from 'lucide-react'
import type { FlowCategory, FlowScope } from './types'
import { useTr } from './useTr'
import './flow_editor.css'

export interface FlowListEntry { name: string; scope: FlowScope; category: FlowCategory; legacy: boolean; shadowed: boolean }

export interface FileActions {
  onNew: () => void
  onOpen: (entry: FlowListEntry) => void
  onSave: () => void
  onSaveAs: () => void
  onIncrement: () => void
  onMigrate: () => void
}

export interface RunActions {
  running: boolean
  runBlocked?: string         // why Run is greyed (no box, no flow...)
  dryBlocked?: string         // why Essai a blanc is greyed
  runsOpen: boolean
  onRun: () => void
  onDry: () => void
  onStop: () => void
  onToggleRuns: () => void
}

export function TopBar({ flows, current, scope, version, legacy, showPerso, saveBlocked, canMigrate, search, dots, straight, actions, run, onSearch, onToggleDots, onToggleWires, onLegacy }: {
  flows: FlowListEntry[]
  current: string
  scope?: FlowScope
  version?: number
  legacy: boolean
  showPerso: boolean
  saveBlocked?: string        // why Save / Increment are greyed (no box, shipped flow...)
  canMigrate: boolean
  search: string
  dots: boolean
  straight: boolean
  actions: FileActions
  run: RunActions
  onSearch: (s: string) => void
  onToggleDots: () => void
  onToggleWires: () => void
  onLegacy: () => void
}) {
  const { tr } = useTr()
  const p4 = tr('Arrive avec l\'edition (P4)', 'Comes with editing (P4)')
  const groups: { key: FlowCategory; label: string }[] = [
    { key: 'pipe', label: tr('Pipe', 'Pipe') },
    { key: 'project', label: tr('Projet', 'Project') },
    ...(showPerso ? [{ key: 'perso' as const, label: tr('Perso', 'Personal') }] : []),
  ]
  const scopeTag: Record<FlowScope, string> = {
    shipped: tr('livre', 'shipped'), team: tr('equipe', 'team'), project: tr('projet', 'project'), perso: tr('perso', 'personal'),
  }
  return (
    <div style={{ height: 44, flexShrink: 0, display: 'flex', alignItems: 'center', gap: 6, padding: '0 10px', borderBottom: '1px solid var(--rule)', background: 'var(--paper)' }}>
      <Menu.Root modal={false}>
        <Menu.Trigger asChild>
          <button type="button" className="flow-tool">{tr('Fichier', 'File')} <ChevronDown size={12} /></button>
        </Menu.Trigger>
        <Menu.Portal>
          <Menu.Content className="flow-menu" align="start" sideOffset={4} collisionPadding={10}>
            <Menu.Item className="flow-menu-item" onSelect={actions.onNew}><FilePlus size={13} /> {tr('Nouveau', 'New')}<span className="shortcut">Ctrl+N</span></Menu.Item>
            <Menu.Sub>
              <Menu.SubTrigger className="flow-menu-item"><FolderOpen size={13} /> {tr('Ouvrir', 'Open')}<ChevronRight size={12} style={{ marginLeft: 'auto' }} /></Menu.SubTrigger>
              <Menu.Portal>
                <Menu.SubContent className="flow-menu" sideOffset={4} collisionPadding={10} style={{ maxHeight: 420, overflowY: 'auto' }}>
                  {groups.map(g => {
                    // A name shadowed by a narrower scope (perso > project > team > shipped) is not listed.
                    const list = flows.filter(f => f.category === g.key && !f.shadowed)
                    return (
                      <div key={g.key}>
                        <Menu.Label className="flow-menu-label">{g.label}</Menu.Label>
                        {list.length === 0 && <Menu.Item className="flow-menu-item" disabled>{tr('Aucun flow', 'No flow')}</Menu.Item>}
                        {list.map(f => (
                          <Menu.Item key={`${f.scope}:${f.name}`} className="flow-menu-item" onSelect={() => actions.onOpen(f)}>
                            {f.name}
                            {g.key === 'pipe' && f.scope === 'team' && <span className="tag">{tr('equipe', 'team')}</span>}
                            {f.name === current && <span className="shortcut">{tr('ouvert', 'open')}</span>}
                          </Menu.Item>
                        ))}
                      </div>
                    )
                  })}
                </Menu.SubContent>
              </Menu.Portal>
            </Menu.Sub>
            <Menu.Separator className="flow-menu-sep" />
            <Menu.Item className="flow-menu-item" disabled={!!saveBlocked} title={saveBlocked} onSelect={actions.onSave}><Save size={13} /> {tr('Enregistrer', 'Save')}<span className="shortcut">Ctrl+S</span></Menu.Item>
            <Menu.Item className="flow-menu-item" disabled={!current} onSelect={actions.onSaveAs}>{tr('Enregistrer sous…', 'Save as…')}<span className="shortcut">Ctrl+Maj+S</span></Menu.Item>
            <Menu.Item className="flow-menu-item" disabled={!!saveBlocked} title={saveBlocked} onSelect={actions.onIncrement}>{tr('Enregistrer et incrementer', 'Save and increment')}<span className="shortcut">Alt+Maj+S</span></Menu.Item>
            <Menu.Separator className="flow-menu-sep" />
            <Menu.Item className="flow-menu-item" disabled={!canMigrate} title={canMigrate ? undefined : tr('Case Team TD requise', 'Team TD box required')} onSelect={actions.onMigrate}>
              <ArrowUpFromLine size={13} /> {tr('Migrer les actions v1…', 'Migrate v1 actions…')}
            </Menu.Item>
            <Menu.Item className="flow-menu-item" onSelect={onLegacy}><History size={13} /> {tr('Ancien editeur', 'Old editor')}</Menu.Item>
          </Menu.Content>
        </Menu.Portal>
      </Menu.Root>

      <span style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--ink)', marginLeft: 4 }}>{current || '…'}</span>
      {scope && <span className="tag">{scopeTag[scope]}</span>}
      {!!version && <span className="tag">v{String(version).padStart(3, '0')}</span>}
      {legacy && <span className="tag">v1</span>}
      <span className="tag" title={p4}>{tr('lecture seule', 'read-only')}</span>

      <div style={{ width: 1, height: 20, background: 'var(--rule)', margin: '0 6px' }} />
      {run.running
        ? <button type="button" className="flow-tool" onClick={run.onStop} title={tr('Annuler le run en cours', 'Cancel the running run')}><Square size={13} /> Stop</button>
        : <button type="button" className="flow-tool" disabled={!!run.runBlocked} onClick={run.onRun}
                  title={run.runBlocked ?? tr('Lance le document ouvert (aucune version creee)', 'Runs the open document (no version created)')}>
            <Play size={13} /> Run
          </button>}
      <button type="button" className="flow-tool" disabled={run.running || !!run.dryBlocked} onClick={run.onDry}
              title={run.dryBlocked ?? tr('Essai a blanc du fichier enregistre : rien n\'est ecrit, aucun logiciel lance', 'Dry run of the saved file: nothing written, no software started')}>
        <FlaskConical size={13} /> {tr('Essai', 'Dry run')}
      </button>
      <button type="button" className={`flow-tool${run.runsOpen ? ' on' : ''}`} onClick={run.onToggleRuns} title={tr('Historique des runs', 'Run history')}>
        <ListChecks size={13} /> Runs
      </button>

      <div style={{ width: 1, height: 20, background: 'var(--rule)', margin: '0 6px' }} />
      <button type="button" className="flow-tool" disabled title={p4}><BoxSelect size={13} /> Backdrop</button>
      <button type="button" className="flow-tool" disabled title={p4}><Boxes size={13} /> Subnet</button>
      <button type="button" className="flow-tool" disabled title={p4}><StickyNote size={13} /> {tr('Note', 'Sticky note')}</button>

      <div style={{ flex: 1 }} />
      <button type="button" className={`flow-tool${dots ? ' on' : ''}`} onClick={onToggleDots} title={tr('Points du fond', 'Background dots')}>
        <Grid3x3 size={13} />
      </button>
      <button type="button" className={`flow-tool${straight ? ' on' : ''}`} onClick={onToggleWires} title={tr('Liens droits ou courbes (Maj+S)', 'Straight or curved wires (Shift+S)')}>
        <Spline size={13} /> {straight ? tr('Droits', 'Straight') : tr('Courbes', 'Curved')}
      </button>
      <input
        value={search} onChange={e => onSearch(e.target.value)}
        placeholder={tr('Chercher dans le flow', 'Search in the flow')}
        style={{ fontSize: 12, padding: '4px 8px', background: 'var(--paper-2)', border: '1px solid var(--rule-2)', borderRadius: 5, color: 'var(--ink)', outline: 'none', fontFamily: 'var(--sans)', width: 190 }}
      />
    </div>
  )
}
