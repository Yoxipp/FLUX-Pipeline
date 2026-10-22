// TopBar.tsx — top bar of the Flows editor (03_EDITEUR §1, 44 px), like a DCC file menu
// (2026-10-22): File > New, Open (flows of the Pipe and of the Project, by category),
// Save, Save as, Save and Increment. Then the network tools (backdrop, subnet, sticky note),
// the view toggles (background dots, wire style), search and the way to the old editor.
// P0: Open works (v1 actions = Pipe); writing comes with the v2 store (P1) and editing (P4).

import * as Menu from '@radix-ui/react-dropdown-menu'
import { ChevronDown, ChevronRight, FilePlus, FolderOpen, Grid3x3, History, Save, Spline, BoxSelect, StickyNote, Boxes } from 'lucide-react'
import { useTr } from './useTr'
import './flow_editor.css'

export interface FlowListEntry { name: string; category: 'pipe' | 'project' }

export function TopBar({ flows, current, origin, search, dots, straight, onSearch, onOpen, onToggleDots, onToggleWires, onLegacy }: {
  flows: FlowListEntry[]
  current: string
  origin?: string
  search: string
  dots: boolean
  straight: boolean
  onSearch: (s: string) => void
  onOpen: (name: string) => void
  onToggleDots: () => void
  onToggleWires: () => void
  onLegacy: () => void
}) {
  const { tr } = useTr()
  const p1 = tr('Arrive avec le stockage des flows (P1)', 'Comes with the flow store (P1)')
  const p4 = tr('Arrive avec l\'edition (P4)', 'Comes with editing (P4)')
  const groups: { key: FlowListEntry['category']; label: string }[] = [
    { key: 'pipe', label: tr('Pipe', 'Pipe') },
    { key: 'project', label: tr('Projet', 'Project') },
  ]
  return (
    <div style={{ height: 44, flexShrink: 0, display: 'flex', alignItems: 'center', gap: 6, padding: '0 10px', borderBottom: '1px solid var(--rule)', background: 'var(--paper)' }}>
      <Menu.Root modal={false}>
        <Menu.Trigger asChild>
          <button type="button" className="flow-tool">{tr('Fichier', 'File')} <ChevronDown size={12} /></button>
        </Menu.Trigger>
        <Menu.Portal>
          <Menu.Content className="flow-menu" align="start" sideOffset={4} collisionPadding={10}>
            <Menu.Item className="flow-menu-item" disabled title={p1}><FilePlus size={13} /> {tr('Nouveau', 'New')}<span className="shortcut">Ctrl+N</span></Menu.Item>
            <Menu.Sub>
              <Menu.SubTrigger className="flow-menu-item"><FolderOpen size={13} /> {tr('Ouvrir', 'Open')}<ChevronRight size={12} style={{ marginLeft: 'auto' }} /></Menu.SubTrigger>
              <Menu.Portal>
                <Menu.SubContent className="flow-menu" sideOffset={4} collisionPadding={10} style={{ maxHeight: 420, overflowY: 'auto' }}>
                  {groups.map(g => {
                    const list = flows.filter(f => f.category === g.key)
                    return (
                      <div key={g.key}>
                        <Menu.Label className="flow-menu-label">{g.label}</Menu.Label>
                        {list.length === 0 && (
                          <Menu.Item className="flow-menu-item" disabled>
                            {g.key === 'project' ? tr('Aucun flow de projet (P1)', 'No project flow (P1)') : tr('Aucun flow', 'No flow')}
                          </Menu.Item>
                        )}
                        {list.map(f => (
                          <Menu.Item key={f.name} className="flow-menu-item" onSelect={() => onOpen(f.name)}>
                            {f.name}{f.name === current && <span className="shortcut">{tr('ouvert', 'open')}</span>}
                          </Menu.Item>
                        ))}
                      </div>
                    )
                  })}
                </Menu.SubContent>
              </Menu.Portal>
            </Menu.Sub>
            <Menu.Separator className="flow-menu-sep" />
            <Menu.Item className="flow-menu-item" disabled title={p1}><Save size={13} /> {tr('Enregistrer', 'Save')}<span className="shortcut">Ctrl+S</span></Menu.Item>
            <Menu.Item className="flow-menu-item" disabled title={p1}>{tr('Enregistrer sous…', 'Save as…')}<span className="shortcut">Ctrl+Maj+S</span></Menu.Item>
            <Menu.Item className="flow-menu-item" disabled title={p1}>{tr('Enregistrer et incrementer', 'Save and increment')}<span className="shortcut">Alt+Maj+S</span></Menu.Item>
            <Menu.Separator className="flow-menu-sep" />
            <Menu.Item className="flow-menu-item" onSelect={onLegacy}><History size={13} /> {tr('Ancien editeur', 'Old editor')}</Menu.Item>
          </Menu.Content>
        </Menu.Portal>
      </Menu.Root>

      <span style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--ink)', marginLeft: 4 }}>{current || '…'}</span>
      <span className="tag">v1</span>
      {origin === 'equipe' && <span className="tag">{tr('equipe', 'team')}</span>}
      <span className="tag" title={p4}>{tr('lecture seule', 'read-only')}</span>

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
