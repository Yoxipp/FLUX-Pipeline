// portTypes.ts — port types of the Flows (01_ARCHITECTURE §3): colour and shape.
// P4: TS mirror of backend/flux_flows/types.py (SCALARS, IMPLICIT, can_connect) for the
// check while dragging a link (03 §5); the backend validation stays the reference.
// backend/tests/flux_flows/test_catalog_types.py keeps SCALARS / IMPLICIT equal to types.py.
// One editor choice (P4 decision): an output still typed `any` is not checked (no false
// refusal: its real type is only known at run time).

import type { FlowDocLink, FlowViewNode, PortType } from './types'

export const SCALARS = ['exec', 'any', 'bool', 'int', 'float', 'str', 'path', 'dir', 'dict', 'publish', 'dcc_node', 'pattern'] as const

// Direct implicit conversions; the closure (dir -> path -> str) is transitive.
export const IMPLICIT: Record<string, string[]> = {
  int: ['float'],
  str: ['any'],
  path: ['str'],
  dir: ['path', 'str'],
  dict: ['any'],
  publish: ['dict', 'any'],
  dcc_node: ['str'],
  pattern: ['str'],
}

type Advice = [string, string]
const ADVICE: Record<string, Advice> = {
  'int>bool': ['un nombre n\'est pas un booleen : utilise Compare', 'a number is not a boolean: use Compare'],
  'float>bool': ['un nombre n\'est pas un booleen : utilise Compare', 'a number is not a boolean: use Compare'],
  'float>int': ['perte des decimales : utilise Math (round)', 'decimals would be lost: use Math (round)'],
  'str>path': ['un texte n\'est pas un chemin : passe par un node Path', 'a text is not a path: go through a Path node'],
  'str>dir': ['un texte n\'est pas un chemin : passe par un node Path', 'a text is not a path: go through a Path node'],
  'int>str': ['utilise Template ou StrFormat', 'use Template or StrFormat'],
  'float>str': ['utilise Template ou StrFormat', 'use Template or StrFormat'],
  'path>dir': ['un chemin peut etre un fichier : prends la sortie dir de PathJoin ou de Path, ou parent de PathSplit pour le dossier d\'un fichier', 'a path can be a file: take the dir output of PathJoin or Path, or parent of PathSplit for the folder of a file'],
  'dict>*': ['utilise JsonValue pour lire une cle', 'use JsonValue to read a key'],
  'publish>path': ['un publish est un enregistrement : lis son chemin avec PublishFields', 'a publish is a record: read its path with PublishFields'],
  'publish>*': ['un publish est un enregistrement : lis ses champs avec PublishFields ou PublishInfos', 'a publish is a record: read its fields with PublishFields or PublishInfos'],
  'str>dcc_node': ['un texte n\'est pas un node : utilise houFindNode / mayFindNodes', 'a text is not a node: use houFindNode / mayFindNodes'],
  'str>pattern': ['un texte libre n\'est pas verifie comme motif : saisis-le dans le champ du node', 'a free text is not checked as a pattern: type it in the node field'],
}

export interface Connection { status: 'ok' | 'implicit' | 'incompatible'; reason_fr: string; reason_en: string; fix: string | null }

const LIST_RE = /^list\[(.+)\]$/
const SESSION_RE = /^session\[([a-z*][a-z0-9_]*|\*)\]$/

export function isValidType(t: string): boolean {
  if ((SCALARS as readonly string[]).includes(t) || SESSION_RE.test(t)) return true
  const inner = LIST_RE.exec(t)
  return !!inner && inner[1] !== 'exec' && isValidType(inner[1])
}

const base = (t: string) => LIST_RE.test(t) ? 'list' : SESSION_RE.test(t) ? 'session' : t
const soft = (t: string) => SESSION_RE.exec(t)?.[1] ?? ''
const label = (t: string, fr: boolean) => {
  const inner = LIST_RE.exec(t)
  return inner ? (fr ? `une liste de ${inner[1]}` : `a list of ${inner[1]}`) : t
}

