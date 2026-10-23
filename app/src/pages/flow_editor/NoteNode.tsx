// NoteNode.tsx — a sticky note of the flow (01 §2 `notes`, visual only, 03_EDITEUR §4):
// N adds one at the mouse, double click edits the text (Echap or click outside ends,
// one undo entry per editing pause), drag moves it like a node.

import { memo, useEffect, useRef, useState } from 'react'
import type { Node, NodeProps } from '@xyflow/react'

export type NoteData = { text: string; editable: boolean; onText: (text: string) => void }
export type NoteRfNode = Node<NoteData, 'note'>

function NoteView({ data, selected }: NodeProps<NoteRfNode>) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(data.text)
  const area = useRef<HTMLTextAreaElement>(null)
  useEffect(() => { if (!editing) setDraft(data.text) }, [data.text, editing])
  useEffect(() => { if (editing) area.current?.focus() }, [editing])
  const done = () => { setEditing(false); if (draft !== data.text) data.onText(draft) }
  return (
    <div
      onDoubleClick={() => { if (data.editable) setEditing(true) }}
      style={{
        width: 220, minHeight: 60, padding: '8px 10px', fontSize: 11.5, lineHeight: 1.4, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
        color: 'var(--ink)', background: 'color-mix(in oklch, var(--warn) 16%, var(--paper-2))',
        border: `1px solid ${selected ? 'var(--ink-3)' : 'color-mix(in oklch, var(--warn) 40%, var(--rule-2))'}`,
        borderRadius: 6, boxShadow: 'var(--shadow-sm)',
      }}
    >
      {editing
        ? <textarea ref={area} className="nodrag" value={draft} onChange={e => setDraft(e.target.value)} onBlur={done}
                    onKeyDown={e => { if (e.key === 'Escape') { e.stopPropagation(); done() } }}
                    style={{ width: '100%', minHeight: 60, resize: 'vertical', fontSize: 11.5, fontFamily: 'var(--sans)', color: 'var(--ink)', background: 'transparent', border: 'none', outline: 'none' }} />
        : data.text || <span style={{ color: 'var(--ink-4)' }}>Note</span>}
    </div>
  )
}

export const NoteNode = memo(NoteView)
