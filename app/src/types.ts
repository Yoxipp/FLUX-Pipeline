// types.ts — shared TypeScript types for FLUX frontend.

// One running instance of a DCC (cluster C: several can run at once, each on its
// own port in the DCC's range). Rich identity fields stay null until the DCC-side
// bridge reports them.
export interface DccInstance {
  id: string          // stable id, "<dcc>:<port>"
  dcc: string
  port: number
  connected: boolean
  pid: number | null
  scene: string | null
  version: string | null
  label: string
  // "busy": accepts the connection but does not answer in time (an export runs)
  state?: 'connected' | 'busy'
}

export interface DccStatusEntry {
  connected: boolean
  port: number
  color: string
  // Every reachable instance of this DCC. Empty when none is up. `connected`
  // above is true when this list is non-empty, and `port` is the lowest open one.
  instances?: DccInstance[]
  // Maya only: a headless ("zombie") instance holds the commandPort but never
  // accepts a connection. Present (and false) once the backend has checked.
  stuck?: boolean
  stuck_pid?: number | null
  // A1: open without the FLUX bridge listening, every instance busy, the instance the
  // backend targets (port + pid) and the chosen one that went away.
  no_bridge?: boolean
  no_bridge_count?: number   // B5: sessions running without the bridge
  busy?: boolean
  active?: { port: number; pid: number | null } | null
  active_lost?: { port: number; pid: number | null; now_pid: number | null; at: number } | null
}

export type DccStatusMap = Record<string, DccStatusEntry>

export interface ActivityEvent {
  id: string
  user: string
  action: string
  file?: string
  dest_folder?: string
  project?: string
  date: string
  time: string
  read: boolean
  // Why it concerns the current artist (GET /activity/notifications, retake 04):
  // a followed shot, a favorite task, a task assigned to them; null = project-wide only.
  reason?: 'followed_shot' | 'favorite' | 'assigned' | null
}

export interface FollowedShot { seq: string; shot: string; exists: boolean }

export interface ChatMessage {
  id: string
  user: string
  message: string
  date: string
  time: string
}

export interface ChatMention {
  id: string
  message_id: string
  to_user: string
  from_user: string
  text: string
  date: string
  time: string
  project?: string   // project whose team chat the mention was said in
  read: boolean
}

export interface FileEntry {
  name: string
  path: string
  size: number
  modified: string
  is_dir: boolean
  legacy?: boolean               // old flat Constructor file of usd/assembly (V4): never imported
}

// Template library preset (RETAKES-3): a reusable model file the team links once
// and drops anywhere in the folder manager. `file` is null when the slot is empty.
export interface Preset {
  id: string
  name: string
  file: string | null
  task: string | null   // TASK token (or 'DEFAULT') this preset is assigned to
  soft: string | null   // target software key (maya, houdini, nuke…)
  builtin?: boolean     // shipped by FLUX, read-only (sequence render scene, ADR 0036)
  exists?: boolean      // builtin only: its scene is already on disk
}

export interface Settings {
  first_launch: boolean
  workspace: string | null
  username: string | null
  theme: {
    bg: string
    surface: string
    fg: string
    accent: string
  }
  last_project: string | null
  dcc_paths: Record<string, string>
  language?: 'fr' | 'en'
  // Console log-color overrides, keyed by level (debug/info/warning/error).
  // Absent/empty means the console uses its own theme-aware defaults.
  log_colors?: Record<string, string>
}

export interface PublishPayload {
  source_path: string
  project_name: string
  description?: string
  user?: string
  target_name?: string   // composed FLUX name when the source file isn't token-named
}

export interface PublishDestination {
  abs_path: string
  rel_path: string
  version: string
  sequence: boolean
  first: boolean
  last_exists: boolean
  existing: string[]
  more: number
}

export interface PublishResult {
  success: boolean
  dest_path: string | null
  message: string
  tx_paths?: string[] | null      // .tx written by the texture conform (switch on)
  proxy_path?: string | null      // purpose=proxy USD written at publish (switch on)
}

// ── Action engine (declarative YAML actions) ───────────────────────────────
// One field the generic front form renders. Mirrors a backend ParameterBuffer
// plus the (step, command) address that locates it inside the action.
export interface ActionField {
  step:     string
  command:  string
  name:     string
  type:     string          // str | text | path | int | float | bool | select | ...
  value:    unknown
  label:    string
  tooltip:  string | null
  hide:     boolean
  ask_user: boolean
  prompt:   boolean
  status:   string
}

