import { useCallback, useState } from 'react'
import type { ShowFilter } from './ProductionTableMenus'
import { productionShowKey, readProductionShow, writeProductionShow } from './showPreference'

export function useProductionShow(project: string, mode: 'asset' | 'shot', entityId?: string): [ShowFilter, (filter: ShowFilter) => void] {
  const key = productionShowKey(project, mode, entityId)
  const [saved, setSaved] = useState(() => ({ key, filter: readProductionShow(key) }))
  const filter = saved.key === key ? saved.filter : readProductionShow(key)
  const setFilter = useCallback((next: ShowFilter) => {
    writeProductionShow(key, next)
    setSaved({ key, filter: next })
  }, [key])
  return [filter, setFilter]
}
