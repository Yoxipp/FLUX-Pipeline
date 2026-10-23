// GroupBox.tsx — a box drawn behind a group of nodes (01 §2 `groups`, visual only,
// 03_EDITEUR §4): Ctrl+G groups the selection, the box follows its nodes (its rectangle
// is computed from them), dragging the box moves its nodes, double click on the title
// renames it, Suppr on the selected box removes the box only (not its nodes).
// Colour = a family colour (`color` = family key), the accent by default.

import { memo, useEffect, useState } from 'react'
import type { Node, NodeProps } from '@xyflow/react'
import { FAMILY_INFO } from './families'
import type { Family } from './types'

export const GROUP_PAD = 24
export const GROUP_HEAD = 26

export type GroupData = { label: string; color?: string | null; width: number; height: number; editable: boolean; onRename: (label: string) => void }
// Node type "box", not xyflow's built-in "group" (parent node behaviour).
export type GroupRfNode = Node<GroupData, 'box'>

function GroupView({ data, selected }: NodeProps<GroupRfNode>) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(data.label)
  useEffect(() => { if (!editing) setDraft(data.label) }, [data.label, editing])
  const color = (data.color && FAMILY_INFO[data.color as Family]?.color) || 'var(--accent)'
  const done = () => { setEditing(false); if (draft !== data.label) data.onRename(draft) }
  return (
    <div style={{
      width: data.width, height: data.height, borderRadius: 8,
      background: `color-mix(in oklch, ${color} 9%, transparent)`,
      border: `1px solid color-mix(in oklch, ${color} ${selected ? 70 : 35}%, transparent)`,
    }}>
      <div
        onDoubleClick={() => { if (data.editable) setEditing(true) }}
        style={{ height: GROUP_HEAD, display: 'flex', alignItems: 'center', padding: '0 10px', fontSize: 12, fontWeight: 600, color: 'var(--ink-2)' }}
      >
        {editing
          ? <input autoFocus className="nodrag" value={draft} onChange={e => setDraft(e.target.value)} onBlur={done}
                   onKeyDown={e => { if (e.key === 'Enter' || e.key === 'Escape') { e.stopPropagation(); done() } }}
                   style={{ fontSize: 12, fontWeight: 600, background: 'var(--paper-2)', border: '1px solid var(--rule-2)', borderRadius: 4, color: 'var(--ink)', padding: '1px 5px', outline: 'none' }} />
          : data.label || 'Groupe'}
      </div>
    </div>
  )
}

export const GroupBox = memo(GroupView)
