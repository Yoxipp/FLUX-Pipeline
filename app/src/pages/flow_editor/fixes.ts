// fixes.ts — "Corriger" of the Problems panel (03_EDITEUR §5): one reducer per fix kind of
// validate.py (01 §8), pure, applied as one undo entry. A node inserted by a fix sits in
// the middle of the link (or beside its node) and pushes nothing (no relayout, 03 §4).
// Exec rewiring: "insert before" redirects every link into <node>.exec to the new node,
// whose `then` (or `loop`) feeds <node>.exec. Returns null when the fix cannot apply
// (node type missing from the catalogue: the nodes of P5 / P6).

import { addNode, connect, disconnect, EXEC_IN, nextNodeId, nodeOfRef, setParam, splitRef } from './reducers'
import type { FlowDoc, Issue, NodeSpec } from './types'

type Specs = Record<string, NodeSpec>

const FOREACH_BEGIN = 'operator.foreach_begin'
const FOREACH_END = 'operator.foreach_end'
const SET_VARIABLE = 'data.set_variable'
const BLOCK_ENDS: Record<string, string> = {
  'operator.foreach_begin': 'operator.foreach_end',
  'operator.for_begin': 'operator.for_end',
  'operator.while_begin': 'operator.while_end',
}

const posOf = (doc: FlowDoc, id: string): [number, number] => doc.nodes[id]?.pos ?? [0, 0]
const mid = (a: [number, number], b: [number, number]): [number, number] => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]
const hasExecIn = (specs: Specs, doc: FlowDoc, id: string) => !!specs[doc.nodes[id]?.type]?.inputs.some(p => p.name === EXEC_IN)

// Every link into <target>.exec now goes to <id>.exec; <id>.<out> -> <target>.exec.
function insertBefore(doc: FlowDoc, id: string, target: string, out = 'then'): FlowDoc {
  const into = doc.links.filter(l => l.to === `${target}.${EXEC_IN}`)
  let next = disconnect(doc, into)
  for (const l of into) next = connect(next, l.from, `${id}.${EXEC_IN}`)
  return connect(next, `${id}.${out}`, `${target}.${EXEC_IN}`)
}

// <target>.then -> <id>.exec; the old successor of <target>.then hangs on <id>.<out>.
function insertAfter(doc: FlowDoc, id: string, target: string, out: string): FlowDoc {
  const from = `${target}.then`
  const old = doc.links.filter(l => l.from === from)
  let next = disconnect(doc, old)
  next = connect(next, from, `${id}.${EXEC_IN}`)
  for (const l of old) next = connect(next, `${id}.${out}`, l.to)
  return next
}

// Last node of the exec chain starting at <from> (stops on a loop back).
function chainEnd(doc: FlowDoc, from: string): string | null {
  const seen = new Set<string>()
  let cur: string | null = null
  let ref = from
  for (;;) {
    const l = doc.links.find(x => x.from === ref && splitRef(x.to)[1] === EXEC_IN)
    if (!l) return cur
    const n = nodeOfRef(l.to)
    if (seen.has(n)) return cur
    seen.add(n)
    cur = n
    ref = `${n}.then`
  }
}

function leftOfAll(doc: FlowDoc): [number, number] {
  const ps = Object.values(doc.nodes).map(n => n.pos ?? [0, 0])
  if (!ps.length) return [0, 0]
  return [Math.min(...ps.map(p => p[0])) - 300, Math.min(...ps.map(p => p[1]))]
}

