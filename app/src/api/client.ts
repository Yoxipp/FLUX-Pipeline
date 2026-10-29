// client.ts — HTTP client vers FastAPI Python backend (127.0.0.1:8765).

import type {
  ActionFormResponse,
  CalendarItem,
  CalendarPublish,
  ActionPreviewResponse,
  ActivityEvent,
  FollowedShot,
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
  PublishDestination,
  PublishResult,
  Settings,
  ZBrushPublishPayload,
  ZBrushPublishResult,
} from '../types'

export const BASE_URL = 'http://127.0.0.1:8765'

export interface WorkspacesInfo {
  active: string | null
  workspaces: { path: string; exists: boolean; active: boolean }[]
}

export interface LogRecord {
  id:      number
  ts:      number
  levelno: number
  level:   string
  logger:  string
  msg:     string
}

export async function apiCall<T>(
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
    let detail: unknown = `HTTP ${response.status}`
    try {
      const err = await response.json()
      detail = err.detail ?? detail
    } catch {}
    // Object details ({message, ...} of the /flows routes) keep their fields on the error.
    const message = typeof detail === 'string' ? detail
      : (detail as { message?: string } | null)?.message ?? JSON.stringify(detail)
    throw Object.assign(new Error(message), { status: response.status, detail })
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

// An export preset of the open Painter, with the output maps it writes (fileName = id).
export interface PainterPreset { name: string; url: string; maps: { id: string; label: string }[] }
// A channel of the texture sets' stacks (coat, anisotropy, user...): id = Painter export name.
export interface PainterChannel { id: string; label: string; gray: boolean }
// Substance Designer: the open packages, their graphs and each graph's outputs.
export interface DesignerGraph { id: string; current?: boolean; outputs: { id: string; label: string }[] }
export interface DesignerPackage { path: string; name: string; graphs: DesignerGraph[] }

// One group of operations of the cleaning scan (backend features/folder_manager/asset_cleanup.py).
export interface CleanupItem {
  id: string
  kind: 'temp' | 'old_layout' | 'wrong_place' | 'old_map_name' | 'empty_dir'
  action: 'move' | 'drop_dup' | 'drop_tmp' | 'rm_empty' | 'warn'
  path: string; target: string; reason: string; files: number; bytes: number
  safe: boolean; warning: string; names: string[]
}
export interface CleanupScan { scope: string; items: CleanupItem[]; unknown: string[] }

// One DCC of "Installer tous les bridges" (backend features/launcher/bridges.py).
export interface BridgeInstallResult { dcc: string; status: 'ok' | 'skip' | 'error'; message: string }

// The manual as HTML, for the Settings > Doc iframe (the Electron main process adds
// the X-Flux-Token header to every request to the backend, frames included).
export const MANUAL_URL = `${BASE_URL}/system/manual`
export const FLOWS_MANUAL_URL = `${BASE_URL}/system/manual?doc=flows`

// Tractor farm render (backend features/render/team_settings.py, routers/render.py).
export interface RenderSettings {
  tractor_project: string; priority: number; maxactive: number; chunk_size: number
  max_task_minutes: number; retry_exit_codes: number[]   // per render chunk: kill past N min (0 = none), retry on codes
  renderer: 'karma' | 'renderman'; freeze_by_default: boolean
  // scheduled job: freeze on the blade when it starts, or at submit
  freeze_when: RenderFreezeWhen; houdini_path: string
  schedule: { enabled: boolean; start: string; end: string; kill_at_end: boolean }
  service_karma: string; service_renderman: string; envkeys: string[]
  husk_path: string; bridge_python: string; bridge_script: string; engine: string; engine_user: string; dry_run: boolean
  engine_config_dir: string   // network folder of the engine limits.config (environment screen only)
  denoise_path: string; denoise_crossframe: boolean   // RenderMan denoise_batch on the blades
  // percent 0 = off; of = alive blades or blades free right now
  job_share: RenderShare; team_cap: RenderShare
  host_groups: Record<string, string[]>; exclude_hosts: string[]
}
// farm_teams / team_warning: Shares of the engine limits.config (read only, Tractor balances the teams itself)
export interface RenderSettingsResponse {
  settings: RenderSettings; warning: string | null; farm_teams?: string[]; team_warning?: string | null
  farm_shares?: Record<string, RenderShareRule> | null   // husk Shares, "default" = every other project
}
export interface RenderEnvUnlock { phrase: string; password: string }
export interface RenderShareRule { nominal: number | null; cap: number | null }   // 0..1 (school limits.config)
export interface RenderEnvState {
  engine: string; config_dir: string; folder_ok: boolean; folder_error: string | null
  engine_shares: Record<string, Record<string, RenderShareRule>> | null   // per limit tag (husk, prman...)
}
// Last launch form of the artist (backend <project>/_flux_setup/render_last/<user>.json).
export interface RenderLastForm {
  source: 'shot' | 'usd'; seq: string; shot: string; usd_path: string; renderer: 'karma' | 'renderman'
  freeze: boolean; limit_job: boolean; share_percent: number; share_of: RenderShareBase
  target: 'any' | 'pick'; hosts: string[]; groups: string[]; freeze_when?: RenderFreezeWhen
  denoise?: boolean; denoise_crossframe?: boolean
}
export type RenderShareBase = 'alive' | 'free'
export type RenderFreezeWhen = 'start' | 'submit'
export interface RenderShare { percent: number; of: RenderShareBase }
export interface RenderShot { seq: string; shot: string; frame_start: number | null; frame_end: number | null; has_stage: boolean }
export interface RenderSubmitResult {
  dry_run: boolean; jid?: number | null; files: { alf: string; json: string }; title: string
  output: string; usd: string; frozen: boolean; frames: string; warnings: string[]; priority_warning?: string | null
  start_at: string; service: string; maxactive: number; freeze_when?: RenderFreezeWhen
  denoise?: string | null   // folder of the denoised frames, when asked
}
export interface RenderJob {
  jid: number; title: string; user: string; projects?: string[] | string; priority?: number; maxactive?: number
  numTasks: number; numDone: number; numError: number; numActive: number
  numBlocked?: number; numReady?: number
  spooltime?: string | number; stoptime?: string; pausetime?: string; comment?: string; metadata?: unknown
  // user = Tractor owner (the shared school login); flux_user = who spooled it from FLUX ('' otherwise)
  flux_user?: string
  state?: 'active' | 'error' | 'done' | 'paused' | 'waiting' | 'deleted'
  percent?: number   // done tasks + progress of the running ones (husk ALF_PROGRESS), 0-100
}
export interface RenderTask { jid: number; tid: number; title: string; state: string; service?: string; progress?: number | null }
export type RenderJobScope = 'all' | 'team' | 'mine'
// Job menu of the Tractor Dashboard (backend tractor_bridge.JOB_ACTIONS); only on the user's FLUX jobs.
export type RenderJobAction = 'kill' | 'retry' | 'pause' | 'resume' | 'skip_errors' | 'restart' | 'archive'
  | 'restore' | 'lock' | 'unlock' | 'shuffle_top'
export interface RenderExitCode {
  code: number; count: number; last_seen: string; last_title: string; label: string; active: boolean; proposed: boolean
}
export type RenderBladeState = 'free' | 'busy' | 'nimby' | 'offline'
export interface RenderBlade {
  name: string; state: RenderBladeState; room: string; slots: number; nimby: string
  job: number | null; project: string | null; heartbeat: string
}
export interface RenderFarm {
  blades: RenderBlade[]; active_by_project: Record<string, number>
  counts: Record<RenderBladeState | 'alive', number>; rooms: Record<string, string[]>
  host_groups: Record<string, string[]>; exclude_hosts: string[]; host_targeting_verified: boolean
  schedule: { enabled: boolean; start: string; end: string; kill_at_end: boolean }
  tractor_project: string; dry_run?: boolean
}

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

  // Known FLUX directories on this machine; exactly one is active (activate it with
  // updateSettings({ workspace })).
  listWorkspaces: () =>
    apiCall<WorkspacesInfo>('GET', '/settings/workspaces'),

  addWorkspace: (path: string) =>
    apiCall<WorkspacesInfo>('POST', '/settings/workspaces', { path }),

  removeWorkspace: (path: string) =>
    apiCall<WorkspacesInfo>('POST', '/settings/workspaces/remove', { path }),

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
    apiCall<{ connected: boolean; version: string | null; busy?: boolean; publishing?: boolean }>('GET', `/dcc/${dcc}/ping`),

  // Photoshop (COM, no in-app plugin): actionable state + library bootstrap.
  photoshopStatus: () =>
    apiCall<{ reason: 'ok' | 'lib_missing' | 'not_running'; lib_installed: boolean; connected: boolean; version: string | null; error: string | null }>(
      'GET', '/dcc/photoshop/status'),

  photoshopInstall: () =>
    apiCall<{ ok: boolean; already: boolean; installed: boolean; frozen: boolean; message: string }>(
      'POST', '/dcc/photoshop/install'),

  // Settings > User: install the FLUX bridge of every DCC detected on this machine.
  installAllBridges: () =>
    apiCall<{ results: BridgeInstallResult[] }>('POST', '/dcc/bridges/install-all', undefined, 180000),

  // Settings > Doc: where the manual lives (FLUX_DOC copy, else the bundled one).
  getManualInfo: () =>
    apiCall<{ path: string; flows_path: string; doc_dir: string }>('GET', '/system/manual-info'),

  photoshopOpen: (project_name: string, rel_path: string) =>
    apiCall<{ ok: boolean; error: string | null }>('POST', '/dcc/photoshop/open', { project_name, rel_path }),

  // Create a Read node in Nuke from a project-relative file (Folder Manager).
  nukeImportPath: (project_name: string, rel_path: string) =>
    apiCall<{ ok: boolean; node: string; path: string }>('POST', '/dcc/nuke/import_path', { project_name, rel_path }),

  // Animation range to export (U1): Maya = first / last key (selection or scene),
  // playback range without keys; Houdini = playbar range.
  getAnimRange: (dcc: 'Maya' | 'Houdini', scope: 'scene' | 'selection', port?: number) =>
    apiCall<{ ok: boolean; start: number; end: number; source: 'keys' | 'timeline'; curves: number }>(
      'GET', dcc === 'Maya'
        ? `/dcc/maya/anim-range?scope=${scope}${port ? `&port=${port}` : ''}`
        : '/dcc/houdini/anim-range'),

  // Running instances of a DCC with their open scene (publish picker), and the
  // instance FLUX works with (backend clients without a port follow it: Houdini).
  getDccInstances: (dcc: string) =>
    apiCall<{ dcc: string; active: number | null; instances: { id: string; port: number; pid: number | null; label: string; scene: string | null; selection?: string[] }[] }>(
      'GET', `/dcc/instances/${encodeURIComponent(dcc)}`),
  // pid: the process seen on that port (A1): the backend refuses a port taken back by
  // another process instead of publishing from the wrong scene.
  setActiveInstance: (dcc: string, port: number | null, pid?: number | null) =>
    apiCall<{ ok: boolean }>('POST', '/dcc/active-instance', { dcc, port, pid: pid ?? null }),

  // Instances of one character in the Maya scene (U2): DINGO_01, DINGO_02...
  getMayaCharacterInstances: (name: string, port?: number) =>
    apiCall<{ ok: boolean; items: { node: string; label: string; instance: number; meshes: number }[] }>(
      'GET', `/dcc/maya/character-instances?name=${encodeURIComponent(name)}${port ? `&port=${port}` : ''}`),

  // Detect a stuck ("zombie") Maya still holding the commandPort (port 7001).
  getMayaPortStatus: () =>
    apiCall<{ stuck: boolean; pid: number | null; name: string | null }>('GET', '/dcc/maya/port_status'),

  // Terminate a stuck Maya holding the commandPort (re-verified server-side before killing).
  // Close one running instance of a DCC (sidebar instance menu). force = kill (unsaved work lost).
  closeDccInstance: (dcc: string, port: number, force = false) =>
    apiCall<{ closed: boolean; pid: number | null; needs_force: boolean; message: string }>(
      'POST', `/dcc/instances/${encodeURIComponent(dcc)}/close`, { port, force }),

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
  getPublishDestination: (project: string, base: string, ext: string, sequence = false) =>
    apiCall<PublishDestination>('GET', `/publish/destination?${new URLSearchParams({
      project, base, ext, sequence: String(sequence) })}`),
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

  // The old YAML action editor (P4-P8) is gone; the backend /actions/* routes stay as a fallback.
  getNodeTemplate: (name: string) =>
    apiCall<{ code: string }>('GET', `/actions/nodes/template?name=${encodeURIComponent(name)}`),
  saveNode: (name: string, code: string) =>
    apiCall<{ path: string; error: string }>('POST', '/actions/nodes', { name, code }),

  getHoudiniState: () =>
    apiCall<HoudiniState>('GET', '/dcc/houdini/state'),

  publishHoudiniRop: (payload: HoudiniPublishPayload) =>
    apiCall<HoudiniPublishResult>('POST', '/dcc/houdini/publish', payload),

  // Maya
  getMayaConnectCmd: () =>
    apiCall<{ cmd: string; backend: string }>('GET', '/dcc/maya/connect_cmd'),

  // port targets a specific Maya instance (multi-instance); omit → base commandPort.
  importFileInMaya: (project_name: string, rel_path: string, port?: number, mode: 'import' | 'proxy' = 'import') =>
    apiCall<{ ok: boolean; file: string }>('POST', '/dcc/maya/import', { project_name, rel_path, port, mode }),
  // V4: what "Ouvrir dans..." loads for a file (asset / decor / shot first, layer second).
  getLoadTargets: (project: string, rel_path: string) =>
    apiCall<LoadTargets>('GET', `/dcc/load-targets?${new URLSearchParams({ project, rel_path })}`),
  // Old Constructor files (usd/assembly): list, and move to <project>/_backup_flux (never a hard delete).
  getUsdLegacy: (project: string) =>
    apiCall<{ files: { name: string; rel_path: string }[] }>('GET', `/usd/legacy?${new URLSearchParams({ project })}`),
  deleteUsdLegacy: (project: string, rel_path: string) =>
    apiCall<{ ok: boolean; backup: string }>('POST', '/usd/legacy/delete', { project, rel_path }),

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
    apiCall<{ ok: boolean; version_str: string; dest: string; warnings?: string[] }>('POST', '/dcc/maya/publish', payload),

  exportMayaLightUsd: (payload: {
    project_name: string
    asset:        string
    filename?:    string
    root?:        string   // one character instance node (U2), overrides scope
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
    // Publisher preset options (ADR 0034): { preset: 'model' | 'rig' | 'anim', ... }.
    options?:         Record<string, unknown>
    port?:            number
  }) =>
    apiCall<{ ok: boolean; asset: string; version: string; root: string; warnings?: string[] }>(
      'POST', '/dcc/maya/export-usd', payload),

  // What a USD preset would export from Maya (listing before the publish).
  getMayaUsdPreview: (preset: 'model' | 'rig' | 'anim' | 'look' | 'camera' | 'light', scope: 'scene' | 'selection',
                      start?: number, end?: number, port?: number) => {
    const qs = new URLSearchParams({ preset, scope })
    if (start !== undefined) qs.set('start', String(start))
    if (end !== undefined) qs.set('end', String(end))
    if (port) qs.set('port', String(port))
    return apiCall<MayaUsdPreview>('GET', `/dcc/maya/usd-preview?${qs}`)
  },

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
    apiCall<{ ok: boolean; asset: string; version: string; root: string; warnings?: string[] }>(
      'POST', '/dcc/houdini/export-usd', payload),

  // Look department (ADR 0019 A1b): the DCC exports its materials, the backend
  // rewrites them into /<NAME>/mtl + bindings and publishes the look layer.
  exportMayaLookUsd: (payload: {
    project_name: string
    filename:     string
    fmt?:         string
    scope?:       string
    user?:        string
    port?:        number
  }) =>
    apiCall<LookExportResult>('POST', '/dcc/maya/export-usd-look', payload),

  exportHoudiniLookUsd: (payload: {
    project_name: string
    filename:     string
    lop_node?:    string
    fmt?:         string
    user?:        string
  }) =>
    apiCall<LookExportResult>('POST', '/dcc/houdini/export-usd-look', payload),
  createSequenceRenderScene: (project: string, seq: string) =>
    apiCall<{ ok: boolean; created: boolean; path: string; shots?: string[]; without_stage?: string[] }>(
      'POST', '/dcc/houdini/sequence-render-scene', { project, seq }),

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
    apiCall<{ ok: boolean; path: string; version: number; version_str: string; is_sequence: boolean; warnings?: string[] }>(
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
    tx_only?:     boolean
    description?: string
    user?:        string
    texture_sets?: string[]
    size?:        number
    padding?:     string
    dilation?:    number
    maps?:        string[]                                              // output maps of the preset (fileName)
    map_params?:  Record<string, { format?: string; bit_depth?: string; size?: number }>  // per map overrides
    channels?:    PainterChannel[]                                      // "Canaux du shader" mode
  }) =>
    apiCall<{ ok: boolean; published?: string[]; tx?: string[] | null; warnings?: string[] }>('POST', '/dcc/substance/publish', payload),

  // What can be exported from the open Painter project / Mari geo (Publisher options).
  getSubstanceInfo: () =>
    apiCall<{ ok: boolean; project: string; texture_sets: { name: string; udim?: boolean; resolution?: number }[];
              presets?: PainterPreset[]; channels?: PainterChannel[] }>(
      'GET', '/dcc/substance/info', undefined, 25000),
  getTextureFormats: () =>
    apiCall<{ formats: Record<string, string[]>; sizes: number[] }>('GET', '/dcc/texture/formats'),
  // Unreal (ADR 0052): point the FLUX stage actor at a USD stage, reload changed layers.
  unrealOpenStage: (path: string, purpose: 'proxy' | 'render' = 'proxy') =>
    apiCall<{ ok: boolean; path: string; purpose: string; seconds: number }>(
      'POST', '/dcc/unreal/open-stage', { path, purpose }, 600000),
  unrealReload: () =>
    apiCall<{ ok: boolean; mode: 'targeted' | 'full'; changed?: string[]; seconds: number }>(
      'POST', '/dcc/unreal/reload', undefined, 600000),

  getMariInfo: () =>
    apiCall<{ ok: boolean; geo: string; mode?: 'channels' | 'nodes'
              channels: { name: string; size?: number; depth?: number; layers?: number
                          node?: string; input?: string; baked?: boolean }[] }>(
      'GET', '/dcc/mari/info', undefined, 25000),

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
    tx_only?:     boolean
    description?: string
    user?:        string
    channels?:    string[]
    channel_params?: Record<string, { format?: string; bit_depth?: string; size?: number }>
  }) =>
    apiCall<{ ok: boolean; published?: string[]; tx?: string[] | null; warnings?: string[]; timings?: string }>('POST', '/dcc/mari/publish', payload, 3600000),

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

  // Substance Designer bridge (Level 2, like Painter): graph maps / .sbsar / .sbs
  // exported by the in-app plugin, ingested under FLUX tokens.
  getDesignerInfo: () =>
    apiCall<{ ok: boolean; packages: DesignerPackage[]; current?: string }>(
      'GET', '/dcc/designer/info', undefined, 25000),
  publishDesignerBridge: (payload: {
    project_name: string
    class_token:  string
    task_token:   string
    name_token:   string
    instance?:    string
    graphs?:      { package: string; graph: string; outputs?: string[] | null }[]
    file_format?: string
    size?:        number
    bit_depth?:   string
    maps?:        boolean
    sbsar?:       boolean
    sbs?:         boolean
    conform_tx?:  boolean
    tx_only?:     boolean
    description?: string
    user?:        string
  }) =>
    apiCall<{ ok: boolean; published?: string[]; tx?: string[] | null; warnings?: string[] }>(
      'POST', '/dcc/designer/bridge/publish', payload),

  // Marvelous Designer bridge: the open project exported (abc / obj / fbx / usd / glb,
  // + .zprj) by the bridge script, published under the composed FLUX name.
  getMarvelousInfo: () =>
    apiCall<{ ok: boolean; project: string; path?: string; formats: string[];
              patterns?: number | null; avatars?: number | null }>(
      'GET', '/dcc/marvelous/info', undefined, 25000),
  // Import a project file into the open Marvelous scene (Folder Manager "Ouvrir dans").
  importInMarvelous: (project_name: string, rel_path: string) =>
    apiCall<{ ok: boolean; function?: string; path?: string }>(
      'POST', '/dcc/marvelous/import', { project_name, rel_path }, 600000),
  publishMarvelousBridge: (payload: {
    project_name: string
    target_name:  string
    file_format?: string
    options?:     Record<string, unknown>
    with_zprj?:   boolean
    description?: string
    user?:        string
  }) =>
    apiCall<{ ok: boolean; published?: string[]; warnings?: string[] }>(
      'POST', '/dcc/marvelous/bridge/publish', payload),

  // Activity
  // Conditional variants used by the shared feed poller (FeedsProvider): send
  // the stored ETag, get a 304 (keep state) when nothing changed.
  getActivityConditional: (limit: number, etag?: string) =>
    apiGetConditional<{ events: ActivityEvent[]; unread_count: number }>(
      `/activity?limit=${limit}`, etag),

  // Personal notifications of ONE project for the current artist (retake 04):
  // scope 'self' = followed shots, favorite and assigned tasks; 'global' = every
  // event of the project, each annotated with its `reason`.
  getNotifications: (project: string, scope: 'self' | 'global', limit = 200) =>
    apiCall<{ events: ActivityEvent[]; followed_shots: FollowedShot[]; user: string }>(
      'GET', `/activity/notifications?${new URLSearchParams({ project, scope, limit: String(limit) })}`),

  // Publish copies running / waiting on this machine (shown while a publish is pending).
  getPublishQueue: () =>
    apiCall<{ active: number; waiting: number; max_parallel: number; max_mbps: number }>('GET', '/publish/queue'),

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

  // Team chat is per project (DOSSIER_PROJETS/<project>/teamChat.json).
  getChat: (project: string, limit?: number) =>
    apiCall<{ messages: ChatMessage[]; users: string[] }>(
      'GET', `/activity/chat?project=${encodeURIComponent(project)}${limit ? `&limit=${limit}` : ''}`),

  sendChat: (project: string, message: string, user?: string) =>
    apiCall<{ success: boolean }>('POST', '/activity/chat', { project, message, user }),

  markMentionsRead: (user?: string) =>
    apiCall<{ success: boolean }>('POST', '/activity/chat/mentions/read', { user }),

  // Files
  // N8: deep settings (project.json + publish switches of this machine).
  getAdvancedSettings: (project?: string) =>
    apiCall<{ project: AdvancedProject | null; switches: Record<string, AdvancedSwitch> }>(
      'GET', `/settings/advanced${project ? `?project=${encodeURIComponent(project)}` : ''}`),
  putAdvancedProject: (project: string, values: Record<string, unknown>) =>
    apiCall<AdvancedProject>('PUT', '/settings/advanced/project', { project, values }),
  putAdvancedSwitches: (values: Record<string, boolean | number | null>) =>
    apiCall<Record<string, AdvancedSwitch>>('PUT', '/settings/advanced/switches', { values }),

  // N7: note of a published file (modif_logs.json): the version clicked + the history.
  getPublishNote: (project_name: string, relPath: string) =>
    apiCall<{ base: string; version: string | null; latest: PublishNoteEntry | null; history: PublishNoteEntry[] }>(
      'GET', `/files/projects/${encodeURIComponent(project_name)}/publish-note?rel_path=${encodeURIComponent(relPath)}`),

  // Raw modif_logs.json entries touching a file, plus the folder's full log
  // (fallback when the file is not a publish output but the folder has a log).
  getFileLog: (project_name: string, relPath: string) =>
    apiCall<{
      base: string; version: string | null;
      matched: Record<string, unknown>[];
      folder_log: Record<string, unknown>[];
      folder_path: string;
    }>('GET', `/files/projects/${encodeURIComponent(project_name)}/file-log?rel_path=${encodeURIComponent(relPath)}`),

  // Disk manager: heaviest files under DOSSIER_PROJETS, optionally scoped to a project.
  getDiskUsage: (project?: string, limit = 200) =>
    apiCall<{
      root: string; total_bytes: number; file_count: number;
      top_files: { rel: string; project: string; size: number; mtime: number }[];
      by_project: { project: string; size: number; file_count: number }[];
    }>('GET', `/system/disk-usage?limit=${limit}${project ? `&project=${encodeURIComponent(project)}` : ''}`),

  // Settings > Desinstaller FLUX: what the uninstaller would remove / keep (read only).
  getUninstallPlan: () =>
    apiCall<{ remove: { label: string; paths: string[] }[]; keep: string[] }>('GET', '/system/uninstall-plan'),

  // setup: also list the project's setup files (_flux_setup/ and its JSON), hidden by default.
  browseProject: (project_name: string, subpath?: string, setup = false) => {
    const q = new URLSearchParams()
    if (subpath) q.set('subpath', subpath)
    if (setup) q.set('setup', 'true')
    const qs = q.toString()
    return apiCall<{ path: string; folders: { name: string; path: string }[]; files: FileEntry[] }>('GET', `/files/projects/${project_name}/browse${qs ? `?${qs}` : ''}`)
  },

  // Folder Manager
  // Copy Path Relative: $FLUX/DOSSIER_PROJETS/$PROD/.../$SEQ/$SHOT (FLUX Work scene variables).
  getRelativePath: (project: string, rel_path: string) =>
    apiCall<{ path: string }>('GET', `/folder/projects/${encodeURIComponent(project)}/relative-path?rel_path=${encodeURIComponent(rel_path)}`),
  getTokens: (project: string) =>
    apiCall<{ tokens: Record<string, Record<string, string>> }>('GET', `/folder/projects/${encodeURIComponent(project)}/tokens`),

  getProjects: () =>
    apiCall<{ projects: string[] }>('GET', '/folder/projects'),

  // Active project — single source of truth, persisted backend-side (config.json)
  getCurrentProject: () =>
    apiCall<{ project: string | null }>('GET', '/project/current'),

  setCurrentProject: (project: string) =>
    apiCall<{ project: string }>('PUT', '/project/current', { project }),

  // Work profiles shared by a project (project.json "ui.work_profiles", ADR 0042)
  getProjectWorkProfiles: (project: string) =>
    apiCall<{ profiles: unknown[] }>('GET', `/folder/projects/${encodeURIComponent(project)}/work-profiles`),
  setProjectWorkProfiles: (project: string, profiles: unknown[]) =>
    apiCall<{ profiles: unknown[] }>('PUT', `/folder/projects/${encodeURIComponent(project)}/work-profiles`, { profiles }),

  // project.json and its schema (the advanced settings window is generated from it).
  getProjectConfig: (project: string) =>
    apiCall<{ config: Record<string, unknown>; warnings: string[]; schema: Record<string, unknown> }>(
      'GET', `/folder/projects/${encodeURIComponent(project)}/config`),
  putProjectConfig: (project: string, settings: Record<string, unknown>) =>
    apiCall<{ config: Record<string, unknown> }>('PUT', `/folder/projects/${encodeURIComponent(project)}/config`, { settings }),

  createProject: (name: string, painter_presets?: string[]) =>
    apiCall<{ name: string; path: string }>('POST', '/folder/projects', { name, painter_presets: painter_presets ?? null }),
  // Painter export presets: shipped with FLUX (bundled) and those of a project.
  getPainterPresets: (project?: string) =>
    apiCall<{ bundled: string[]; project: string[] }>('GET', `/dcc/substance/presets${project ? `?project=${encodeURIComponent(project)}` : ''}`),
  putPainterPresets: (project: string, presets: string[]) =>
    apiCall<{ project: string[] }>('PUT', '/dcc/substance/presets', { project, presets }),

  // Hard-delete a whole project folder. Destructive: only call after the typed
  // confirmation in the Archives view.
  deleteProject: (name: string) =>
    apiCall<{ deleted: string }>('DELETE', `/folder/projects/${encodeURIComponent(name)}`),

  // Cleaning to the current FLUX layout (Disque page): only what is certain moves.
  scanCleanup: (project: string, asset?: string) =>
    apiCall<CleanupScan>('GET', `/folder/projects/${encodeURIComponent(project)}/cleanup${asset ? `?asset=${encodeURIComponent(asset)}` : ''}`, undefined, 300000),
  applyCleanup: (project: string, ids: string[], asset?: string) =>
    apiCall<{ done: number; moved: number; dropped: number; errors: string[]; journal: string }>(
      'POST', `/folder/projects/${encodeURIComponent(project)}/cleanup`, { asset: asset || null, ids }, 300000),
  getCleanupBackups: (project: string) =>
    apiCall<{ backups: { id: string; files: number }[] }>('GET', `/folder/projects/${encodeURIComponent(project)}/cleanup/backups`),
  restoreCleanup: (project: string, journal_id: string) =>
    apiCall<{ restored: number; already_there: string[] }>(
      'POST', `/folder/projects/${encodeURIComponent(project)}/cleanup/restore`, { journal_id }, 300000),
  cloneProject: (project: string, new_name: string) =>
    apiCall<{ project: string; files: number; moved: number; dropped: number; warnings: number }>(
      'POST', `/folder/projects/${encodeURIComponent(project)}/clone`, { new_name }, 3600000),

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
    apiCall<{ sequences: string[]; padding?: number }>('GET', `/folder/projects/${project}/sequences`),

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
  // builtin: also the read-only presets shipped by FLUX (Template Editor, New Scene).
  listPresets: (project: string, builtin = false) =>
    apiCall<{ presets: Preset[] }>('GET', `/folder/projects/${encodeURIComponent(project)}/presets${builtin ? '?builtin=1' : ''}`),

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

  // LOP: add the file to the selected Reference / Sublayer LOP, else a new one.
  houdiniImportLop: (project: string, rel_path: string, mode: 'reference' | 'payload' | 'sublayer') =>
    apiCall<{ ok: boolean; result?: { node_path?: string; mode?: string; entry?: number } }>(
      'POST', '/dcc/houdini/import/lop', { project, rel_path, mode },
    ),

  // Shelf
  getShelves: () =>
    apiCall<Record<string, { versions: string[]; installed: Record<string, boolean>; hdas_installed: Record<string, boolean> }>>('GET', '/shelf'),

  installShelf: (dcc: string, version: string) =>
    apiCall<{ success: boolean; message: string }>('POST', '/shelf/install', { dcc, version }),

  // Old FLUX files of a DCC after a reinstall (only FLUX's own, with why), then remove the ticked ones.
  getStaleShelfFiles: (dcc: string, version: string) =>
    apiCall<{ items: { path: string; reason: string }[] }>('GET', `/shelf/stale?dcc=${encodeURIComponent(dcc)}&version=${encodeURIComponent(version)}`),

  removeStaleShelfFiles: (dcc: string, version: string, paths: string[]) =>
    apiCall<{ removed: string[]; skipped: string[]; failed: string[] }>('POST', '/shelf/stale/remove', { dcc, version, paths }),

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
  getUsdLayers: (project: string, asset: string, task: string, instance = '') => {
    const qs = new URLSearchParams({ project, asset, task })
    if (instance) qs.set('instance', instance)
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

  // Crowd (A6, ADR 0022): which assets share a rig and which clips fit them.
  getUsdCrowdCompat: (project: string) => {
    const qs = new URLSearchParams({ project })
    return apiCall<UsdCrowdCompat>('GET', `/usd/crowd/compat?${qs}`)
  },


  // pins: {slot: {task, instance, version} | {exclude: true} | null (automatic again)}
  // ADR 0023: components are created by hand, then edited through their recipe.
  refreshUsdComponent: (project: string, name: string) =>
    apiCall<UsdComponentResult>('POST', '/usd/component/refresh', { project, name }),
  // ADR 0024: created with empty blocks (model / look / rig unless *blocks* is given).
  createUsdComponent: (project: string, name: string, blocks?: string[]) =>
    apiCall<UsdComponentResult>('POST', '/usd/component/create', { project, name, blocks }),
  saveUsdComponent: (project: string, name: string, recipe: UsdComponentRecipe) =>
    apiCall<UsdComponentResult>('POST', '/usd/component/save', { project, name, recipe }),
  addProposedUsdComponent: (project: string, name: string) =>
    apiCall<UsdComponentResult>('POST', '/usd/component/add-proposed', { project, name }),

  // A3: new versioned assembly (empty or copy of *source*) and edits (each = new version).
  createUsdAssembly: (project: string, name: string, source?: string) =>
    apiCall<UsdAssemblyEditResult>('POST', '/usd/assembly/create', { project, name, source }),
  editUsdAssembly: (project: string, name: string, ops: UsdAssemblyOp[]) =>
    apiCall<UsdAssemblyEditResult>('POST', '/usd/assembly/edit', { project, name, ops }),
  // The department table (ADR 0019): which task writes which USD department.
  // Assembled USD of one asset (component or decor assembly), Production "USD" task.
  getUsdAsset: (project: string, name: string) =>
    apiCall<UsdAssetInfo>('GET', `/usd/asset?${new URLSearchParams({ project, name })}`),

  // Shot stage (ADR 0020) of one shot: state, version, layers.
  getUsdShot: (project: string, seq: string, shot: string) =>
    apiCall<{ project: string; shots: UsdShotInfo[] }>('GET', `/usd/shots?${new URLSearchParams({ project, seq, shot })}`),

  generateUsdShot: (project: string, seq: string, shot: string, user: string, frozen = false) =>
    apiCall<{ ok: boolean; changed: boolean; version: string; last: string; warnings: string[] }>(
      'POST', '/usd/shot/generate', { project, seq, shot, user, frozen }),

  getUsdDepartments: () =>
    apiCall<{ tasks: Record<string, UsdTaskContribution>; order: Record<string, number>
              shot_tasks?: Record<string, UsdTaskContribution> }>(
      'GET', '/usd/departments'),

  // Read-only composition of a published USD file (prims, variants, layers used).
  getUsdComposition: (project: string, file: string) => {
    const qs = new URLSearchParams({ project, file })
    return apiCall<UsdComposition>('GET', `/usd/composition?${qs}`)
  },

  // Read instance placements from the open DCC: layout vNNN + LAST, then a new assembly version.
  publishUsdLayout: (project: string, name: string, dcc: 'houdini' | 'maya') =>
    apiCall<UsdAssemblyEditResult & { layout_version: string; layout: string; placements: number }>(
      'POST', '/usd/assembly/layout/publish', { project, name, dcc }),

  // Point one assembly instance at a component LAST or a frozen vNNN.

  relinkUsdInstance: (project: string, file: string, prim: string, component: string, version: string) =>
    apiCall<{ ok: boolean; prim: string; asset_path: string }>(
      'POST', '/usd/assembly/relink', { project, file, prim, component, version }),

  // ── Production Tab ─────────────────────────────────────────────────────────
  // GET returns production + reconciled publishes; PUT replaces the store.
  getProduction: (project: string) =>
    apiCall<ProductionPayload>('GET', `/production/${encodeURIComponent(project)}`),
  // Conditional variant used by useProduction: 304 when the server store is unchanged.
  getProductionConditional: (project: string, etag?: string) =>
    apiGetConditional<ProductionPayload>(`/production/${encodeURIComponent(project)}`, etag),

  // Saving production.json also mirrors the planning to disk (create-only) on the
  // backend — there is no separate "materialize" call any more; structure is kept
  // in sync automatically in both directions.
  setProduction: (project: string, production: ProductionState) =>
    apiCall<{ success: boolean; synced?: Record<string, number>; locked_kept?: string[] }>(
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
  }, opts: { count?: boolean } = {}) => {
    const qs = new URLSearchParams({ kind: params.kind })
    if (params.class_token) qs.set('class_token', params.class_token)
    if (params.name)        qs.set('name', params.name)
    if (params.seq)         qs.set('seq', params.seq)
    if (params.shot)        qs.set('shot', params.shot)
    if (opts.count === false) qs.set('count', 'false')   // folder only, no recursive walk
    return apiCall<{ rel_path: string; exists: boolean; file_count: number }>(
      'GET', `/production/${encodeURIComponent(project)}/entity-folder?${qs}`)
  },

  // Move an entity folder into <project>/ARCHIVE/<timestamp>/ (never hard-delete).
  // The caller removes the logical entity from production.json after this resolves.
  archiveEntity: (project: string, relPath: string) =>
    apiCall<{ archived: boolean; archived_to?: string; reason?: string }>(
      'POST', `/production/${encodeURIComponent(project)}/archive`, { rel_path: relPath }),

  // Delete a sequence / shot server-side: archive its folders (shot + comp / lighting),
  // drop its tokens, remove it from production.json with a tombstone (never comes back).
  // Rename a sequence / shot in production.json AND on disk (refused with 409 while it
  // holds published files: their names and USD paths carry the old name).
  renameSeqShot: (project: string, kind: 'seq' | 'shot', seq: string, shot: string, newName: string) =>
    apiCall<{ ok: boolean; archived: string; path: string; warnings: string[] }>(
      'POST', `/production/${encodeURIComponent(project)}/rename-seq-shot`, { kind, seq, shot, new: newName }),

  // Team calendar of a project: commitments, proposals (ping) and answers.
  getCalendar: (project: string) =>
    apiCall<{ items: CalendarItem[]; me: string }>('GET', `/calendar/${encodeURIComponent(project)}`),
  // Tractor farm render (ADR 0015, backend routers/render.py)
  renderSettings: (project: string) =>
    apiCall<RenderSettingsResponse>('GET', `/render/settings?project=${encodeURIComponent(project)}`),
  renderSaveSettings: (project: string, patch: Partial<RenderSettings>) =>
    apiCall<RenderSettingsResponse>('PUT', `/render/settings?project=${encodeURIComponent(project)}`, patch),
  renderShots: (project: string) =>
    apiCall<{ shots: RenderShot[] }>('GET', `/render/shots?project=${encodeURIComponent(project)}`),
  renderUsdRange: (project: string, path: string) =>
    apiCall<{ frame_start: number | null; frame_end: number | null }>('GET',
      `/render/usd_range?project=${encodeURIComponent(project)}&path=${encodeURIComponent(path)}`),
  renderSubmit: (body: {
    project: string; seq?: string; shot?: string; usd_path?: string
    frame_start?: number; frame_end?: number; renderer?: string; freeze?: boolean; chunk_size?: number
    start_at?: string   // "YYYY-MM-DDTHH:MM" local; omitted = now
    freeze_when?: RenderFreezeWhen   // with start_at: freeze when the job starts or now; omitted = team default
    hosts?: string[]; groups?: string[]   // only these machines / groups (team groups or rooms)
    share_percent?: number; share_of?: RenderShareBase   // omitted = team default (job_share)
    priority?: number   // this job only, omitted = team default
    denoise?: boolean; denoise_crossframe?: boolean   // RenderMan denoise_batch after the render (same job)
  }) => apiCall<RenderSubmitResult>('POST', '/render/submit', body, 120000),   // freezing can be slow
  // Denoise of an already rendered sequence (RenderMan denoise_batch on the farm, into <folder>/denoised).
  renderDenoise: (body: {
    project: string; path: string; frame_start?: number; frame_end?: number; crossframe?: boolean; priority?: number
  }) => apiCall<{
    dry_run: boolean; jid?: number | null; files: { alf: string; json: string }; title: string; output: string
    frames: [number, number]; count: number; pattern: string; warnings: string[]; priority_warning?: string | null
  }>('POST', '/render/denoise', body, 60000),
  renderJobs: (project: string, scope: RenderJobScope, days = 30) =>
    apiCall<{ jobs: RenderJob[]; dry_run?: boolean; tractor_project?: string; finished?: { jid: number; title: string; output?: string }[] }>(
      'GET', `/render/jobs?project=${encodeURIComponent(project)}&scope=${scope}&days=${days}`),
  renderJobTasks: (project: string, jid: number) =>
    apiCall<{ tasks: RenderTask[] }>('GET', `/render/jobs/${jid}/tasks?project=${encodeURIComponent(project)}`),
  renderTaskLog: (project: string, jid: number, tid: number) =>
    apiCall<{ log: string }>('GET', `/render/jobs/${jid}/tasks/${tid}/log?project=${encodeURIComponent(project)}`, undefined, 60000),
  renderLast: (project: string) =>
    apiCall<{ last: Partial<RenderLastForm> }>('GET', `/render/last?project=${encodeURIComponent(project)}`),
  renderSaveLast: (project: string, last: RenderLastForm) =>
    apiCall<{ ok: boolean }>('PUT', `/render/last?project=${encodeURIComponent(project)}`, last),
  // Exit codes seen on the team's failed FLUX renders (husk), most frequent first; proposed = can be added.
  renderExitCodes: (project: string) =>
    apiCall<{ codes: RenderExitCode[]; warning: string | null }>('GET',
      `/render/exit_codes?project=${encodeURIComponent(project)}`),
  renderTractorProjects: (project: string) =>
    apiCall<{ projects: { name: string; jobs: number }[]; current: string }>('GET',
      `/render/tractor_projects?project=${encodeURIComponent(project)}`),
  renderFarm: (project: string) =>
    apiCall<RenderFarm>('GET', `/render/farm?project=${encodeURIComponent(project)}`),
  renderJobAction: (project: string, jid: number, action: RenderJobAction) =>
    apiCall<unknown>('POST', `/render/jobs/${jid}/${action}?project=${encodeURIComponent(project)}`),
  renderJobPriority: (project: string, jid: number, priority: number) =>
    apiCall<{ jid: number; priority: number; priority_warning: string | null }>('POST',
      `/render/jobs/${jid}/priority?project=${encodeURIComponent(project)}`, { priority }),
  // Environment screen (school farm config, locked by "Understand" + password; backend checks both)
  renderEnvState: (project: string, unlock: RenderEnvUnlock) =>
    apiCall<RenderEnvState>('POST', `/render/env/state?project=${encodeURIComponent(project)}`, unlock),
  renderEnvShares: (project: string, unlock: RenderEnvUnlock, teams: Record<string, RenderShareRule>) =>
    apiCall<{ path: string; backup: string; shares: Record<string, Record<string, RenderShareRule>> }>('PUT',
      `/render/env/shares?project=${encodeURIComponent(project)}`, { ...unlock, teams }),
  renderEnvReload: (project: string, unlock: RenderEnvUnlock) =>
    apiCall<{ reloaded: string }>('POST', `/render/env/reload?project=${encodeURIComponent(project)}`, unlock),
  // Engine dispatch trace of a job ("Trace Job"), read only, any job.
  renderJobTrace: (project: string, jid: number) =>
    apiCall<{ trace: string }>('GET', `/render/jobs/${jid}/trace?project=${encodeURIComponent(project)}`, undefined, 60000),

  getCalendarPublishes: (project: string, start: string, end: string) =>
    apiCall<{ publishes: CalendarPublish[] }>('GET', `/calendar/${encodeURIComponent(project)}/publishes?start=${start}&end=${end}`),
  createCalendarItem: (project: string, body: { title: string; owner: string; start: string; end: string; note: string; link: string }) =>
    apiCall<{ item: CalendarItem }>('POST', `/calendar/${encodeURIComponent(project)}/items`, body),
  respondCalendarItem: (project: string, id: string, action: 'accept' | 'postpone' | 'decline', start = '', end = '') =>
    apiCall<{ item: CalendarItem }>('POST', `/calendar/${encodeURIComponent(project)}/items/${encodeURIComponent(id)}/respond`, { action, start, end }),
  updateCalendarItem: (project: string, id: string, patch: Partial<Pick<CalendarItem, 'title' | 'note' | 'link' | 'start' | 'end' | 'status'>>) =>
    apiCall<{ item: CalendarItem }>('PATCH', `/calendar/${encodeURIComponent(project)}/items/${encodeURIComponent(id)}`, patch),
  deleteCalendarItem: (project: string, id: string) =>
    apiCall<{ ok: boolean }>('DELETE', `/calendar/${encodeURIComponent(project)}/items/${encodeURIComponent(id)}`),

  // Lock / unlock a sequence or shot (unlock needs phrase "Understand").
  lockSeqShot: (project: string, kind: 'seq' | 'shot', seq: string, shot: string, locked: boolean, phrase = '') =>
    apiCall<{ ok: boolean; locked: { by: string; at: string } | null }>(
      'POST', `/production/${encodeURIComponent(project)}/lock`, { kind, seq, shot, locked, phrase }),

  deleteSeqShot: (project: string, kind: 'seq' | 'shot', seq: string, shot = '') =>
    apiCall<{ ok: boolean; archived: string[]; tokens_dropped: string[]; removed_ids: string[] }>(
      'POST', `/production/${encodeURIComponent(project)}/delete-seq-shot`, { kind, seq, shot }),

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

  // Every version of a /ref zone, newest first, from its modif log (retake 10).
  getRefVersions: (project: string, relPath: string) => {
    const qs = new URLSearchParams({ rel_path: relPath })
    return apiCall<{ versions: RefVersion[] }>(
      'GET', `/production/${encodeURIComponent(project)}/ref/versions?${qs}`)
  },

  // LAST media of each task of the given shots (Timeline preview, auto edit).
  getShotPreviews: (project: string, shots: Array<{ seq: string; shot: string; tasks: string[] }>) =>
    apiCall<{ shots: Array<{ seq: string; shot: string; media: ShotPreviewMedia[] }> }>(
      'POST', `/production/${encodeURIComponent(project)}/shot-previews`, { shots }),

  // Export of the Timeline auto edit: media + .otio + .edl and/or one H.264 .mov (ffmpeg).
  exportMontage: (project: string, body: {
    name: string; dest_dir: string; fps: number; mov?: boolean; folder?: boolean
    clips: Array<{ seq: string; shot: string; frames: number; media: { task: string; label: string; rel_path: string; file: string; source?: string } | null }>
  }) =>
    apiCall<{ dir: string; mov: string | null; otio: string | null; edl: string | null; shots: number; missing: number; warnings: string[] }>(
      'POST', `/production/${encodeURIComponent(project)}/montage/export`, body, 30 * 60 * 1000),

  // Keyframe Pro (retake 09): status of this machine, open pipeline videos.
  keyframeStatus: () => apiCall<KeyframeStatus>('GET', '/review/keyframe/status', undefined, 8000),
  keyframeOpen: (project: string, items: Array<{ rel_path?: string; path?: string; label?: string }>, title = 'FLUX', siblings = true) =>
    apiCall<KeyframeOpenResult>('POST', '/review/keyframe/open', { project, items, title, siblings }),

  // Streamable URL for the <img>/<video> src (Range-enabled backend).
  refFileUrl: (project: string, relPath: string, name: string, scope: 'ref' | 'publish' = 'ref', rev?: number | string) => {
    const qs = new URLSearchParams({ rel_path: relPath, name, ...(scope === 'publish' ? { scope } : {}), ...(rev ? { rev: String(rev) } : {}) })
    return `${BASE_URL}/production/${encodeURIComponent(project)}/ref/file?${qs}`
  },

  // Delete one vNNN file of a /ref zone (LAST is re-pointed by the backend).
  deleteRefVersion: (project: string, relPath: string, name: string) =>
    apiCall<{ ok: boolean; deleted: string; last: string }>(
      'POST', `/production/${encodeURIComponent(project)}/ref/delete`, { rel_path: relPath, name }),

  // Set an older version as LAST (re-deposited as the next version).
  restoreRefVersion: (project: string, relPath: string, name: string) =>
    apiCall<{ ok: boolean; version: string; file: string }>(
      'POST', `/production/${encodeURIComponent(project)}/ref/restore`, { rel_path: relPath, name }),

  exportRef: (project: string, relPath: string, name: string, destPath: string) =>
    apiCall<{ ok: boolean; dest: string }>(
      'POST', `/production/${encodeURIComponent(project)}/ref/export`,
      { rel_path: relPath, name, dest_path: destPath }),
}

