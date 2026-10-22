// flows.ts — API calls of the Flows editor (03_EDITEUR §9).
// P0: read-only, on top of the v1 action routes. P1 adds the /flows routes one by one.
// The TD boxes themselves (flows_td, flows_team_td) are written through /settings/user-data.

import { api, apiCall } from './client'
import type { ActionCatalog, ActionGraph } from '../types'
import type { FlowRights } from '../pages/flow_editor/types'

// Fired after a TD box changes so open views (Advanced, editor) re-read the rights.
export const FLOW_RIGHTS_EVENT = 'flux:flows-rights'

export const flowsApi = {
  listV1Actions: (): Promise<string[]> => api.getActionGraphList(),
  getV1Action:   (name: string): Promise<ActionGraph> => api.getActionGraph(name),
  getV1Catalog:  (): Promise<ActionCatalog> => api.getActionCatalog(),
  getRights:     (): Promise<FlowRights> => apiCall<FlowRights>('GET', '/flows/rights'),
}