function reaches(src: string, dst: string): boolean {
  const seen = new Set<string>()
  const todo = [src]
  while (todo.length) {
    for (const nxt of IMPLICIT[todo.pop()!] ?? []) {
      if (nxt === dst) return true
      if (!seen.has(nxt)) { seen.add(nxt); todo.push(nxt) }
    }
  }
  return false
}

const OK: Connection = { status: 'ok', reason_fr: '', reason_en: '', fix: null }
const IMPLICIT_OK: Connection = { status: 'implicit', reason_fr: '', reason_en: '', fix: null }
const bad = (src: string, dst: string, fr: string, en: string, fix: string | null = null): Connection => ({
  status: 'incompatible', fix,
  reason_fr: `${label(src, true)} ne va pas dans ${label(dst, true)} : ${fr}`,
  reason_en: `${label(src, false)} does not go into ${label(dst, false)}: ${en}`,
})

// Can an output of type src feed an input of type dst? (types.py can_connect)
export function canConnect(src: PortType, dst: PortType): Connection {
  if (!isValidType(src) || !isValidType(dst)) return bad(src, dst, 'type inconnu', 'unknown type')
  if (src === dst) return OK
  if (src === 'exec' || dst === 'exec') {
    return bad(src, dst, 'un lien d\'execution relie seulement deux ports d\'execution', 'an execution link only joins two execution ports')
  }
  if (dst === 'any') return IMPLICIT_OK
  const sb = base(src), db = base(dst)
  if (sb === 'session' && db === 'session') {
    return soft(dst) === '*' ? IMPLICIT_OK : bad(src, dst, `ajoute un node Instance ${soft(dst)}`, `add a ${soft(dst)} Instance node`)
  }
  if (sb === 'list' && db === 'list') {
    return canConnect(LIST_RE.exec(src)![1], LIST_RE.exec(dst)![1]).status !== 'incompatible'
      ? IMPLICIT_OK : bad(src, dst, 'les elements ne vont pas ensemble', 'the items do not match')
  }
  if (sb === 'list') return bad(src, dst, 'mets un ForEach', 'add a ForEach', LIST_RE.exec(src)![1] === dst ? 'insert_foreach' : null)
  if (db === 'list' && LIST_RE.exec(dst)![1] === src) return bad(src, dst, 'ajoute un node ListAppend', 'add a ListAppend node')
  if (reaches(sb, db)) return IMPLICIT_OK
  const advice = ADVICE[`${sb}>${db}`] ?? ADVICE[`${sb}>*`]
  if (advice) return bad(src, dst, ...advice)
  if (sb === 'any') return bad(src, dst,
    'la sortie est de type any (connu seulement au run) : choisis le type de la source (Value : reglage type) ou passe par un node de conversion (Path, Template, Compare)',
    'the output is of type any (only known at run time): set the source type (Value: type setting) or go through a conversion node (Path, Template, Compare)')
  return bad(src, dst, 'ajoute un node de conversion', 'add a conversion node')
}

// The editor's rule while dragging: same as canConnect, except an `any` output is let
// through (the validation does not check it either).
export function editorConnect(src: PortType, dst: PortType): Connection {
  if (src === 'any' && dst !== 'exec') return IMPLICIT_OK
  return canConnect(src, dst)
}

// First port of a catalogue node that a dragged port of `type` on `side` can link to
// (the Tab menu opened by dropping a link in the void, 03 §4). null = none.
export function firstCompatible(spec: { inputs: { name: string; type: string }[]; params: { name: string; type: string }[]; outputs: { name: string; type: string }[] },
                                type: PortType, side: 'in' | 'out'): string | null {
  const ok = (src: string, dst: string) => (src === 'exec') === (dst === 'exec') && editorConnect(src, dst).status !== 'incompatible'
  if (side === 'out') {
    const ins = [...spec.inputs, ...spec.params]
    return ins.find(p => ok(type, p.type) && (type !== 'exec' || p.name === 'exec'))?.name ?? null
  }
  return spec.outputs.find(p => ok(p.type, type))?.name ?? null
}

