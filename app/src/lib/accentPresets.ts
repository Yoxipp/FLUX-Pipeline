// Accent color presets — shared between TitleBar (picker) and App (restore on load).

export interface AccentPreset {
  key:    string
  label:  string
  accent: string   // oklch value used for --accent
  hi:     string   // oklch value used for --accent-hi
}

export const ACCENT_PRESETS: AccentPreset[] = [
  { key: 'orange', label: 'Orange', accent: 'oklch(66% 0.10  52)',  hi: 'oklch(75% 0.115 52)'  },
  { key: 'blue',   label: 'Bleu',   accent: 'oklch(62% 0.11 250)',  hi: 'oklch(72% 0.125 250)' },
  { key: 'yellow', label: 'Jaune',  accent: 'oklch(78% 0.15  95)',  hi: 'oklch(86% 0.17  95)'  },
  { key: 'pink',   label: 'Rose',   accent: 'oklch(66% 0.11 350)',  hi: 'oklch(75% 0.125 350)' },
  { key: 'green',  label: 'Vert',   accent: 'oklch(64% 0.09 145)',  hi: 'oklch(73% 0.105 145)' },
  { key: 'gray',   label: 'Gris',   accent: 'oklch(60% 0.02  60)',  hi: 'oklch(72% 0.025 60)'  },
]

// A stored accent is either a preset key or a free "#rrggbb" color.
export const isCustomAccent = (value: string): boolean => /^#[0-9a-f]{6}$/i.test(value)

export function applyAccentPreset(key: string): void {
  let accent: string
  let hi: string
  if (isCustomAccent(key)) {
    accent = key
    hi     = `color-mix(in oklch, ${key} 82%, white)`
  } else {
    const preset = ACCENT_PRESETS.find(p => p.key === key) ?? ACCENT_PRESETS[0]
    accent = preset.accent
    hi     = preset.hi
  }
  const root = document.documentElement
  root.style.setProperty('--accent',      accent)
  root.style.setProperty('--accent-hi',   hi)
  root.style.setProperty('--accent-soft', `color-mix(in oklch, ${accent} 13%, transparent)`)
  root.style.setProperty('--hl',          `color-mix(in oklch, ${accent} 22%, transparent)`)
  // Tell the other FLUX windows (Tractor window...): they get a 'storage' event, this one does not.
  try { localStorage.setItem(ACCENT_STORAGE_KEY, key) } catch { /* private storage off */ }
}

const ACCENT_STORAGE_KEY = 'flux.accent'

/** Follow an accent change made in another FLUX window. Returns the cleanup. */
export function followAccentFromOtherWindows(): () => void {
  const onStorage = (e: StorageEvent) => {
    if (e.key === ACCENT_STORAGE_KEY && e.newValue) applyAccentPreset(e.newValue)
  }
  window.addEventListener('storage', onStorage)
  return () => window.removeEventListener('storage', onStorage)
}