export interface ActionFormResponse {
  action: string
  fields: ActionField[]
}

export interface ActionPreviewResponse {
  resolved:  boolean
  dest_path: string | null
  message:   string
}

// ── Node flow (read-only graph view of a YAML action) ────────────────────────

export interface ActionGraphParam {
  name:  string
  type:  string
  label: string
  value: unknown
  wired: boolean          // fed from another command's output (never user-typed)
  hide:  boolean
  tooltip?: string
}

export interface ActionGraphNode {
  id:       string        // "step.command"
  position: { x: number; y: number }
  data: {
    label:   string
    command: string       // registry key
    step:    string
    index:   number
    status:  string
    params:  ActionGraphParam[]
    doc?:    string       // first paragraph of the command's docstring
    doc_fr?: string       // French doc (UI in French)
    module?: string       // python module of the command
    outputs?: string[]    // B4: output keys the command returns (its ports)
    effects?: ActionGraphEffect[]   // B4: files written + hidden hooks
    note?:    string      // B4: YAML comments inside the command block
  }
}

// B4: what a command writes besides its outputs, or a hook that runs behind it.
export interface ActionGraphEffect { kind: 'output' | 'hook'; label: string; detail: string }

// B6 node editor catalogue: registered commands (FLUX + team) and code functions.
export interface CatalogParam { name: string; type: string; value: unknown; label?: string; hide?: boolean; tooltip?: string; required?: boolean }
export interface CatalogCommand { key: string; doc: string; doc_fr?: string; params: CatalogParam[]; outputs: string[]; origin: 'flux' | 'equipe'; module: string }
export interface CatalogFunction { id: string; module: string; name: string; useful?: boolean; args: CatalogParam[]; doc: string; outputs: string[] }
export interface ActionCatalog { commands: CatalogCommand[]; functions: CatalogFunction[]; node_errors: Record<string, string> }

// B4: what the runner injects at launch (context snapshot or set_parameter).
export interface ActionGraphInput { kind: 'context' | 'runtime'; name: string; target: string; function: string }

export interface ActionGraphEdge {
  id:     string
  source: string
  target: string
  kind:   'order' | 'dataflow'
  label?: string
}

export interface ActionGraph {
  name:  string
  nodes: ActionGraphNode[]
  edges: ActionGraphEdge[]
  steps?: { name: string; index: number; commands: string[]; note?: string }[]
  inputs?: ActionGraphInput[]
  origin?: 'flux' | 'equipe'   // B6: "equipe" = team copy in CONFIG/actions
  has_default?: boolean        // B6: a shipped YAML exists (reset possible)
  description?: string    // header comment of the YAML
  description_fr?: string // its French part (after a "FR:" line)
  file?: string
}

export interface HoudiniPublishPayload {
  project_name: string
  filename: string
  extension: string
  rop_node_path?: string
  is_sequence?: boolean
  frame_range?: [number, number, number]
  frame_padding?: number
  export_options?: Record<string, unknown>
  attr_filter?: { mode: 'keep' | 'remove'; names: string[] }
  description?: string
  user?: string
}

export interface HoudiniPublishResult {
  ok: boolean
  path: string
  version: number
  version_str: string
  rop_node: string
  is_sequence: boolean
}

export interface HoudiniState {
  selected_nodes: string[]
  selected_node_types?: Record<string, string>
  current_path: string
  frame: number
  fps: number
  hip_file: string
}

export interface ZBrushPublishPayload {
  project_name:   string
  filename:       string
  extension:      string
  export_options?: Record<string, unknown>
  description?:   string
  user?:          string
}

export interface ZBrushPublishResult {
  ok:          boolean
  path:        string
  version:     number
  version_str: string
}

// ── Production Tab ───────────────────────────────────────────────────────────

export interface ProductionComment {
  id:     string
  text:   string
  author: string
  date:   string                  // ISO YYYY-MM-DD
  time:   string                  // HH:MM
  kind?:  'note' | 'retake'       // absent = note (old comments); 'retake' feeds the home "Tes retakes"
}

export interface ProductionTaskDetail {
  assignee?:   string             // pipeline artist assigned to this task or subtask
  status?:     string             // explicit review token; completion never implies approval
  notes?:      string
  completion?: number             // 0-100
  comments?:   ProductionComment[]
  priority?:   'high' | 'low'     // absent = normal (retake 07, Production/taskPriority.ts)
}