// A port end while dragging a link: node id, port name, side.
export interface PortEnd { node: string; port: string; side: 'in' | 'out' }

const portOf = (nodes: Record<string, FlowViewNode>, e: PortEnd) =>
  (e.side === 'in' ? nodes[e.node]?.inputs : nodes[e.node]?.outputs)?.find(p => p.name === e.port)
    ?? (e.side === 'in' && e.port === 'exec' && nodes[e.node]?.hasExec ? { name: 'exec', type: 'exec' }
      : e.side === 'out' && e.port === 'then' && nodes[e.node]?.hasExec ? { name: 'then', type: 'exec' } : undefined)

// Is a link from `a` to `b` (either order) accepted while dragging (03 §5)? Refused: same
// node, two inputs or two outputs, exec <-> data, incompatible types, a 2nd link on an exec
// output ("Plusieurs suites : utilise Sequence"). A data input already linked is accepted:
// the new link replaces the old one (reducers.connect).
export function checkLink(nodes: Record<string, FlowViewNode>, links: FlowDocLink[], a: PortEnd, b: PortEnd): Connection & { from?: string; to?: string } {
  const refuse = (fr: string, en: string): Connection => ({ status: 'incompatible', reason_fr: fr, reason_en: en, fix: null })
  if (a.side === b.side) return refuse('Relie une sortie a une entree.', 'Link an output to an input.')
  const [src, dst] = a.side === 'out' ? [a, b] : [b, a]
  if (src.node === dst.node) return refuse('Un node ne se relie pas a lui-meme.', 'A node does not link to itself.')
  const sp = portOf(nodes, src), dp = portOf(nodes, dst)
  if (!sp || !dp) return refuse('Port inconnu.', 'Unknown port.')
  const from = `${src.node}.${src.port}`, to = `${dst.node}.${dst.port}`
  if (sp.type === 'exec' && dp.type === 'exec') {
    if (links.some(l => l.from === from && l.to !== to)) {
      return refuse('Plusieurs suites : utilise Sequence.', 'Several next steps: use Sequence.')
    }
    return { ...OK, from, to }
  }
  const c = editorConnect(sp.type, dp.type)
  return { ...c, from, to }
}

export type PortShape = 'triangle' | 'circle' | 'square' | 'diamond' | 'ring' | 'hollow'

// Base of a type: "list[path]" -> "path", "session[maya]" -> "session".
export function baseType(t: PortType): string {
  const list = /^list\[(.+)\]$/.exec(t)
  if (list) return baseType(list[1])
  return t.replace(/\[.*\]$/, '')
}

export function portColor(t: PortType): string {
  return `var(--port-${baseType(t)}, var(--port-any))`
}

export function portShape(t: PortType): PortShape {
  if (t === 'exec') return 'triangle'
  if (t === 'any') return 'hollow'
  if (t.startsWith('list[')) return 'square'
  if (t === 'dict' || t === 'publish') return 'diamond'
  if (t.startsWith('session') || t === 'dcc_node') return 'ring'
  return 'circle'
}

const KNOWN = new Set(['exec', 'any', 'bool', 'int', 'float', 'str', 'path', 'dir', 'dict', 'publish', 'dcc_node', 'pattern'])

// A v1 parameter type ("string", "list", "folder"...) -> a v2 port type; unknown = any.
export function toPortType(raw: string | undefined): PortType {
  const t = (raw ?? '').trim().toLowerCase()
  const alias: Record<string, string> = {
    string: 'str', text: 'str', boolean: 'bool', integer: 'int', number: 'float',
    file: 'path', folder: 'dir', directory: 'dir', list: 'list[any]', json: 'dict',
  }
  const v = alias[t] ?? t
  if (KNOWN.has(v) || /^(list|session)\[.+\]$/.test(v)) return v
  return 'any'
}
