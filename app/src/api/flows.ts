// flows.ts — API calls of the Flows editor (03_EDITEUR §9).
// P0: read-only, on top of the v1 action routes (no new backend route). The /flows
// routes (list, get, save, validate, run) arrive with the v2 format (P1+).

import { api } from './client'
import type { ActionCatalog, ActionGraph } from '../types'

export const flowsApi = {
  listV1Actions: (): Promise<string[]> => api.getActionGraphList(),
  getV1Action:   (name: string): Promise<ActionGraph> => api.getActionGraph(name),
  getV1Catalog:  (): Promise<ActionCatalog> => api.getActionCatalog(),
}
