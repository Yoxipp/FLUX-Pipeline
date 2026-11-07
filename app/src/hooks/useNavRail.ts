// Thin navigation bar switch (2026-11-06), per machine, on by default (2026-11-07).
// One of the two bars is removed once they have been compared, so this stays a plain local
// preference.
import { useCallback, useEffect, useState } from 'react'

const KEY = 'flux.ui.navRail'
const EVENT = 'flux:nav-rail-changed'

// A machine that never touched the switch has no stored value and gets the thin bar.
export function navRailFromStored(stored: string | null): boolean {
  return stored !== '0'
}

function read(): boolean {
  try { return navRailFromStored(localStorage.getItem(KEY)) } catch { return navRailFromStored(null) }
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