// USD assembler library (GET /usd/library)
// ADR 0023 + 0024: a component is created by hand; its recipe groups links (files) in
// blocks; each link names its task (asset TYPE token), how it is composed (arc), an
// optional variant name (exclusive choice in its block) and a proxy flag.
export type UsdFileKind = 'geometry' | 'groom' | 'shader' | 'rig' | 'animation' | 'other'
export type UsdLinkArc = 'reference' | 'sublayer' | 'payload'
// variant = default choice; deferred = heavy block loaded apart (payload, ADR 0031)
export interface UsdComponentBlock { name: string; variant: string; deferred?: boolean }
export interface UsdComponentFile {
  id: string; label: string; block: string; department: string; kind: UsdFileKind; format: string
  source: 'publish' | 'manual'
  arc: UsdLinkArc; variant: string; proxy: boolean
  base?: string; instance?: string; variante?: string; version?: string   // publish ("latest" or vNNN)
  path?: string                                                           // manual, project-relative
  prim?: string
  targets: string[]; proxy_of: string[]; depends: string[]
  active: boolean
  // library only: what the file resolves to now / in the current component version
  resolved_version?: string | null; composed_version?: string | null; found?: boolean
}
export interface UsdComponentRecipe { blocks: UsdComponentBlock[]; departments: string[]; files: UsdComponentFile[] }
export interface UsdProposedFile {
  department: string; base: string; instance: string; variante: string; version: string
  format: string; kind: UsdFileKind
  path?: string   // non-USD publish (abc, fbx...): its LAST, linked as a file
}
export interface UsdComponentInfo {
  name: string
  class: string | null   // CLASS token (deep link to Production)
  tokens: Record<string, string>   // classification tokens from tokens.json (UI sort / filter, retake 03)
  state: 'ok' | 'stale' | 'empty'
  legacy: boolean        // written before ADR 0023: saved again in the new format on the next update
  version: string | null
  versions: string[]
  blocks: UsdComponentBlock[]
  departments: string[]
  files: UsdComponentFile[]
  proposed: UsdProposedFile[]   // publishes of every task not linked yet
  variant_sets: Record<string, string[]>   // of the current version (assembly instances pick in them)
  warnings: string[]
  dir: string
  last: string | null
  used_by: string[]
}
export interface UsdComponentResult {
  ok: boolean; changed: boolean; version: string | null; last?: string; warnings: string[]
}
export interface UsdAssemblyInstance {
  prim: string; asset_path: string; component: string | null; broken: boolean; follows_last: boolean
  variants: Record<string, string>   // variant set (one per component file) -> variant picked by this instance
}
export interface UsdAssemblyInfo {
  name: string; class?: string; file: string; instances: UsdAssemblyInstance[]; broken: number
  tokens: Record<string, string>   // {} for a legacy flat file
  version: string | null      // current vNNN (null = legacy flat file)
  versions: string[]
  legacy: boolean             // old builder file, converted on first edit
  layout: string | null       // layout LAST published from a DCC
  layout_version: string | null   // layout vNNN pinned by the current assembly version
}
// A3 edit operations (backend assembly_v2.apply_ops).
export type UsdAssemblyOp =
  | { op: 'add'; component: string; count?: number; version?: string }
  | { op: 'remove'; name: string }
  | { op: 'duplicate'; name: string }
  | { op: 'rename'; name: string; new_name: string }
  | { op: 'relink'; name: string; component: string; version?: string }
  | { op: 'set_version'; name?: string; all?: boolean; version: string }
  | { op: 'set_variant'; name: string; department: string; variant: string }   // '' = component default
