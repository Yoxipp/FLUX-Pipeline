// Thin navigation bar switch (2026-11-06), per machine. One of the two bars is removed
// once they have been compared, so this stays a plain local preference.
import { useCallback, useEffect, useState } from 'react'

const KEY = 'flux.ui.navRail'
const EVENT = 'flux:nav-rail-changed'

function read(): boolean {
  try { return localStorage.getItem(KEY) === '1' } catch { return false }
}

export function useNavRail(): [boolean, (on: boolean) => void] {
  const [enabled, setEnabled] = useState(read)
  useEffect(() => {
    const sync = () => setEnabled(read())
    window.addEventListener(EVENT, sync)
    return () => window.removeEventListener(EVENT, sync)
  }, [])
  const set = useCallback((on: boolean) => {
    try { localStorage.setItem(KEY, on ? '1' : '0') } catch { /* blocked storage */ }
    setEnabled(on)
    window.dispatchEvent(new Event(EVENT))
  }, [])
  return [enabled, set]
}
