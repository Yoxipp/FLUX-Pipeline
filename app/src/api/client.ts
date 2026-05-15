// client.ts — HTTP client vers FastAPI Python backend (127.0.0.1:8765).

import type {
  ActivityEvent,
  ChatMessage,
  DccStatusMap,
  FileEntry,
  ModifLog,
  PublishPayload,
  PublishResult,
  Settings,
} from '../types'

const BASE_URL = 'http://127.0.0.1:8765'

async function apiCall<T>(
  method: 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH',
  endpoint: string,
  body?: unknown,
): Promise<T> {
  const response = await fetch(`${BASE_URL}${endpoint}`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

  if (!response.ok) {
    let detail = `HTTP ${response.status}`
    try {
      const err = await response.json()
      detail = err.detail ?? detail
    } catch {}
    throw new Error(detail)
  }

  return response.json() as Promise<T>
}

// ── Settings ──────────────────────────────────────────────────────────────────

export const api = {
  // Settings
  getSettings: () =>
    apiCall<Settings>('GET', '/settings'),

  initFirstLaunch: (workspace: string, username: string) =>
    apiCall<{ success: boolean }>('POST', '/settings/init', { workspace, username }),

  updateSettings: (patch: Partial<{
    theme_bg: string; theme_surface: string; theme_fg: string; theme_accent: string
    last_project: string; dcc_path: Record<string, string>
    username: string; workspace: string
  }>) => apiCall<{ success: boolean }>('PUT', '/settings', patch),

  listUsers: () =>
    apiCall<{ users: string[] }>('GET', '/settings/users'),

  // DCC
  getDccStatus: () =>
    apiCall<DccStatusMap>('GET', '/dcc/status'),

  connectDcc: (dcc: string) =>
    apiCall<{ dcc: string; connected: boolean }>('POST', `/dcc/connect/${dcc}`),

  disconnectDcc: (dcc: string) =>
    apiCall<{ dcc: string; connected: boolean }>('POST', `/dcc/disconnect/${dcc}`),

  executeCommand: (dcc: string, command: string) =>
    apiCall<{ success: boolean; result: string; dcc: string }>('POST', '/dcc/execute', { dcc, command }),

  findDccExe: (dcc: string) =>
    apiCall<{ dcc: string; path: string | null; found: boolean }>('GET', `/dcc/find/${dcc}`),

  getInstalledDccs: () =>
    apiCall<{ dccs: Record<string, string> }>('GET', '/dcc/installed'),

  launchDcc: (dcc: string, exe_path?: string) =>
    apiCall<{ dcc: string; launched: boolean }>('POST', '/dcc/launch', { dcc, exe_path }),

  // Publisher
  publish: (payload: PublishPayload) =>
    apiCall<PublishResult>('POST', '/publish', payload),

  // Importer
  importFiles: (dcc: string, file_paths: string[], project_name?: string) =>
    apiCall<{ results: { path: string; success: boolean }[] }>('POST', '/import', { dcc, file_paths, project_name }),

  browseImport: (project_name: string, subpath?: string) =>
    apiCall<{ path: string; folders: string[]; files: FileEntry[] }>('GET', `/import/browse?project_name=${encodeURIComponent(project_name)}${subpath ? `&subpath=${encodeURIComponent(subpath)}` : ''}`),

  // Activity
  getActivity: (params?: { limit?: number; user?: string; action?: string; project?: string }) => {
    const qs = new URLSearchParams()
    if (params?.limit)   qs.set('limit', String(params.limit))
    if (params?.user)    qs.set('user', params.user)
    if (params?.action)  qs.set('action', params.action)
    if (params?.project) qs.set('project', params.project)
    return apiCall<{ events: ActivityEvent[]; unread_count: number }>('GET', `/activity?${qs}`)
  },

  markEventRead: (event_id: string) =>
    apiCall<{ success: boolean }>('POST', '/activity/read', { event_id }),

  markAllRead: () =>
    apiCall<{ success: boolean }>('POST', '/activity/read-all'),

  getChat: (limit?: number) =>
    apiCall<{ messages: ChatMessage[]; users: string[] }>('GET', `/activity/chat${limit ? `?limit=${limit}` : ''}`),

  sendChat: (message: string, user?: string) =>
    apiCall<{ success: boolean }>('POST', '/activity/chat', { message, user }),

  // Files
  browseProject: (project_name: string, subpath?: string) =>
    apiCall<{ path: string; folders: { name: string; path: string }[]; files: FileEntry[] }>('GET', `/files/projects/${project_name}/browse${subpath ? `?subpath=${encodeURIComponent(subpath)}` : ''}`),

  getModifLogs: (project_name: string, subpath?: string) =>
    apiCall<{ logs: ModifLog[] }>('GET', `/files/projects/${project_name}/logs${subpath ? `?subpath=${encodeURIComponent(subpath)}` : ''}`),

  // Folder Manager
  getTokens: (project: string) =>
    apiCall<{ tokens: Record<string, Record<string, string>> }>('GET', `/folder/projects/${encodeURIComponent(project)}/tokens`),

  getProjects: () =>
    apiCall<{ projects: string[] }>('GET', '/folder/projects'),

  createProject: (name: string) =>
    apiCall<{ name: string; path: string }>('POST', '/folder/projects', { name }),

  getAssets: (project: string, class_token?: string) =>
    apiCall<{ assets: string[] }>('GET', `/folder/projects/${project}/assets${class_token ? `?class_token=${class_token}` : ''}`),

  createAsset: (project: string, class_token: string, name: string) =>
    apiCall<{ name: string; path: string }>('POST', '/folder/assets', { project, class_token, name }),

  getSequences: (project: string) =>
    apiCall<{ sequences: string[] }>('GET', `/folder/projects/${project}/sequences`),

  createSequence: (project: string, seq_number: number) =>
    apiCall<{ seq_number: number; path: string }>('POST', '/folder/sequences', { project, seq_number }),

  getShots: (project: string, seq_label: string) =>
    apiCall<{ shots: string[] }>('GET', `/folder/projects/${project}/sequences/${seq_label}/shots`),

  createShot: (project: string, seq_number: number, shot_number: number) =>
    apiCall<{ seq_number: number; shot_number: number; path: string }>('POST', '/folder/shots', { project, seq_number, shot_number }),

  createDirectory: (project: string, subpath: string[], name: string, token?: string, token_type?: string) =>
    apiCall<{ name: string; path: string; rel_path: string }>('POST', '/folder/directory', {
      project, subpath: subpath.join('/'), name,
      token: token ?? '', token_type: token_type ?? '',
    }),

  deleteItem: (project: string, subpath: string[], name: string) =>
    apiCall<{ deleted: string }>('DELETE', '/folder/items', { project, subpath: subpath.join('/'), name }),

  patchItem: (project: string, subpath: string[], name: string, newName?: string, newSubpath?: string[]) =>
    apiCall<{ name: string; path: string }>('PATCH', '/folder/items', {
      project, subpath: subpath.join('/'), name,
      new_name: newName ?? '', new_subpath: newSubpath !== undefined ? newSubpath.join('/') : '',
    }),

  // Shelf
  getShelves: () =>
    apiCall<Record<string, { versions: string[]; installed: Record<string, boolean> }>>('GET', '/shelf'),

  installShelf: (dcc: string, version: string) =>
    apiCall<{ success: boolean; message: string }>('POST', '/shelf/install', { dcc, version }),

  removeShelf: (dcc: string, version: string) =>
    apiCall<{ success: boolean; message: string }>('DELETE', '/shelf', { dcc, version }),
}
