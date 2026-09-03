// types.ts — shared TypeScript types for FLUX frontend.

export interface DccStatusEntry {
  connected: boolean
  port: number
  color: string
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
}

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
  read: boolean
}

export interface FileEntry {
  name: string
  path: string
  size: number
  modified: string
  is_dir: boolean
}

// Template library preset (RETAKES-3): a reusable model file the team links once
// and drops anywhere in the folder manager. `file` is null when the slot is empty.
export interface Preset {
  id: string
  name: string
  file: string | null
  task: string | null   // TASK token (or 'DEFAULT') this preset is assigned to
  soft: string | null   // target software key (maya, houdini, nuke…)
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

export interface PublishResult {
  success: boolean
  dest_path: string | null
  message: string
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
}

export interface ProductionTaskDetail {
  notes?:      string
  completion?: number             // 0-100
  comments?:   ProductionComment[]
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
  order: number
  tasks: ProductionTask[]
  assets: { id: string; ref: string }[]
  notes?: string
}

export interface ProductionShot {
  id: string
  seq_id: string
  name: string                    // SHOT010
  order: number
  inherit_tasks: boolean
  inherit_assets: boolean
  tasks: ProductionTask[]
  assets: { id: string; ref: string }[]
  task_details?: Record<string, ProductionTaskDetail>
}

export interface ProductionState {
  version: number
  sequences: ProductionSequence[]
  shots:     ProductionShot[]
  assets:    ProductionAsset[]
  asset_groups: ProductionAssetGroup[]
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
}

export interface ProductionPayload {
  production: ProductionState
  publishes_by_task: Record<string, ProductionPublish[]>   // "<asset_id>|<task_id>"
  publishes_unmatched: ActivityEvent[]
}

