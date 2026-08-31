// client.ts — HTTP client vers FastAPI Python backend (127.0.0.1:8765).

import type {
  ActivityEvent,
  ChatMessage,
  DccStatusMap,
  FileEntry,
  HoudiniPublishPayload,
  HoudiniPublishResult,
  HoudiniState,
  ModifLog,
  PublishPayload,
  PublishResult,
  Settings,
  ZBrushPublishPayload,
  ZBrushPublishResult,
} from '../types'

const BASE_URL = 'http://127.0.0.1:8765'

export interface LogRecord {
  id:      number
  ts:      number
  levelno: number
  level:   string
  logger:  string
  msg:     string
}

async function apiCall<T>(
  method: 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH',
  endpoint: string,
  body?: unknown,
  timeoutMs?: number,   // optional: fail fast instead of hanging on a wedged backend
): Promise<T> {
  let signal: AbortSignal | undefined
  let timer: ReturnType<typeof setTimeout> | undefined
  if (timeoutMs) {
    const controller = new AbortController()
    signal = controller.signal
    timer = setTimeout(() => controller.abort(), timeoutMs)
  }

  let response: Response
  try {
    response = await fetch(`${BASE_URL}${endpoint}`, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal,
    })
  } catch (e) {
    if ((e as { name?: string })?.name === 'AbortError') {
      throw new Error(`Backend injoignable (timeout ${timeoutMs}ms sur ${endpoint})`)
    }
    throw e
  } finally {
    if (timer) clearTimeout(timer)
  }

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
    apiCall<Settings>('GET', '/settings', undefined, 10000),   // fail fast on a wedged backend

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

  pingDcc: (dcc: string) =>
    apiCall<{ connected: boolean; version: string | null }>('GET', `/dcc/${dcc}/ping`),

  getDccAutostart: (dcc: string) =>
    apiCall<{ installed: boolean; startup_file: string | null }>('GET', `/dcc/${dcc}/autostart`),

  installDccAutostart: (dcc: string) =>
    apiCall<{ success: boolean; message: string; path: string | null }>('POST', `/dcc/${dcc}/autostart`),

  removeDccAutostart: (dcc: string) =>
    apiCall<{ success: boolean; message: string }>('DELETE', `/dcc/${dcc}/autostart`),

  // Console logs
  getLogs: (after = 0, level?: string) =>
    apiCall<{ records: LogRecord[] }>(
      'GET',
      `/logs?after=${after}${level ? `&level=${encodeURIComponent(level)}` : ''}`,
    ),

  clearLogs: () =>
    apiCall<{ ok: boolean }>('DELETE', '/logs'),

  // Publisher
  publish: (payload: PublishPayload) =>
    apiCall<PublishResult>('POST', '/publish', payload),

  getHoudiniState: () =>
    apiCall<HoudiniState>('GET', '/dcc/houdini/state'),

  publishHoudiniRop: (payload: HoudiniPublishPayload) =>
    apiCall<HoudiniPublishResult>('POST', '/dcc/houdini/publish', payload),

  // Maya
  getMayaConnectCmd: () =>
    apiCall<{ cmd: string; backend: string }>('GET', '/dcc/maya/connect_cmd'),

  importFileInMaya: (project_name: string, rel_path: string) =>
    apiCall<{ ok: boolean; file: string }>('POST', '/dcc/maya/import', { project_name, rel_path }),

  publishMaya: (payload: {
    project_name: string
    filename:     string
    extension:    string
    scope?:       string
    is_sequence?: boolean
    frame_range?: [number, number]
    export_options?: Record<string, unknown>
    description?: string
    user?:        string
  }) =>
    apiCall<{ ok: boolean; version_str: string; dest: string }>('POST', '/dcc/maya/publish', payload),

  exportMayaLightUsd: (payload: {
    project_name: string
    asset:        string
    filename?:    string
    mesh?:        string
    root_joint?:  string
    frame_start?: number
    frame_end?:   number
    fmt?:         string
    include_geo?:     boolean
    include_skel?:    boolean
    include_anim?:    boolean
    include_weights?: boolean
    include_uv?:      boolean
  }) =>
    apiCall<{ ok: boolean; asset: string; version: string; root: string }>(
      'POST', '/dcc/maya/export-usd', payload),

  // ZBrush
  publishZBrush: (payload: ZBrushPublishPayload) =>
    apiCall<ZBrushPublishResult>('POST', '/dcc/zbrush/publish', payload),

  cancelZBrush: () =>
    apiCall<{ cancelled: boolean }>('POST', '/dcc/zbrush/cancel'),

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

  getTypesForClass: (project: string, class_token?: string) =>
    apiCall<{ types: string[] }>('GET', `/folder/projects/${encodeURIComponent(project)}/types${class_token ? `?class_token=${encodeURIComponent(class_token)}` : ''}`),

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

  addToken: (payload: { project: string; token_type: string; token_value: string; rel_path?: string }) =>
    apiCall<{ success: boolean; token_type: string; token_value: string }>('POST', '/folder/tokens', payload),

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

  // DCC
  getFluxTokensFromPath: (project: string, rel_path: string) =>
    apiCall<{ CLASS: string; TYPE: string; NAME: string; INSTANCE: string }>(
      'GET', `/dcc/houdini/importer/path_to_tokens?project=${encodeURIComponent(project)}&rel_path=${encodeURIComponent(rel_path)}`,
    ),

  importHoudiniCharacter: (file_path: string, network_path = '/obj') =>
    apiCall<{ node_path: string; node_type: string; file_set: boolean; has_bonecapture: boolean; point_count: number }>(
      'POST', '/dcc/houdini/import-character', { file_path, network_path },
    ),

  createFluxImporterNode: (params: {
    project?: string; flux_class?: string; flux_type?: string;
    flux_name?: string; flux_instance?: string; flux_iter?: string;
  }) =>
    apiCall<{ ok: boolean; node_path?: string }>('POST', '/dcc/houdini/importer/create_node', params),

  // Shelf
  getShelves: () =>
    apiCall<Record<string, { versions: string[]; installed: Record<string, boolean>; hdas_installed: Record<string, boolean> }>>('GET', '/shelf'),

  installShelf: (dcc: string, version: string) =>
    apiCall<{ success: boolean; message: string }>('POST', '/shelf/install', { dcc, version }),

  removeShelf: (dcc: string, version: string) =>
    apiCall<{ success: boolean; message: string }>('DELETE', '/shelf', { dcc, version }),

  // Maya tools catalog
  getTools: () =>
    apiCall<{ versions: string[]; tools: { id: string; label: string; filename: string; installed: Record<string, boolean> }[] }>('GET', '/shelf/tools'),

  installTool: (tool_id: string, version: string) =>
    apiCall<{ success: boolean; message: string }>('POST', '/shelf/tools/install', { tool_id, version }),

  removeTool: (tool_id: string, version: string) =>
    apiCall<{ success: boolean; message: string }>('POST', '/shelf/tools/remove', { tool_id, version }),

  // USD Assembler
  assembleRecipe: (recipe: unknown, project?: string, strict = true) =>
    apiCall<{
      success: boolean
      root?: string
      layers?: string[]
      issues: { level: string; msg: string; prim: string | null }[]
    }>('POST', '/usd/assemble', { recipe, project, strict }),

  getRecipeSchema: () =>
    apiCall<Record<string, unknown>>('GET', '/usd/schema'),
}
