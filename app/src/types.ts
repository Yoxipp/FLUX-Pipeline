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
}

export interface PublishPayload {
  source_path: string
  project_name: string
  description?: string
  user?: string
}

export interface PublishResult {
  success: boolean
  dest_path: string | null
  message: string
}