export interface UsdAssemblyEditResult { ok: boolean; changed: boolean; version: string | null; warnings: string[] }
export interface UsdLibrary {
  project: string; components: UsdComponentInfo[]; assemblies: UsdAssemblyInfo[]
  creatable: string[]      // asset NAMEs without a component (created by hand, ADR 0023)
  departments: string[]    // asset TYPE tokens of the project
  token_keys: string[]     // token categories present (CLASS first), for sort / filter
  rules: UsdComponentRules
}
export interface UsdComponentRules {
  kinds: UsdFileKind[]
  default_kind: Record<string, UsdFileKind>          // TYPE -> kind
  targets: Record<UsdFileKind, UsdFileKind[]>        // what a file of that kind may target
  proxy: Partial<Record<UsdFileKind, UsdFileKind[]>> // what it may stand in for as a proxy
  preview: UsdFileKind[]                             // never active in a component (ANIM)
  block_of_task?: Record<string, string>              // TYPE -> block name (GEO -> model)
}
export interface LoadTargets {
  what: 'asset' | 'decor' | 'shot' | 'layer' | 'file'
  legacy: boolean
  message: string
  targets: { label: string; rel_path: string; primary: boolean; what: string }[]
}
export interface UsdAssetFile {
  id: string; department: string; base: string; label?: string; instance?: string
  resolved_version: string | null; composed_version: string | null; found: boolean; active?: boolean
}
export interface UsdAssetInfo {
  project: string; name: string; class: string | null
  component: null | {
    version: string; versions: string[]; state: 'ok' | 'stale' | 'empty'; legacy: boolean
    departments: string[]; files: UsdAssetFile[]; proposed: { department: string; base: string }[]
    warnings: string[]; last: string | null
  }
  assembly: null | {
    version: string; versions: string[]; file: string; broken: number
    instances: { prim: string; component: string | null; broken: boolean }[]
  }
  used_by: string[]
}
export interface UsdShotInfo {
  seq: string; shot: string; entity: string
  state: 'none' | 'up_to_date' | 'outdated' | 'frozen'
  versions: string[]; last_version: string | null; last: string | null; rel_last: string | null
  departments: { department: string; task: string; files: string[] }[]
  range: [number, number] | null; fps: number | null; warnings: string[]
  render?: { camera: string; resolution: [number, number] }   // render layer (ADR 0060)
}
export interface MayaUsdTreeNode { name: string; path: string; type: 'group' | 'joint'; children: MayaUsdTreeNode[] }
export interface MayaUsdPreview {
  ok: boolean; preset: string; scope: string
  // model: meshes; anim: moving joints; look: materials
  items?: { name: string; path?: string; points?: number; faces?: number; uv?: boolean
            color_sets?: string[]; skinned?: boolean; token?: string; channels?: string[]
            type?: string; meshes?: number; focal?: number }[]
  // rig
  tree?: MayaUsdTreeNode[]; joints?: number; roots?: string[]
  skinned?: { name: string; joints: number }[]; controllers?: number
  sampled?: number; geometry?: number
}
export interface UsdTaskContribution {
  department: string
  label?: string          // preset name in the Publisher (model / rig / anim / look)
  what: string
  // Which exporter writes this department: the skinned-mesh/skeleton one, or the look one.
  writer: 'light' | 'look'
  include: { geo: boolean; skel: boolean; anim: boolean; weights: boolean; uv: boolean }
}
export interface LookExportResult {
  ok: boolean; asset: string; version: string; root: string
  materials: number; bindings: number; warnings?: string[]
}
export interface UsdPrimNode {
  path: string; name: string; type: string; kind: string; purpose: string
  instanceable: boolean
  variant_sets: Record<string, { selection: string; variants: string[] }>
  arcs: { arc: string; asset: string; prim: string }[]
  children: UsdPrimNode[]
  truncated: boolean
}
// N8 "Parametres avances" (GET /settings/advanced).
export interface AdvancedProject {
  name: string; project_id: string; last_modes: string[]; warnings: string[]
  values: {
    fps: number; resolution: [number, number]; ocio_config: string; env: Record<string, string>
    usd: { meters_per_unit: number; up_axis: string }
    storage: { last_mode: Record<string, string>; last_link_threshold_gb: number }
  }
}
export interface AdvancedSwitch {
  value: boolean | number; saved: boolean | number | null; env: string; source: 'page' | 'lancement' | 'defaut'
}

