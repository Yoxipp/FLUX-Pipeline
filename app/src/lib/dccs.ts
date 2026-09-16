// dccs.ts - launcher DCC list shared by Sidebar, StatusBar and Settings.

// Frontend key -> backend DCC_PORTS key (backend uses capitalized/abbreviated names).
export const DCC_STATUS_KEYS: Record<string, string> = {
  maya:               'Maya',
  houdini:            'Houdini',
  nuke:               'Nuke',
  substance_painter:  'SubstanceP',
  substance_designer: 'SubstanceD',
  zbrush:             'ZBrush',
  marvelous:          'Marvelous',
  photoshop:          'Photoshop',
  mari:               'Mari',
}

export const SOFTWARE = [
  { name: 'Maya',      key: 'maya' },
  { name: 'Houdini',   key: 'houdini' },
  { name: 'Nuke',      key: 'nuke' },
  { name: 'Marvelous', key: 'marvelous' },
  { name: 'Painter',   key: 'substance_painter' },
  { name: 'Designer',  key: 'substance_designer' },
  { name: 'Mari',      key: 'mari' },
  { name: 'ZBrush',    key: 'zbrush' },
  { name: 'Photoshop', key: 'photoshop' },
]

// Backend status key -> frontend key (StatusBar filtering).
export const DCC_FRONTEND_KEYS: Record<string, string> = Object.fromEntries(
  Object.entries(DCC_STATUS_KEYS).map(([front, back]) => [back, front]),
)
