// Accent color presets — shared between TitleBar (picker) and App (restore on load).

export interface AccentPreset {
  key:    string
  label:  string
  accent: string   // oklch value used for --accent
  hi:     string   // oklch value used for --accent-hi
}

export const ACCENT_PRESETS: AccentPreset[] = [
  { key: 'orange', label: 'Orange', accent: 'oklch(66% 0.10  52)',  hi: 'oklch(75% 0.115 52)'  },
  { key: 'blue',   label: 'Bleu',   accent: 'oklch(60% 0.18 250)',  hi: 'oklch(70% 0.20 250)'  },
  { key: 'yellow', label: 'Jaune',  accent: 'oklch(78% 0.15  95)',  hi: 'oklch(86% 0.17  95)'  },
  { key: 'pink',   label: 'Rose',   accent: 'oklch(65% 0.20 350)',  hi: 'oklch(74% 0.22 350)'  },
  { key: 'green',  label: 'Vert',   accent: 'oklch(62% 0.15 145)',  hi: 'oklch(72% 0.17 145)'  },
  { key: 'gray',   label: 'Gris',   accent: 'oklch(60% 0.02  60)',  hi: 'oklch(72% 0.025 60)'  },
]

export function applyAccentPreset(key: string): void {
  const preset = ACCENT_PRESETS.find(p => p.key === key) ?? ACCENT_PRESETS[0]
  const root = document.documentElement
  root.style.setProperty('--accent',      preset.accent)
  root.style.setProperty('--accent-hi',   preset.hi)
  root.style.setProperty('--accent-soft', `color-mix(in oklch, ${preset.accent} 13%, transparent)`)
  root.style.setProperty('--hl',          `color-mix(in oklch, ${preset.accent} 22%, transparent)`)
}
