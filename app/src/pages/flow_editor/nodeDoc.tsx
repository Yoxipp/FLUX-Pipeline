// nodeDoc.tsx — the (i) doc of a node, read from docs/user/flows/03_INDEX_NODES.md (bundled by
// Vite `?raw`, so the installed app needs no file). One section per node: a heading
// "### <type> : <Label>" up to the next ## / ### heading (rules in docs/user/flows/README.md,
// checked by backend/tests/test_flux_flows/test_nodes_doc.py). Plain text only: paragraphs,
// "* " bullets, `code` and **bold**.

import { Fragment, type ReactNode } from 'react'
import indexMd from '../../../../docs/user/flows/03_INDEX_NODES.md?raw'

const NODE_HEADING = /^###\s+([a-z][a-z0-9_]*\.[a-z0-9_]+)\s*:/

function parseSections(md: string): Map<string, string> {
  const out = new Map<string, string>()
  let type: string | null = null
  let lines: string[] = []
  const flush = () => {
    if (type) out.set(type, lines.join('\n').trim())
    type = null
    lines = []
  }
  for (const line of md.split(/\r?\n/)) {
    if (/^#{1,3}\s/.test(line)) {
      flush()
      type = NODE_HEADING.exec(line)?.[1] ?? null
    } else if (type) {
      lines.push(line)
    }
  }
  flush()
  return out
}

const SECTIONS = parseSections(indexMd)

// Section text of a node type, or undefined (team node, v1 command, unknown type).
export const nodeDocSection = (type: string): string | undefined => SECTIONS.get(type)

function inline(text: string): ReactNode[] {
  return text.split(/(`[^`]+`|\*\*[^*]+\*\*)/).map((part, i) => {
    if (part.startsWith('`') && part.endsWith('`') && part.length > 1) {
      return <code key={i} style={{ color: 'var(--ink)', background: 'var(--paper-2)', borderRadius: 3, padding: '0 3px' }}>{part.slice(1, -1)}</code>
    }
    if (part.startsWith('**') && part.endsWith('**') && part.length > 3) {
      return <strong key={i} style={{ color: 'var(--ink)' }}>{part.slice(2, -2)}</strong>
    }
    return <Fragment key={i}>{part}</Fragment>
  })
}

// Paragraphs, bullet lists (a line starting "* "; an indented line continues the bullet)
// and the "Exemple :" paragraph set apart.
export function NodeDocText({ text }: { text: string }) {
  const blocks = text.split(/\n\s*\n/).map(b => b.trim()).filter(Boolean)
  return (
    <>
      {blocks.map((block, i) => {
        const rows = block.split('\n')
        if (rows[0].startsWith('* ')) {
          const items: string[] = []
          for (const row of rows) {
            if (row.startsWith('* ')) items.push(row.slice(2))
            else if (items.length) items[items.length - 1] += ` ${row.trim()}`
          }
          return (
            <ul key={i} style={{ margin: '0 0 6px', paddingLeft: 14 }}>
              {items.map((it, j) => <li key={j} style={{ marginBottom: 2 }}>{inline(it)}</li>)}
            </ul>
          )
        }
        const example = /^Exemple\s*:/.test(block)
        return (
          <p key={i} style={{
            margin: '0 0 6px', ...(example ? { padding: '4px 6px', background: 'var(--paper-2)', borderRadius: 4 } : {}),
          }}>
            {inline(rows.map(r => r.trim()).join(' '))}
          </p>
        )
      })}
    </>
  )
}
