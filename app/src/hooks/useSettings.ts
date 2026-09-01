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

  // Refresh without restart: re-fetch settings when the shell broadcasts flux:refresh.
  useEffect(() => {
    const onRefresh = () => {
      api.getSettings().then(setSettings).catch(() => { /* keep current */ })
    }
    window.addEventListener('flux:refresh', onRefresh)
    return () => window.removeEventListener('flux:refresh', onRefresh)
  }, [])

  return { settings, loading, error, setSettings }
}