export interface ProductionTask {
  id: string
  name: string                    // free-form label
  order: number
  type_tokens: string[]           // TYPE tokens (match key against publishes)
  known_subtasks: string[]        // INSTANCE values seen/typed for this task
  origin?: 'user' | 'auto'
  path_override?: string          // project-relative path replacing token-based matching
}

export interface ProductionAsset {
  thumbnail?: ProductionThumbnail
  dependencies?: ProductionDependency[]
  id: string
  class: string                   // CHAR / PROPS / ENV / FXRIG …
  name: string
  group_id: string | null
  order: number
  origin?: 'user' | 'auto'
  tasks: ProductionTask[]
  task_details?: Record<string, ProductionTaskDetail>
}

export interface ProductionAssetGroup {
  id: string
  class: string
  name: string
  order: number
}

export interface ProductionSequence {
  id: string
  name: string                    // SEQ001
  label?: string                  // free-form user label (e.g. "opening bar")
  color?: string                  // user-chosen CSS color (auto-derived if absent)
  order: number
  origin?: 'user' | 'auto'
  tasks: ProductionTask[]
  assets: CastingLink[]
  task_details?: Record<string, ProductionTaskDetail>
  notes?: string
  locked?: ProductionLock          // 2026-09-30: blocks edits / rename / delete
}

// Lock of a sequence / shot (backend features/production/lock.py).
export interface ProductionLock { by: string; at: string }

// Casting link (ADR 0020): count = number of instances in the shot stage (NAME_01, NAME_02...),
// origin "auto" = added because an animation was published for that character.
export interface CastingLink {
  id: string
  ref: string
  count?: number
  origin?: 'user' | 'auto'
  // ADR 0048: pinned USD version of the asset ("v003"); absent or "" = follows LAST.
  version?: string
}

export interface ProductionShot {
  thumbnail?: ProductionThumbnail
  dependencies?: ProductionDependency[]
  id: string
  seq_id: string
  name: string                    // SHOT010
  label?: string                  // free-form user label
  order: number
  origin?: 'user' | 'auto'
  inherit_tasks: boolean
  inherit_assets: boolean
  tasks: ProductionTask[]
  assets: CastingLink[]
  task_details?: Record<string, ProductionTaskDetail>
  frame_start?: number            // shot frame range (ADR 0020), written on the shot stage
  frame_end?: number
  locked?: ProductionLock
  preview_source?: string         // department shown for this shot in the Timeline edit (group id); unset = global source
}

export interface ProductionState {
  tracking?: { departments: ProductionDepartment[] }
  version: number
  sequences: ProductionSequence[]
  shots:     ProductionShot[]
  assets:    ProductionAsset[]
  asset_groups: ProductionAssetGroup[]
}

export interface ProductionThumbnail { rel_path: string; file: string }
export interface ProductionDependency { entity_id: string; task?: string }
export interface ProductionDepartment {
  id: string
  name: string
  task_tokens: string[]
  scope: 'shot' | 'asset'
  active: boolean
  fixed?: boolean
  statuses: string[]
  depends_on: string[]
}

// Publish event enriched by reconcile — carries the parsed INSTANCE for grouping.
export interface ProductionPublish {
  id: string
  user: string
  file: string
  dest_folder: string
  date: string
  time: string
  instance?: string
  task_token?: string
  description?: string   // publish comment, from the folder's modif log
}

export interface ProductionPayload {
  production: ProductionState
  publishes_by_task: Record<string, ProductionPublish[]>   // "<entity_id>|<task_id>"
  publishes_unmatched: ActivityEvent[]
  sequences_on_disk?: string[]              // seq names present on disk
  shots_on_disk?: Array<[string, string]>   // [seq_name, shot_name] pairs on disk
}


// Team calendar (backend features/calendar/calendar_store.py, 2026-09-30).
export type CalendarStatus = 'proposed' | 'accepted' | 'in_progress' | 'done' | 'declined'
export interface CalendarHistory { at: string; by: string; action: string; start?: string; end?: string }
export interface CalendarItem {
  id: string
  title: string
  note: string
  link: string
  owner: string          // who commits
  created_by: string     // who wrote it (someone else = a proposal)
  start: string          // YYYY-MM-DD
  end: string            // YYYY-MM-DD, inclusive
  status: CalendarStatus
  created_at: string
  updated_at: string
  history: CalendarHistory[]
}

// A publish shown on the calendar (features/calendar/publishes.py).
export interface CalendarPublish { id: string; date: string; time: string; user: string; file: string; dest_folder: string }
