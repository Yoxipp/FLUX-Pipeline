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

export interface ModifLog {
  name: string
  date: string
  time: string
  version: string
  modification: string
  user: string
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