export interface PublishNoteEntry {
  name: string; date: string; time: string; version: string; modification: string; user: string
}

// Crowd (A6, ADR 0022): shared skeletons and animation clips (GET /usd/crowd/compat).
export interface UsdCrowdClip {
  base: string; asset: string; clip: string; last: string
  joints: string[]; range: [number, number] | null; fps: number
}
export interface UsdCrowdCompat {
  assets: Record<string, { signature: string; joint_count: number; compatible: string[]; clips: string[] }>
  clips: UsdCrowdClip[]
}

export interface UsdComposition {
  file: string; default_prim: string
  layers: { path: string; root: boolean }[]
  tree: UsdPrimNode | null
}

// /ref versions (retake 10): one row per deposit, from the ref folder's modif log.
export interface RefVersion {
  version: string; file: string; ext: string; kind: string
  user: string; date: string; time: string
  source_name: string      // name of the dropped file
  logged: boolean          // false: file older than the log (no author / date)
  available: boolean       // file still on disk
  playable: boolean        // the renderer can show it (mov / mkv often cannot)
  latest: boolean          // what LAST is a copy of
}
export interface ShotPreviewMedia {
  task: string; rel_path: string; file: string; ext: string; kind: string
  version: string; version_file: string; version_count: number; abs_path: string
  source?: 'ref' | 'publish'      // publish = DCC publish in the task folder (no /ref drop)
}
// Keyframe Pro (retake 09, backend features/review/keyframe.py).
export interface KeyframeStatus {
  installed: boolean; exe: string; flavor: '' | 'pro' | 'mp'
  api: 'ready' | 'not_running' | 'not_licensed' | 'error'
}
export interface KeyframeOpenResult {
  mode: 'api' | 'cli' | 'none'
  code?: string
  message: string
  opened: Array<{ path: string; label?: string }>
  skipped: Array<{ path: string; label?: string; reason: string }>
  siblings?: number
}
