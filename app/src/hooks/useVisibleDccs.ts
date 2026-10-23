// useVisibleDccs.ts - software shown to the artist: Settings > Logiciels (useEnabledDccs)
// narrowed by the work profile "softwares" pref (ADR 0042). Settings keeps using
// useEnabledDccs directly, so its checkboxes are never filtered by the profile.

import { useCallback } from 'react'
import { useEnabledDccs } from './useEnabledDccs'
import { useWorkProfile } from '../WorkProfileContext'
import { SOFTWARE } from '../lib/dccs'
import { isSoftwareVisible } from '../lib/workProfiles'

const ALL_KEYS = SOFTWARE.map(s => s.key)

export function useVisibleDccs() {
  const { isEnabled } = useEnabledDccs()
  const { prefs } = useWorkProfile()
  const isVisible = useCallback((key: string) => isSoftwareVisible(key, prefs.softwares, ALL_KEYS, isEnabled), [prefs.softwares, isEnabled])
  return { isVisible, isEnabled }
}
