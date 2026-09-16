// useEnabledDccs.ts - per-user enabled DCC list (V8 U10).
//
// Stored in USER/<user>/UserSettings/User.json (enabled_dccs) via /settings/enabled-dccs.
// null = the user never chose = every DCC enabled. Changes are broadcast with the
// 'flux:enabled-dccs' event so Sidebar, StatusBar and Settings stay in sync.

import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'

const EVENT = 'flux:enabled-dccs'

export function useEnabledDccs() {
  const [enabled, setEnabledState] = useState<string[] | null>(null)

  useEffect(() => {
    let alive = true
    const load = () => {
      api.getEnabledDccs()
        .then(r => { if (alive) setEnabledState(r.enabled) })
        .catch(() => { /* keep current: all enabled by default */ })
    }
    load()
    const onChange = (e: Event) => setEnabledState((e as CustomEvent<string[] | null>).detail)
    window.addEventListener(EVENT, onChange)
    window.addEventListener('flux:refresh', load)
    return () => {
      alive = false
      window.removeEventListener(EVENT, onChange)
      window.removeEventListener('flux:refresh', load)
    }
  }, [])

  const isEnabled = useCallback((key: string) => enabled === null || enabled.includes(key), [enabled])

  const setEnabled = useCallback(async (next: string[] | null) => {
    const r = await api.setEnabledDccs(next)
    window.dispatchEvent(new CustomEvent(EVENT, { detail: r.enabled }))
  }, [])

  return { enabled, isEnabled, setEnabled }
}
