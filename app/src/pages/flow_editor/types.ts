// types.ts — TS types of the Flows editor (03_EDITEUR §9). P0 holds the view model
// only; FlowDoc / FlowLink / Issue / RunRecord arrive with the v2 format (P1+).
// CatalogPort / PortSpec carry choices (menu), wirable (false = constant param, listed in
// FlowViewNode.constants, never a port) and tokens (project token section menu).

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
  choices?: unknown[]     // allowed values (menu, catalogue order)
  wirable?: boolean       // false = constant param: never a port, edited in Params only
  tokens?:  string        // project token section offered in a menu (CLASS, NAME, SEQ...)
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
  constants?: PortSpec[]  // spec params with wirable false: not drawn, edited in Params
  position: { x: number; y: number }
  meta?:    Record<string, string>   // shown in Params (step, module...)
  spec?:    NodeSpec                 // catalogue entry (P4), absent for unknown / legacy types
  destructive?: boolean              // `!` node (flag true for its params, not bypassed)
}

export interface FlowViewEdge {
  id:     string
  kind:   'exec' | 'data'
  source: string
  sourcePort: string
  target: string
  targetPort: string
  type:   PortType
  conversion?: boolean    // implicit conversion (int -> float...), marked on the link
  bad?:   boolean         // incompatible types (kept, reported by the validation)
}

export interface FlowView {
  name:  string
  description?: string
  nodes: FlowViewNode[]
  edges: FlowViewEdge[]
  groups?: FlowGroup[]
  notes?:  FlowNote[]
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

// Visual only, no effect on execution (01 §2).
export interface FlowGroup { id: string; label?: string; nodes: string[]; color?: string | null }
export interface FlowNote  { id: string; pos: [number, number]; text: string }
export interface FlowVariable { name: string; type: string; default?: unknown }

// interface of a flow (01 §2): the values asked at run time (form, event payload) and the
// outputs a sub-flow returns. Input types: INTERFACE_TYPES of model.py.
export const INTERFACE_TYPES = ['bool', 'int', 'float', 'str', 'path', 'dir', 'pattern', 'list[str]', 'select'] as const
export interface InterfaceInput  { id: string; type: string; label?: string; default?: unknown; options?: unknown[] }
export interface InterfaceOutput { id: string; type: string; label?: string }
export interface FlowInterface   { inputs: InterfaceInput[]; outputs: InterfaceOutput[] }

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
  interface?:  FlowInterface
  variables?:  FlowVariable[]
  nodes:       Record<string, FlowDocNode>
  links:       FlowDocLink[]
  groups?:     FlowGroup[]
  notes?:      FlowNote[]
}

// state.json of a flow (store.py): current = last frozen version (0 = none).
export interface FlowState {
  current:        number
  active_version: number | null
  active:         boolean
  revision:       number
  saved_by?:      string | null
  saved_at?:      string | null
  // P5: dry run passed (activation), warnings read, last Schedule slots.
  dry_run_ok?:    { version: number; run_id: string; nodes_simulated: string[]; at?: string | null } | null
  acked?:         { version: number; items: { code: string; node: string | null; port: string | null }[] } | null
  last_schedule?: Record<string, { slot: string; ran_at: string | null }>
}

// GET /flows/{name}/activation: the three lines of the activation dialog (03 §5), on `current`.
export interface ActivationWarning extends Issue { acked: boolean }
export interface ActivationGate {
  version:        number
  active:         boolean
  active_version: number | null
  legacy:         boolean
  errors:         Issue[]
  warnings:       ActivationWarning[]
  dry_run:        { ok: boolean; run_id: string | null; version: number | null }
  destructive:    string[]          // `!` nodes of the version: Activer becomes a SlideToConfirm
  ready:          boolean
  reason?:        string
}

