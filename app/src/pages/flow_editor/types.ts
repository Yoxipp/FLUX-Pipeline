// types.ts — TS types of the Flows editor (03_EDITEUR §9). P0 holds the view model
// only; FlowDoc / FlowLink / Issue / RunRecord arrive with the v2 format (P1+).

// GET /flows/rights (01 §7): TD / Team TD boxes of the current user. A guard, not security.
export type FlowScope = 'perso' | 'project' | 'team' | 'shipped'
export interface FlowRights {
  user:    string | null
  td:      boolean
  team_td: boolean
  can:     Record<FlowScope, { write: boolean; draft: boolean; admin: boolean }>
  note_fr: string
  note_en: string
}

export type Family =
  | 'event' | 'data' | 'logic' | 'operator' | 'action'
  | 'flux' | 'session' | 'dcc' | 'bridge' | 'subflow'

// "exec", "any", "bool", "int", "float", "str", "path", "dir", "list[T]", "dict",
// "session[<soft>]", "publish", "dcc_node", "pattern".
export type PortType = string

export interface PortSpec {
  name:     string
  type:     PortType
  required?: boolean
  doc_fr?:  string
  doc_en?:  string
  example?: string
  value?:   unknown       // literal value of an input (shown greyed)
  wiredFrom?: string      // "<node label>.<port>" when the input is linked
}

// One node as the editor draws it.
export interface FlowViewNode {
  id:       string
  type:     string        // registry type id ("flux.legacy_command" for v1)
  label:    string
  family:   Family
  icon?:    string
  prefix?:  string        // DCC prefix badge: hou, may...
  doc_fr?:  string
  doc_en?:  string
  hasExec:  boolean       // exec in + then out
  inputs:   PortSpec[]
  outputs:  PortSpec[]
  position: { x: number; y: number }
  meta?:    Record<string, string>   // shown in Params (step, module...)
}

export interface FlowViewEdge {
  id:     string
  kind:   'exec' | 'data'
  source: string
  sourcePort: string
  target: string
  targetPort: string
  type:   PortType
}

export interface FlowView {
  name:  string
  description?: string
  nodes: FlowViewNode[]
  edges: FlowViewEdge[]
  readOnly: boolean
  origin?: string
}

// -- v2 format and store (01 §2, §6, §14, ADR 0058) -----------------------------

export type FlowCategory = 'pipe' | 'project' | 'perso'

export interface FlowDocNode {
  type:    string
  pos?:    [number, number]
  params?: Record<string, unknown>
  label?:  string
  bypass?: boolean
  nodes?:  Record<string, FlowDocNode>   // subnet only
  links?:  FlowDocLink[]
}

export interface FlowDocLink { from: string; to: string }

export interface FlowOrigin {
  kind: 'v1'
  name: string
  shelf?: string
  thumbnail?: string
  extends?: string
  params?: Record<string, Record<string, unknown>>
}

export interface FlowDoc {
  flux_flow:   2
  name:        string
  label?:      string
  description?: string
  run_policy?: 'skip_if_running' | 'queue'
  origin?:     FlowOrigin
  node_type?:  string
  interface?:  unknown
  variables?:  unknown[]
  nodes:       Record<string, FlowDocNode>
  links:       FlowDocLink[]
  groups?:     unknown[]
  notes?:      { id: string; pos: [number, number]; text: string }[]
}

// state.json of a flow (store.py): current = last frozen version (0 = none).
export interface FlowState {
  current:        number
  active_version: number | null
  active:         boolean
  revision:       number
  saved_by?:      string | null
  saved_at?:      string | null
}

// GET /flows entry.
export interface FlowListItem {
  name:        string
  scope:       FlowScope
  category:    FlowCategory
  label:       string
  description: string
  legacy:      boolean
  shadowed:    boolean
  origin:      FlowOrigin | null
  error:       string | null
  current?:    number
  active?:     boolean
  revision?:   number
}

// GET /flows/{name}.
export interface FlowRead {
  name:     string
  scope:    FlowScope
  category: FlowCategory
  version:  number | null
  flow:     FlowDoc
  state:    FlowState
  legacy:   boolean
  issues:   { code: string; node?: string; message?: string }[]
}

export interface MigrateReport {
  dry_run: boolean
  actions: { action: string; flow: string; status: string; nodes?: number; error?: string | null;
             unknown_commands?: string[]; unresolved_links?: string[] }[]
  nodes:   { file: string; status: string }[]
}
