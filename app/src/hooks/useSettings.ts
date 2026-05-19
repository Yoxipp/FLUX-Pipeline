// useSettings.ts — load + cache user settings from FastAPI.

import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Settings } from '../types'

export function useSettings() {
  const [settings, setSettings] = useState<Settings | null>(null)
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState<string | null>(null)

  useEffect(() => {
    api.getSettings()
      .then(setSettings)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  return { settings, loading, error, setSettings }
}
