// flows.ts — API calls of the Flows editor (03_EDITEUR §9).
// P0: read-only, on top of the v1 action routes. P1 adds the /flows routes, P2 the runs.
// The TD boxes themselves (flows_td, flows_team_td) are written through /settings/user-data.

import { api, apiCall, BASE_URL } from './client'
import type { ActionCatalog, ActionGraph } from '../types'
import type { ActivationGate, BridgeInfo, BridgeInstallResult, FlowCatalog, HostInfo, FlowDoc, FlowListItem, FlowRead, FlowRights, FlowScope, FlowState, Issue, MigrateReport, PageDataOp, PageDataRead, PageDoc, PageIssue, PageLink, PageList, PageRead, PageScope, RunRecord, RunStatus, RunSummary, SaveResult, VersionList, PagePorts, PageFlows, PageClickRun, PageTarget } from '../pages/flow_editor/types'

// Fired after a TD box changes so open views (Advanced, editor) re-read the rights.
export const FLOW_RIGHTS_EVENT = 'flux:flows-rights'

export interface RunOpts {
  scope?: FlowScope
  project?: string
  event?: string
  values?: Record<string, unknown>
  dry_run?: boolean          // on the saved file (TD)
  draft?: FlowDoc            // the open document, no version created (TD)
  base_revision?: number
  version?: number           // dry run of a frozen version (activation dialog)
}

// confirmed_destructive: ids of the `!` nodes validated with the slider (409 E_DESTRUCTIVE_UNCONFIRMED otherwise).
export interface SaveOpts { project?: string; base_revision?: number; force?: boolean; note?: string; confirmed_destructive?: string[] }

