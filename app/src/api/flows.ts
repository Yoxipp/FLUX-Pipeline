// flows.ts — API calls of the Flows editor (03_EDITEUR §9).
// P0: read-only, on top of the v1 action routes. P1 adds the /flows routes, P2 the runs.
// The TD boxes themselves (flows_td, flows_team_td) are written through /settings/user-data.

import { api, apiCall } from './client'
import type { ActionCatalog, ActionGraph } from '../types'
import type { FlowCatalog, FlowDoc, FlowListItem, FlowRead, FlowRights, FlowScope, FlowState, Issue, MigrateReport, RunRecord, RunStatus, RunSummary, SaveResult, VersionList } from '../pages/flow_editor/types'

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
  migrate: (dry_run: boolean): Promise<MigrateReport> =>
    apiCall<MigrateReport>('POST', '/flows/migrate', { dry_run }),

  // runs (01 §4, §6). 409 = refused (detail.issues), skipped (run_policy) or not active.
  run: (name: string, opts: RunOpts): Promise<{ run_id: string; status: RunStatus; mode: 'real' | 'dry' }> =>
    apiCall('POST', `/flows/${encodeURIComponent(name)}/run`, opts),
  listRuns: (opts: { flow?: string; scope?: FlowScope; project?: string; status?: RunStatus; limit?: number } = {}): Promise<RunSummary[]> =>
    apiCall<RunSummary[]>('GET', `/flows/runs${qs(opts)}`),
  getRun: (runId: string, project?: string): Promise<RunRecord> =>
    apiCall<RunRecord>('GET', `/flows/runs/${encodeURIComponent(runId)}${qs({ project })}`),
  cancelRun: (runId: string, project?: string): Promise<{ status: string }> =>
    apiCall('POST', `/flows/runs/${encodeURIComponent(runId)}/cancel${qs({ project })}`),
}