// GET /flows/host: who runs the shared active flows (host lock, 01 §9).
export interface HostHolder { host: string; user: string | null; pid: number; expires: number }
export interface HostInfo {
  holder:       HostHolder | null
  me:           string | null
  is_holder:    boolean
  since:        number | null
  enabled:      boolean
  running:      boolean
  idle_reason:  string | null
  active_flows: { flow: string; scope: FlowScope; project: string | null; version: number }[]
  watchers:     { flow: string; scope: FlowScope; node: string; kind: string; next?: string; last_fire?: string; error?: string }[]
  over_cap:     string[]
  max_watchers: number
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

// -- catalogue (GET /flows/catalog, 02 §1) ---------------------------------------

export interface CatalogPort {
  name:     string
  type:     PortType
  doc_fr:   string
  doc_en:   string
  example:  unknown
  required: boolean
  default:  unknown
  choices?: unknown[] | null   // allowed values of a choice param, in menu order
  wirable?: boolean            // absent (old catalogue) = true; false = constant, no link
  tokens?:  string | null      // project token section ("CLASS", "NAME", "SEQ"...) offered in a menu
}

// True, or {param, equals}: compares the param (or its default).
export type CondFlag = boolean | { param: string; equals: unknown } | null

export interface NodeSpec {
  type:        string
  label:       string
  family:      Family
  icon:        string
  inputs:      CatalogPort[]
  outputs:     CatalogPort[]
  params:      CatalogPort[]
  shelf:       number | null
  aliases:     string[]
  doc_fr:      string
  doc_en:      string
  destructive: CondFlag
  effect:      boolean
  raw:         string[]
  source:      'flux' | 'team'
  file:        string
  session:     string | null
  live_only:   boolean
  licence:     CondFlag
}

export interface FlowCatalog {
  nodes:      NodeSpec[]
  families:   string[]
  types:      { id: string; implicit: string[] }[]
  node_errors: { file: string; error: string }[]
}

// -- validation (01 §8, POST /flows/validate) -------------------------------------

export type IssueFixKind =
  | 'remove_link' | 'insert_foreach' | 'add_node' | 'add_block_end' | 'add_instance'
  | 'set_instance_mode' | 'add_set_variable' | 'replace_token' | 'set_param' | 'remove_node'

export interface Issue {
  level:      'error' | 'warning'
  code:       string
  node:       string | null
  port:       string | null
  message_fr: string
  message_en: string
  why_fr:     string
  why_en:     string
  fix:        { kind: IssueFixKind; args: Record<string, unknown> } | null
  link:       FlowDocLink | null
}

export interface SaveResult { state: FlowState; issues: Issue[]; valid: boolean }

// GET /flows/{name}/versions.
export interface VersionInfo { version: number; at: string; size: number; user?: string | null }
// history.jsonl line of the flow (team / project scopes): who, when, what.
export interface HistoryEntry { at: string; user: string | null; host?: string; kind: string; flow: string; version?: number; to_version?: number; from_version?: number; note?: string }
export interface VersionList { scope: FlowScope; name: string; state: FlowState; versions: VersionInfo[]; history: HistoryEntry[] }

// -- runs (01 §4, §6, §10) ------------------------------------------------------

export type RunStatus = 'queued' | 'running' | 'ok' | 'error' | 'cancelled' | 'interrupted' | 'skipped' | 'refused'
export type NodeRunState = 'idle' | 'running' | 'ok' | 'error' | 'error_handled' | 'skipped' | 'cancelled'

export interface NodeRunInfo {
  state:    NodeRunState
  started?: string
  ended?:   string
  error?:   string
  count?:   number
  values?:  Record<string, string>   // values received, shown on an error
  logs?:    { at?: string; level: string; text: string }[]
}

export interface RunIssue { level: string; code: string; node: string | null; port: string | null; message_fr: string }

// GET /flows/runs entry.
export interface RunSummary {
  run_id:      string
  flow:        string
  scope:       FlowScope
  project:     string | null
  version:     number | null
  draft:       boolean
  mode:        'real' | 'dry'
  status:      RunStatus
  trigger:     { event: string | null; values?: Record<string, unknown> }
  user:        string | null
  host:        string
  started:     string | null
  ended:       string | null
  duration_ms: number | null
  error:       string | null
}

// GET /flows/runs/{run_id}: the full record.
export interface RunRecord extends RunSummary {
  base_revision:   number | null
  issues:          RunIssue[]
  nodes:           Record<string, NodeRunInfo>
  links:           Record<string, { value: string; count: number }>
  report:          { node: string | null; kind: string; text_fr: string; path?: string | null }[]
  nodes_simulated: string[]
}

// Messages of WS /flows/ws.
export type FlowsWsMessage =
  | { type: 'hello'; holder: HostHolder | null; me: string; since?: number | null; running: RunSummary[] }
  | { type: 'host'; holder: HostHolder | null; me: string | null; is_holder: boolean; since: number | null }
  | { type: 'activation'; flow: string; scope: FlowScope; project: string | null; active: boolean; version: number | null; by: string | null }
  | { type: 'flow_changed'; flow: string; scope: FlowScope; project: string | null; version: number; revision: number; by: string | null }
  | { type: 'run_started'; run_id: string; flow: string; scope: FlowScope; mode: 'real' | 'dry'; user: string | null }
  | { type: 'node_state'; run_id: string; flow: string; node: string; state: NodeRunState; started?: string; ended?: string; error?: string; count?: number }
  | { type: 'link_value'; run_id: string; flow: string; link: string; preview: string; count: number }
  | { type: 'log'; run_id: string; flow: string; node: string; level: string; text: string }
  | { type: 'notify'; run_id: string; flow: string; node: string; level: 'info' | 'warn' | 'error'; text: string; path: string | null }
  | { type: 'run_finished'; run_id: string; flow: string; status: RunStatus; duration_ms: number | null; error: string | null; mode: 'real' | 'dry' }