function qs(params: Record<string, string | number | undefined>): string {
  const q = Object.entries(params).filter(([, v]) => v !== undefined && v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join('&')
  return q ? `?${q}` : ''
}

export const flowsApi = {
  listV1Actions: (): Promise<string[]> => api.getActionGraphList(),
  getV1Action:   (name: string): Promise<ActionGraph> => api.getActionGraph(name),
  getV1Catalog:  (): Promise<ActionCatalog> => api.getActionCatalog(),
  getRights:     (): Promise<FlowRights> => apiCall<FlowRights>('GET', '/flows/rights'),
  getCatalog:    (): Promise<FlowCatalog> => apiCall<FlowCatalog>('GET', '/flows/catalog'),
  nodeTemplate:  (): Promise<{ filename: string; text: string; folder: string | null }> => apiCall('GET', '/flows/nodes/template'),
  // Team Python node (Team TD): error = load error of this file (the file is kept).
  saveTeamNode:  (name: string, code: string): Promise<{ file: string; error: string | null }> =>
    apiCall('POST', '/flows/nodes', { name, code }),
  // P4: issues of the open document (the backend is the reference, 01 §8). Never writes.
  validate: (flow: FlowDoc, scope: FlowScope, project?: string): Promise<{ issues: Issue[]; valid: boolean }> =>
    apiCall('POST', '/flows/validate', { flow, scope, project }),

  // v2 store (01 §14). project = active project name, needed for the project scope.
  list: (project?: string): Promise<FlowListItem[]> =>
    apiCall<FlowListItem[]>('GET', `/flows${qs({ project })}`),
  get: (name: string, opts: { scope?: FlowScope; project?: string; version?: number } = {}): Promise<FlowRead> =>
    apiCall<FlowRead>('GET', `/flows/${encodeURIComponent(name)}${qs(opts)}`),
  // base_revision undefined = new flow (Nouveau, Enregistrer sous): 409 if the name exists.
  save: (flow: FlowDoc, scope: FlowScope, opts: SaveOpts = {}): Promise<SaveResult> =>
    apiCall('PUT', `/flows/${encodeURIComponent(flow.name)}`, { flow, scope, ...opts }),
  increment: (name: string, scope: FlowScope, flow: FlowDoc | null, opts: SaveOpts = {}): Promise<SaveResult & { created: number | null }> =>
    apiCall('POST', `/flows/${encodeURIComponent(name)}/increment`, { flow, scope, ...opts }),
  versions: (name: string, scope: FlowScope, project?: string): Promise<VersionList> =>
    apiCall<VersionList>('GET', `/flows/${encodeURIComponent(name)}/versions${qs({ scope, project })}`),
  // Revenir a vN: the working file becomes vN, frozen as v(max+1) (nothing is lost).
  revert: (name: string, scope: FlowScope, to_version: number, project?: string): Promise<{ state: FlowState; created: number | null }> =>
    apiCall('POST', `/flows/${encodeURIComponent(name)}/revert`, { scope, project, to_version }),
  copy: (name: string, from_scope: FlowScope, to_scope: FlowScope, opts: { project?: string; new_name?: string } = {}): Promise<{ state: FlowState; scope: FlowScope; name: string }> =>
    apiCall('POST', `/flows/${encodeURIComponent(name)}/copy`, { from_scope, to_scope, ...opts }),
  // P5 activation (01 §8): 0 error, warnings read (acked), dry run passed on `current`.
  activation: (name: string, scope: FlowScope, project?: string): Promise<ActivationGate> =>
    apiCall<ActivationGate>('GET', `/flows/${encodeURIComponent(name)}/activation${qs({ scope, project })}`),
  activate: (name: string, scope: FlowScope, acked: { code: string; node: string | null; port: string | null }[], project?: string): Promise<FlowState> =>
    apiCall('POST', `/flows/${encodeURIComponent(name)}/activate`, { scope, project, acked }),
  deactivate: (name: string, scope: FlowScope, project?: string): Promise<FlowState> =>
    apiCall('POST', `/flows/${encodeURIComponent(name)}/deactivate`, { scope, project }),
  host: (): Promise<HostInfo> => apiCall<HostInfo>('GET', '/flows/host'),
  // P6a: Deverrouiller a shipped flow / DCC node = team copy (Team TD); remove = to _trash/ (on that
  // copy: Revenir au defaut).
  unlock: (name: string, project?: string): Promise<{ state: FlowState; scope: FlowScope; name: string }> =>
    apiCall('POST', `/flows/${encodeURIComponent(name)}/unlock`, { scope: 'team', project }),
  remove: (name: string, scope: FlowScope, project?: string): Promise<{ trash: string }> =>
    apiCall('DELETE', `/flows/${encodeURIComponent(name)}${qs({ scope, project })}`),
  migrate: (dry_run: boolean): Promise<MigrateReport> =>
    apiCall<MigrateReport>('POST', '/flows/migrate', { dry_run }),
  // P6c: extension bridges. install / uninstall act on this machine (no right needed);
  // a conflict without overwrite changes nothing ({success: false, conflicts}). flows = Team TD.
  bridges: (): Promise<{ dir: string | null; bridges: BridgeInfo[] }> => apiCall('GET', '/flows/bridges'),
  installBridge: (soft: string, overwrite = false): Promise<BridgeInstallResult> =>
    apiCall('POST', `/flows/bridges/${encodeURIComponent(soft)}/install`, { overwrite }),
  uninstallBridge: (soft: string): Promise<BridgeInstallResult> =>
    apiCall('POST', `/flows/bridges/${encodeURIComponent(soft)}/uninstall`, {}),
  bridgeFlows: (soft: string, scene_ext: string, overwrite = false): Promise<{ flows: { kind: string; name: string; status: 'written' | 'kept' }[] }> =>
    apiCall('POST', `/flows/bridges/${encodeURIComponent(soft)}/flows`, { scene_ext, overwrite }),

  // runs (01 §4, §6). 409 = refused (detail.issues), skipped (run_policy) or not active.
  run: (name: string, opts: RunOpts): Promise<{ run_id: string; status: RunStatus; mode: 'real' | 'dry' }> =>
    apiCall('POST', `/flows/${encodeURIComponent(name)}/run`, opts),
  listRuns: (opts: { flow?: string; scope?: FlowScope; project?: string; status?: RunStatus; mode?: 'real' | 'dry'; event?: string; limit?: number } = {}): Promise<RunSummary[]> =>
    apiCall<RunSummary[]>('GET', `/flows/runs${qs(opts)}`),
  getRun: (runId: string, project?: string): Promise<RunRecord> =>
    apiCall<RunRecord>('GET', `/flows/runs/${encodeURIComponent(runId)}${qs({ project })}`),
  cancelRun: (runId: string, project?: string): Promise<{ status: string }> =>
    apiCall('POST', `/flows/runs/${encodeURIComponent(runId)}/cancel${qs({ project })}`),

  // TOOL pages (P7). Reads for everyone; save, delete, rename need the Team TD box.
  listPages: (project?: string): Promise<PageList> => apiCall('GET', `/flows/pages${qs({ project })}`),
  getPage: (id: string, opts: { scope?: PageScope; project?: string } = {}): Promise<PageRead> =>
    apiCall('GET', `/flows/pages/${encodeURIComponent(id)}${qs(opts)}`),
  savePage: (page: PageDoc, scope: PageScope, opts: { project?: string; base_rev?: string | null; force?: boolean } = {}): Promise<{ rev: string; changed: boolean; issues: PageIssue[] }> =>
    apiCall('PUT', `/flows/pages/${encodeURIComponent(page.id)}`, { page, scope, ...opts }),
  deletePage: (id: string, scope: PageScope, project?: string): Promise<{ trash: string }> =>
    apiCall('DELETE', `/flows/pages/${encodeURIComponent(id)}${qs({ scope, project })}`),
  validatePage: (page: PageDoc, scope: PageScope, project?: string): Promise<{ issues: PageIssue[] }> =>
    apiCall('POST', '/flows/pages/validate', { page, scope, project }),
  pageLinks: (project?: string): Promise<Record<string, PageLink[]>> =>
    apiCall('GET', `/flows/pages/links${qs({ project })}`),
  // InputsPageReader (ADR 0068): the flow picks its page. Ports of the node, who listens, a click.
  pagePorts: (page: string, project?: string): Promise<PagePorts> =>
    apiCall('GET', `/flows/pages/${encodeURIComponent(page)}/ports${qs({ project })}`),
  pageFlows: (page: string, project?: string): Promise<PageFlows> =>
    apiCall('GET', `/flows/pages/${encodeURIComponent(page)}/flows${qs({ project })}`),
  clickPage: (page: string, body: { button: string; values: Record<string, unknown>; project?: string }): Promise<{ runs: PageClickRun[] }> =>
    apiCall('POST', `/flows/pages/${encodeURIComponent(page)}/click`, body),
  // Generated Publisher panel of an extension software (04 §7): interface of its flow publish_<soft>.
  publishPanel: (soft: string, project?: string): Promise<{ soft: string; flow: string; page: PageDoc; issues: PageIssue[]; target: PageTarget }> =>
    apiCall('GET', `/flows/pages/publish_panel/${encodeURIComponent(soft)}${qs({ project })}`),
  // Page data (ADR 0066): records merged from every author's journal; etag = nothing moved since.
  pageData: (page: string, collection: string, opts: { project?: string; etag?: string } = {}): Promise<PageDataRead> =>
    apiCall('GET', `/flows/pages/${encodeURIComponent(page)}/data/${encodeURIComponent(collection)}${qs(opts)}`),
  writePageData: (page: string, collection: string, ops: PageDataOp[], project?: string): Promise<{ rids: string[]; etag: string }> =>
    apiCall('POST', `/flows/pages/${encodeURIComponent(page)}/data/${encodeURIComponent(collection)}`, { ops, project }),
  // The backend copies the picked local file (bytes never go through the API, ADR 0005).
  addPageImage: (page: string, collection: string, path: string, project?: string): Promise<{ image: string }> =>
    apiCall('POST', `/flows/pages/${encodeURIComponent(page)}/data/${encodeURIComponent(collection)}/media`, { path, project }),
  pageImageUrl: (page: string, collection: string, image: string, project?: string): string =>
    `${BASE_URL}/flows/pages/${encodeURIComponent(page)}/data/${encodeURIComponent(collection)}/media/${encodeURIComponent(image.replace(/^media\//, ''))}${qs({ project })}`,
}