export function applyFix(doc: FlowDoc, issue: Issue, specs: Specs): { doc: FlowDoc; select?: string } | null {
  const fix = issue.fix
  if (!fix) return null
  const a = fix.args as Record<string, string>
  const need = (type: string) => !!specs[type]
  switch (fix.kind) {
    case 'remove_link':
      return { doc: disconnect(doc, [{ from: a.from, to: a.to }]) }

    case 'remove_node': {
      const id = a.node
      if (!doc.nodes[id]) return null
      const nodes = { ...doc.nodes }
      delete nodes[id]
      return { doc: { ...doc, nodes, links: doc.links.filter(l => nodeOfRef(l.from) !== id && nodeOfRef(l.to) !== id),
                      ...(doc.groups ? { groups: doc.groups.map(g => ({ ...g, nodes: g.nodes.filter(n => n !== id) })) } : {}) } }
    }

    case 'set_param':
      return { doc: setParam(doc, a.node, a.param, fix.args.value) }

    case 'set_instance_mode':
      return { doc: setParam(doc, a.node, 'mode', a.mode) }

    case 'replace_token': {
      const cur = doc.nodes[a.node]?.params?.[a.param]
      if (typeof cur !== 'string' || !a.suggestion) return null
      return { doc: setParam(doc, a.node, a.param, cur.split(a.token).join(a.suggestion)) }
    }

    case 'add_node': {
      if (!need(a.type)) return null
      const id = nextNodeId(doc)
      return { doc: addNode(doc, id, { type: a.type, pos: leftOfAll(doc), params: {} }), select: id }
    }

    case 'insert_foreach': {
      if (!need(FOREACH_BEGIN) || !need(FOREACH_END)) return null
      const [src] = splitRef(a.from)
      const [dst] = splitRef(a.to)
      if (!doc.nodes[src] || !doc.nodes[dst]) return null
      const fe = nextNodeId(doc)
      let next = addNode(doc, fe, { type: FOREACH_BEGIN, pos: mid(posOf(doc, src), posOf(doc, dst)), params: {} })
      next = disconnect(next, [{ from: a.from, to: a.to }])
      next = connect(next, a.from, `${fe}.list`)
      next = connect(next, `${fe}.item`, a.to)
      if (hasExecIn(specs, doc, dst)) {
        const end = nextNodeId(next)
        const d = posOf(doc, dst)
        next = addNode(next, end, { type: FOREACH_END, pos: [d[0] + 300, d[1]], params: { begin: fe } })
        next = insertBefore(next, fe, dst, 'loop')
        next = insertAfter(next, end, dst, 'done')
      }
      return { doc: next, select: fe }
    }

    case 'add_block_end': {
      const type = a.type || BLOCK_ENDS[doc.nodes[a.begin]?.type]
      if (!type || !need(type) || !doc.nodes[a.begin]) return null
      const end = nextNodeId(doc)
      const last = chainEnd(doc, `${a.begin}.loop`)
      const p = posOf(doc, last ?? a.begin)
      let next = addNode(doc, end, { type, pos: [p[0] + 300, p[1]], params: { begin: a.begin } })
      if (last) next = connect(next, `${last}.then`, `${end}.${EXEC_IN}`)
      return { doc: next, select: end }
    }

    case 'add_instance': {
      const type = `session.${a.soft}_instance`
      if (!need(type) || !doc.nodes[a.node]) return null
      const id = nextNodeId(doc)
      const p = posOf(doc, a.node)
      let next = addNode(doc, id, { type, pos: [p[0] - 300, p[1] + 80], params: {} })
      const out = specs[type].outputs.find(o => o.type.startsWith('session'))
      if (out) next = connect(next, `${id}.${out.name}`, `${a.node}.session`)
      if (specs[type].inputs.some(i => i.name === EXEC_IN) && hasExecIn(specs, doc, a.node)) next = insertBefore(next, id, a.node)
      return { doc: next, select: id }
    }

    case 'add_set_variable': {
      if (!need(SET_VARIABLE) || !doc.nodes[a.node]) return null
      const id = nextNodeId(doc)
      const p = posOf(doc, a.node)
      let next = addNode(doc, id, { type: SET_VARIABLE, pos: [p[0] - 300, p[1] - 80], params: { name: a.name } })
      // Written before the reader when it runs in the chain, else right after the start event.
      if (hasExecIn(specs, doc, a.node) && doc.links.some(l => l.to === `${a.node}.${EXEC_IN}`)) next = insertBefore(next, id, a.node)
      else {
        const ev = Object.keys(doc.nodes).find(n => doc.nodes[n].type.startsWith('event.'))
        if (ev) next = insertAfter(next, id, ev, 'then')
      }
      return { doc: next, select: id }
    }
  }
  return null
}

// When an End node is added, pair it with the only unpaired Begin of its kind (the
// `begin` param "set by the editor", operator.py).
export function autoBegin(doc: FlowDoc, endType: string): string | null {
  const beginType = Object.keys(BLOCK_ENDS).find(b => BLOCK_ENDS[b] === endType)
  if (!beginType) return null
  const paired = new Set(Object.values(doc.nodes).filter(n => n.type === endType).map(n => String(n.params?.begin ?? '')))
  const free = Object.keys(doc.nodes).filter(id => doc.nodes[id].type === beginType && !paired.has(id))
  return free.length === 1 ? free[0] : null
}
