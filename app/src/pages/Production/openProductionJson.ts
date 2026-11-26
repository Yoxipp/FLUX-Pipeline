import { toast } from 'sonner'
import { api } from '../../api/client'
import { productionSync } from '../../hooks/useProduction'

// Shared by the entity and task context menus. There is no per-entity JSON: this
// opens the project's production.json, after pending edits are written to it.
export async function openProductionJson(project: string) {
  try {
    await productionSync.flush()
    await api.openProductionJson(project)
  } catch (e) { toast.error(e instanceof Error ? e.message : 'Action impossible') }
}
