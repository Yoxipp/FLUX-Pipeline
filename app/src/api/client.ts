// client.ts — HTTP client vers FastAPI Python backend (127.0.0.1:8765).

import type {
  ActionFormResponse,
  ActionGraph,
  ActionPreviewResponse,
  ActivityEvent,
  ChatMention,
  ChatMessage,
  FileEntry,
  HoudiniPublishPayload,
  HoudiniPublishResult,
  HoudiniState,
  Preset,
  ProductionPayload,
  ProductionState,
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

// ── Conditional GET (ETag / 304) ────────────────────────────────────────────────

export interface Conditional<T> {
  /** true when the server answered 304 — `data` is absent, keep prior state. */
  notModified: boolean
  data?: T
  /** ETag to echo back on the next request (unchanged on 304). */
  etag?: string
}

// GET that participates in conditional requests: sends If-None-Match when an
// ETag is known and reports 304 instead of throwing (304 is not `response.ok`).
async function apiGetConditional<T>(endpoint: string, etag?: string): Promise<Conditional<T>> {
  const headers: Record<string, string> = {}
  if (etag) headers['If-None-Match'] = etag

  const response = await fetch(`${BASE_URL}${endpoint}`, { method: 'GET', headers })

  if (response.status === 304) return { notModified: true, etag }

  if (!response.ok) {
    let detail = `HTTP ${response.status}`
    try {
      const err = await response.json()
      detail = err.detail ?? detail
    } catch {}
    throw new Error(detail)
  }

  const newEtag = response.headers.get('ETag') ?? undefined
  const data = (await response.json()) as T
  return { notModified: false, data, etag: newEtag }
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
    username: string; workspace: string; language: 'fr' | 'en'
    log_colors: Record<string, string>
  }>) => apiCall<{ success: boolean }>('PUT', '/settings', patch),

  listUsers: () =>
    apiCall<{ users: string[] }>('GET', '/settings/users'),

  renameUser: (old: string, next: string) =>
    apiCall<{ success: boolean; message: string }>('PUT', '/settings/users/rename', { old, new: next }),

  deleteUser: (name: string) =>
    apiCall<{ success: boolean; message: string }>('DELETE', `/settings/users/${encodeURIComponent(name)}`),

  // Per-user data blob (favorites / recents / archived …) — stored on the Flux drive
  getUserData: () =>
    apiCall<Record<string, unknown>>('GET', '/settings/user-data'),

  setUserData: (patch: Record<string, unknown>) =>
    apiCall<Record<string, unknown>>('PUT', '/settings/user-data', patch),

  // Per-user enabled DCCs (null = all enabled)
  getEnabledDccs: () =>
    apiCall<{ known: string[]; enabled: string[] | null }>('GET', '/settings/enabled-dccs'),

  setEnabledDccs: (enabled: string[] | null) =>
    apiCall<{ known: string[]; enabled: string[] | null }>('PUT', '/settings/enabled-dccs', { enabled }),

  // DCC
  findDccExe: (dcc: string) =>
    apiCall<{ dcc: string; path: string | null; found: boolean }>('GET', `/dcc/find/${dcc}`),

  launchDcc: (dcc: string, exe_path?: string) =>
    apiCall<{ dcc: string; launched: boolean }>('POST', '/dcc/launch', { dcc, exe_path }),

  pingDcc: (dcc: string) =>
    apiCall<{ connected: boolean; version: string | null }>('GET', `/dcc/${dcc}/ping`),

  // Photoshop (COM, no in-app plugin): actionable state + library bootstrap.
  photoshopStatus: () =>
    apiCall<{ reason: 'ok' | 'lib_missing' | 'not_running'; lib_installed: boolean; connected: boolean; version: string | null; error: string | null }>(
      'GET', '/dcc/photoshop/status'),

  photoshopInstall: () =>
    apiCall<{ ok: boolean; already: boolean; installed: boolean; frozen: boolean; message: string }>(
      'POST', '/dcc/photoshop/install'),

  photoshopOpen: (project_name: string, rel_path: string) =>
    apiCall<{ ok: boolean; error: string | null }>('POST', '/dcc/photoshop/open', { project_name, rel_path }),

  // Create a Read node in Nuke from a project-relative file (Folder Manager).
  nukeImportPath: (project_name: string, rel_path: string) =>
    apiCall<{ ok: boolean; node: string; path: string }>('POST', '/dcc/nuke/import_path', { project_name, rel_path }),

  // Detect a stuck ("zombie") Maya still holding the commandPort (port 7001).
  getMayaPortStatus: () =>
    apiCall<{ stuck: boolean; pid: number | null; name: string | null }>('GET', '/dcc/maya/port_status'),

  // Terminate a stuck Maya holding the commandPort (re-verified server-side before killing).
  reapMayaPort: () =>
    apiCall<{ killed: boolean; pid: number | null; message: string }>('POST', '/dcc/maya/reap'),

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

  // Action engine (declarative): the generic form renders these fields, and the
  // preview resolves the destination without copying anything.
  getPublishForm: () =>
    apiCall<ActionFormResponse>('GET', '/actions/publish/form'),

  previewPublish: (payload: {
    source_path: string
    project_name: string
    user?: string
    target_name?: string
  }) => apiCall<ActionPreviewResponse>('POST', '/actions/publish/preview', payload),

  // Node flow (read-only): the graph of a YAML action, rendered with React Flow.
  // On demand only (opened from the hidden bench page); never polled.
  getActionGraphList: () =>
    apiCall<string[]>('GET', '/actions/graph/list'),

  getActionGraph: (name: string) =>
    apiCall<ActionGraph>('GET', `/actions/${encodeURIComponent(name)}/graph`),

  getHoudiniState: () =>
    apiCall<HoudiniState>('GET', '/dcc/houdini/state'),

  publishHoudiniRop: (payload: HoudiniPublishPayload) =>
    apiCall<HoudiniPublishResult>('POST', '/dcc/houdini/publish', payload),

  // Maya
  getMayaConnectCmd: () =>
    apiCall<{ cmd: string; backend: string }>('GET', '/dcc/maya/connect_cmd'),

  // port targets a specific Maya instance (multi-instance); omit → base commandPort.
  importFileInMaya: (project_name: string, rel_path: string, port?: number) =>
    apiCall<{ ok: boolean; file: string }>('POST', '/dcc/maya/import', { project_name, rel_path, port }),

  publishMaya: (payload: {
    project_name: string
    filename:     string
    extension:    string
    scope?:       string
    is_sequence?: boolean
    frame_range?: [number, number] | [number, number, number]
    export_options?: Record<string, unknown>
    description?: string
    user?:        string
    port?:        number
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
    scope?:       string
    include_geo?:     boolean
    include_skel?:    boolean
    include_anim?:    boolean
    include_weights?: boolean
    include_uv?:      boolean
    port?:            number
  }) =>
    apiCall<{ ok: boolean; asset: string; version: string; root: string }>(
      'POST', '/dcc/maya/export-usd', payload),

  exportHoudiniLightUsd: (payload: {
    project_name: string
    asset:        string
    filename?:    string
    skel_node?:   string
    mesh_node?:   string
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
      'POST', '/dcc/houdini/export-usd', payload),

  // ZBrush
  publishZBrush: (payload: ZBrushPublishPayload) =>
    apiCall<ZBrushPublishResult>('POST', '/dcc/zbrush/publish', payload),

  cancelZBrush: () =>
    apiCall<{ cancelled: boolean }>('POST', '/dcc/zbrush/cancel'),

  // Nuke — publish acts on the selected node: FLUX builds a Write with the chosen
  // options, renders it into the versioned layout, removes it (.nk = scriptSaveAs).
  publishNuke: (payload: {
    project_name:   string
    filename:       string
    extension:      string
    export_options?: Record<string, unknown>
    is_sequence?:   boolean
    frame_range?:   [number, number]
    node_name?:     string
    colorspace?:    string
    description?:   string
    user?:          string
  }) =>
    apiCall<{ ok: boolean; path: string; version: number; version_str: string; is_sequence: boolean }>(
      'POST', '/dcc/nuke/publish', payload),

  // Photoshop — save the active document into the FLUX layout over COM.
  publishPhotoshop: (payload: {
    project_name:   string
    filename:       string
    extension:      string
    export_options?: Record<string, unknown>
    description?:   string
    user?:          string
  }) =>
    apiCall<{ ok: boolean; path: string; version: number; version_str: string }>(
      'POST', '/dcc/photoshop/publish', payload),

  // Substance Painter — export maps via the in-app bridge, ingest under FLUX tokens,
  // optionally conform to .tx. Token-driven (class/task/name/instance).
  publishSubstance: (payload: {
    project_name: string
    class_token:  string
    task_token:   string
    name_token:   string
    instance?:    string
    preset?:      string
    file_format?: string
    bit_depth?:   string
    conform_tx?:  boolean
    description?: string
    user?:        string
  }) =>
    apiCall<{ ok: boolean; published?: string[]; tx?: string[] | null }>('POST', '/dcc/substance/publish', payload),

  // Mari — export channels via the in-app bridge, ingest under FLUX tokens,
  // optionally conform to .tx.
  publishMari: (payload: {
    project_name: string
    class_token:  string
    task_token:   string
    name_token:   string
    instance?:    string
    file_format?: string
    conform_tx?:  boolean
    description?: string
    user?:        string
  }) =>
    apiCall<{ ok: boolean; published?: string[]; tx?: string[] | null }>('POST', '/dcc/mari/publish', payload),

  // Level 1 file ingest (Substance Designer / Marvelous Designer): the artist
  // exports a file from the app; FLUX ingests it under FLUX naming. One method per
  // soft for a clear per-DCC entry point.
  publishDesigner: (payload: {
    project_name: string; source_path: string; target_name: string
    description?: string; user?: string
  }) => apiCall<{ ok: boolean; path: string }>('POST', '/dcc/designer/publish', payload),

  publishMarvelous: (payload: {
    project_name: string; source_path: string; target_name: string
    description?: string; user?: string
  }) => apiCall<{ ok: boolean; path: string }>('POST', '/dcc/marvelous/publish', payload),

  // Activity
  // Conditional variants used by the shared feed poller (FeedsProvider): send
  // the stored ETag, get a 304 (keep state) when nothing changed.
  getActivityConditional: (limit: number, etag?: string) =>
    apiGetConditional<{ events: ActivityEvent[]; unread_count: number }>(
      `/activity?limit=${limit}`, etag),

  getMentionsConditional: (etag?: string) =>
    apiGetConditional<{ mentions: ChatMention[]; unread_count: number }>(
      '/activity/chat/mentions', etag),

  // Older, rotated events from the cold archives (Activity page "load older").
  // On demand only — never polled.
  getActivityHistory: (limit = 200, offset = 0, kind: 'activity' | 'mentions' = 'activity') =>
    apiCall<{ events: ActivityEvent[]; has_more: boolean }>(
      'GET', `/activity/history?limit=${limit}&offset=${offset}&kind=${kind}`),

  markAllRead: () =>
    apiCall<{ success: boolean }>('POST', '/activity/read-all'),

  getChat: (limit?: number) =>
    apiCall<{ messages: ChatMessage[]; users: string[] }>('GET', `/activity/chat${limit ? `?limit=${limit}` : ''}`),

  sendChat: (message: string, user?: string) =>
    apiCall<{ success: boolean }>('POST', '/activity/chat', { message, user }),

  markMentionsRead: (user?: string) =>
    apiCall<{ success: boolean }>('POST', '/activity/chat/mentions/read', { user }),

  // Files
  browseProject: (project_name: string, subpath?: string) =>
    apiCall<{ path: string; folders: { name: string; path: string }[]; files: FileEntry[] }>('GET', `/files/projects/${project_name}/browse${subpath ? `?subpath=${encodeURIComponent(subpath)}` : ''}`),

  // Folder Manager
  getTokens: (project: string) =>
    apiCall<{ tokens: Record<string, Record<string, string>> }>('GET', `/folder/projects/${encodeURIComponent(project)}/tokens`),

  getProjects: () =>
    apiCall<{ projects: string[] }>('GET', '/folder/projects'),

  // Active project — single source of truth, persisted backend-side (config.json)
  getCurrentProject: () =>
    apiCall<{ project: string | null }>('GET', '/project/current'),

  setCurrentProject: (project: string) =>
    apiCall<{ project: string }>('PUT', '/project/current', { project }),

  createProject: (name: string) =>
    apiCall<{ name: string; path: string }>('POST', '/folder/projects', { name }),

  // Hard-delete a whole project folder. Destructive: only call after the typed
  // confirmation in the Archives view.
  deleteProject: (name: string) =>
    apiCall<{ deleted: string }>('DELETE', `/folder/projects/${encodeURIComponent(name)}`),

  getAssets: (project: string, class_token?: string) =>
    apiCall<{ assets: string[] }>('GET', `/folder/projects/${project}/assets${class_token ? `?class_token=${class_token}` : ''}`),

  // Contextual token suggestions, scanned from what is published on disk (never global)
  suggestTokens: (params: {
    project: string; field: 'instance' | 'variante' | 'name'; mode?: 'asset' | 'shot'
    class_token?: string; name?: string; type_token?: string; instance?: string; seq?: string; shot?: string
  }) => {
    const qs = new URLSearchParams({ project: params.project, field: params.field, mode: params.mode ?? 'asset' })
    if (params.class_token) qs.set('class_token', params.class_token)
    if (params.name)        qs.set('name', params.name)
    if (params.type_token)  qs.set('type_token', params.type_token)
    if (params.instance)    qs.set('instance', params.instance)
    if (params.seq)         qs.set('seq', params.seq)
    if (params.shot)        qs.set('shot', params.shot)
    return apiCall<{ suggestions: string[] }>('GET', `/folder/suggest?${qs}`)
  },

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

  copyItem: (project: string, subpath: string[], name: string, dstSubpath: string[], newName?: string) =>
    apiCall<{ name: string; path: string }>('POST', '/folder/copy', {
      project, subpath: subpath.join('/'), name,
      dst_subpath: dstSubpath.join('/'), new_name: newName ?? '',
    }),

  getLocks: (project: string) =>
    apiCall<{ locked: string[] }>('GET', `/folder/projects/${encodeURIComponent(project)}/locks`),

  setLock: (project: string, subpath: string[], name: string, locked: boolean) =>
    apiCall<{ locked: string[] }>('POST', '/folder/locks', {
      project, subpath: subpath.join('/'), name, locked,
    }),

  patchItem: (project: string, subpath: string[], name: string, newName?: string, newSubpath?: string[]) =>
    apiCall<{ name: string; path: string }>('PATCH', '/folder/items', {
      project, subpath: subpath.join('/'), name,
      new_name: newName ?? '', new_subpath: newSubpath !== undefined ? newSubpath.join('/') : '',
    }),

  // Presets (template library — RETAKES-3)
  listPresets: (project: string) =>
    apiCall<{ presets: Preset[] }>('GET', `/folder/projects/${encodeURIComponent(project)}/presets`),

  addPreset: (project: string, name?: string) =>
    apiCall<{ ok: boolean; preset: Preset; presets: Preset[] }>(
      'POST', `/folder/projects/${encodeURIComponent(project)}/presets`, { name: name ?? '' }),

  linkPreset: (project: string, presetId: string, srcPath: string) =>
    apiCall<{ ok: boolean; preset: Preset; presets: Preset[] }>(
      'PUT', `/folder/projects/${encodeURIComponent(project)}/presets/${encodeURIComponent(presetId)}/link`,
      { src_path: srcPath }),

  unlinkPreset: (project: string, presetId: string) =>
    apiCall<{ ok: boolean; preset: Preset; presets: Preset[] }>(
      'PUT', `/folder/projects/${encodeURIComponent(project)}/presets/${encodeURIComponent(presetId)}/unlink`),

  renamePreset: (project: string, presetId: string, name: string) =>
    apiCall<{ ok: boolean; preset: Preset; presets: Preset[] }>(
      'PUT', `/folder/projects/${encodeURIComponent(project)}/presets/${encodeURIComponent(presetId)}/rename`,
      { name }),

  deletePreset: (project: string, presetId: string) =>
    apiCall<{ ok: boolean; presets: Preset[] }>(
      'DELETE', `/folder/projects/${encodeURIComponent(project)}/presets/${encodeURIComponent(presetId)}`),

  dropPreset: (project: string, presetId: string, destSubpath: string) =>
    apiCall<{ ok: boolean; name: string; path: string }>(
      'POST', `/folder/projects/${encodeURIComponent(project)}/presets/${encodeURIComponent(presetId)}/drop`,
      { dest_subpath: destSubpath }),

  setPresetMeta: (project: string, presetId: string, task: string, soft: string) =>
    apiCall<{ ok: boolean; preset: Preset; presets: Preset[] }>(
      'PUT', `/folder/projects/${encodeURIComponent(project)}/presets/${encodeURIComponent(presetId)}/meta`,
      { task, soft }),

  launchPreset: (project: string, presetId: string, dcc: string) =>
    apiCall<{ ok: boolean; launched: boolean; dcc: string; scene: string }>(
      'POST', `/folder/projects/${encodeURIComponent(project)}/presets/${encodeURIComponent(presetId)}/launch`,
      { dcc }),

  // DCC
  getFluxTokensFromPath: (project: string, rel_path: string) =>
    apiCall<{ CLASS: string; TYPE: string; NAME: string; INSTANCE: string }>(
      'GET', `/dcc/houdini/importer/path_to_tokens?project=${encodeURIComponent(project)}&rel_path=${encodeURIComponent(rel_path)}`,
    ),

  createFluxImporterNode: (params: {
    project?: string; flux_class?: string; flux_type?: string;
    flux_name?: string; flux_instance?: string; flux_iter?: string;
    rel_path?: string;
  }) =>
    apiCall<{ ok: boolean; result?: { node_path?: string; resolved_path?: string; mode?: string } }>(
      'POST', '/dcc/houdini/importer/create_node', params,
    ),

  // Shelf
  getShelves: () =>
    apiCall<Record<string, { versions: string[]; installed: Record<string, boolean>; hdas_installed: Record<string, boolean> }>>('GET', '/shelf'),

  installShelf: (dcc: string, version: string) =>
    apiCall<{ success: boolean; message: string }>('POST', '/shelf/install', { dcc, version }),

  removeShelf: (dcc: string, version: string) =>
    apiCall<{ success: boolean; message: string }>('DELETE', '/shelf', { dcc, version }),

  // Maya tools → single Flux shelf (checkable, selection persisted)
  getTools: () =>
    apiCall<{ versions: string[]; tools: { id: string; label: string; selected: boolean }[]; installed: Record<string, boolean> }>('GET', '/shelf/tools'),

  applyTools: (version: string, tool_ids: string[]) =>
    apiCall<{ success: boolean; message: string }>('POST', '/shelf/tools/apply', { version, tool_ids }),

  // USD Assembler
  assembleRecipe: (recipe: unknown, project?: string, strict = true) =>
    apiCall<{
      success: boolean
      root?: string
      layers?: string[]
      issues: { level: string; msg: string; prim: string | null }[]
    }>('POST', '/usd/assemble', { recipe, project, strict }),

  // Published layered-USD versions for a component slot (feeds the slot editor's
  // version dropdown). Empty `versions` when nothing is published for asset+task.
  getUsdLayers: (project: string, asset: string, task: string) => {
    const qs = new URLSearchParams({ project, asset, task })
    return apiCall<{
      project: string
      asset: string
      task: string
      versions: Record<string, { base: string; layers: string[] }>
    }>('GET', `/usd/layers?${qs}`)
  },

  // Contextual suggestions for the assembler comboboxes, scanned from disk.
  getUsdTasks: (project: string, asset: string) => {
    const qs = new URLSearchParams({ project, asset })
    return apiCall<{ project: string; asset: string; tasks: string[] }>('GET', `/usd/tasks?${qs}`)
  },

  getUsdInstances: (project: string, asset: string, task = '') => {
    const qs = new URLSearchParams({ project, asset })
    if (task) qs.set('task', task)
    return apiCall<{ project: string; asset: string; task: string; instances: string[] }>('GET', `/usd/instances?${qs}`)
  },

  getUsdVariantes: (project: string, asset: string, task: string, instance = '') => {
    const qs = new URLSearchParams({ project, asset, task })
    if (instance) qs.set('instance', instance)
    return apiCall<{ project: string; asset: string; task: string; instance: string; variantes: string[] }>('GET', `/usd/variantes?${qs}`)
  },

  // Existing components (ADR 0018) and assemblies of the project (assembler default view).
  getUsdLibrary: (project: string) => {
    const qs = new URLSearchParams({ project })
    return apiCall<UsdLibrary>('GET', `/usd/library?${qs}`)
  },

  // pins: {slot: {task, instance, version} | {exclude: true} | null (automatic again)}
  refreshUsdComponent: (project: string, name: string, pins?: Record<string, UsdSlotPin | null>) =>
    apiCall<{ ok: boolean; changed: boolean; version: string | null; last?: string }>(
      'POST', '/usd/component/refresh', { project, name, pins }),

  // Point one assembly instance at a component LAST or a frozen vNNN.
  relinkUsdInstance: (project: string, file: string, prim: string, component: string, version: string) =>
    apiCall<{ ok: boolean; prim: string; asset_path: string }>(
      'POST', '/usd/assembly/relink', { project, file, prim, component, version }),

  // ── Production Tab ─────────────────────────────────────────────────────────
  // GET returns production + reconciled publishes; PUT replaces the store.
  getProduction: (project: string) =>
    apiCall<ProductionPayload>('GET', `/production/${encodeURIComponent(project)}`),

  // Saving production.json also mirrors the planning to disk (create-only) on the
  // backend — there is no separate "materialize" call any more; structure is kept
  // in sync automatically in both directions.
  setProduction: (project: string, production: ProductionState) =>
    apiCall<{ success: boolean; synced?: Record<string, number> }>(
      'PUT', `/production/${encodeURIComponent(project)}`, { production }),

  // Fan out a "comment" activity event so favorited-task subscribers see it in
  // Activity. Persistence of the comment itself is already in production.json
  // (frontend's debounced PUT handles that side).
  notifyProductionComment: (project: string, payload: {
    class_token: string
    name:        string
    task:        string
    subtask?:    string | null
    text?:       string
  }) =>
    apiCall<{ success: boolean }>(
      'POST', `/production/${encodeURIComponent(project)}/comment`, payload),

  // Resolve a Production entity's on-disk folder + file count, to warn before
  // archiving (prevention message). exists=false → nothing on disk (ghost).
  getEntityFolder: (project: string, params: {
    kind: 'asset' | 'shot' | 'seq'
    class_token?: string; name?: string
    seq?: string; shot?: string
  }) => {
    const qs = new URLSearchParams({ kind: params.kind })
    if (params.class_token) qs.set('class_token', params.class_token)
    if (params.name)        qs.set('name', params.name)
    if (params.seq)         qs.set('seq', params.seq)
    if (params.shot)        qs.set('shot', params.shot)
    return apiCall<{ rel_path: string; exists: boolean; file_count: number }>(
      'GET', `/production/${encodeURIComponent(project)}/entity-folder?${qs}`)
  },

  // Move an entity folder into <project>/ARCHIVE/<timestamp>/ (never hard-delete).
  // The caller removes the logical entity from production.json after this resolves.
  archiveEntity: (project: string, relPath: string) =>
    apiCall<{ archived: boolean; archived_to?: string; reason?: string }>(
      'POST', `/production/${encodeURIComponent(project)}/archive`, { rel_path: relPath }),

  // Composer ghost-token: resolve a token's folder + file count (to warn before
  // archiving it from the Publisher).
  getTokenFolder: (project: string, params: {
    field: 'name' | 'instance' | 'seq' | 'shot'
    class_token?: string; name?: string; task?: string
    instance?: string; seq?: string; shot?: string
  }) => {
    const qs = new URLSearchParams({ field: params.field })
    for (const k of ['class_token', 'name', 'task', 'instance', 'seq', 'shot'] as const) {
      if (params[k]) qs.set(k, params[k] as string)
    }
    return apiCall<{ rel_path: string; exists: boolean; file_count: number }>(
      'GET', `/production/${encodeURIComponent(project)}/token-folder?${qs}`)
  },

  // Archive a composer token's folder (into ARCHIVE/) and drop it from tokens.json.
  archiveToken: (project: string, params: {
    field: 'name' | 'instance' | 'seq' | 'shot'
    class_token?: string; name?: string; task?: string
    instance?: string; seq?: string; shot?: string
  }) =>
    apiCall<{ archived: boolean; archived_to?: string }>(
      'POST', `/production/${encodeURIComponent(project)}/archive-token`, params),

  // ── Reference media (/ref embed zone) ──────────────────────────────────────
  // Resolve the project-relative root of a task/subtask (where /ref lives).
  // Authoritative on the backend so shots (templated CLASS tokens) resolve right.
  resolveRefPath: (project: string, params: {
    kind: 'asset' | 'shot' | 'seq'
    class_token?: string; name?: string
    seq?: string; shot?: string
    task?: string; subtask?: string
  }) => {
    const qs = new URLSearchParams({ kind: params.kind })
    if (params.class_token) qs.set('class_token', params.class_token)
    if (params.name)        qs.set('name', params.name)
    if (params.seq)         qs.set('seq', params.seq)
    if (params.shot)        qs.set('shot', params.shot)
    if (params.task)        qs.set('task', params.task)
    if (params.subtask)     qs.set('subtask', params.subtask)
    return apiCall<{ rel_path: string }>(
      'GET', `/production/${encodeURIComponent(project)}/ref/resolve?${qs}`)
  },

  // Deposit a dropped image/video as the next version; the raw File is the body.
  depositRef: async (project: string, relPath: string, file: File) => {
    const qs = new URLSearchParams({ rel_path: relPath, filename: file.name })
    const res = await fetch(
      `${BASE_URL}/production/${encodeURIComponent(project)}/ref?${qs}`,
      { method: 'POST', headers: { 'Content-Type': file.type || 'application/octet-stream' }, body: file },
    )
    if (!res.ok) {
      let detail = `HTTP ${res.status}`
      try { detail = (await res.json()).detail ?? detail } catch {}
      throw new Error(detail)
    }
    return res.json() as Promise<{ ok: boolean; version: string; file: string; ext: string; kind: string }>
  },

  getRefLatest: (project: string, relPath: string) => {
    const qs = new URLSearchParams({ rel_path: relPath })
    return apiCall<{ found: boolean; file?: string; ext?: string; kind?: string }>(
      'GET', `/production/${encodeURIComponent(project)}/ref/latest?${qs}`)
  },

  // Streamable URL for the <img>/<video> src (Range-enabled backend).
  refFileUrl: (project: string, relPath: string, name: string) => {
    const qs = new URLSearchParams({ rel_path: relPath, name })
    return `${BASE_URL}/production/${encodeURIComponent(project)}/ref/file?${qs}`
  },

  exportRef: (project: string, relPath: string, name: string, destPath: string) =>
    apiCall<{ ok: boolean; dest: string }>(
      'POST', `/production/${encodeURIComponent(project)}/ref/export`,
      { rel_path: relPath, name, dest_path: destPath }),
}

// USD assembler library (GET /usd/library)
export interface UsdSlotPin { task?: string; instance?: string; version?: string; exclude?: boolean }
export interface UsdSlotRef { task: string | null; version: string | null; pin?: UsdSlotPin | null }
export interface UsdComponentInfo {
  name: string
  class: string | null   // CLASS token (deep link to Production)
  state: 'ok' | 'stale' | 'missing' | 'incomplete'
  version: string | null
  versions: string[]
  slots: Record<string, UsdSlotRef>
  published: Record<string, UsdSlotRef>
  dir: string
  last: string | null
  used_by: string[]
}
export interface UsdAssemblyInstance {
  prim: string; asset_path: string; component: string | null; broken: boolean; follows_last: boolean
}
export interface UsdAssemblyInfo { name: string; file: string; instances: UsdAssemblyInstance[]; broken: number }
export interface UsdLibrary { project: string; components: UsdComponentInfo[]; assemblies: UsdAssemblyInfo[] }
