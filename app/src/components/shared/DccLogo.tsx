// DccLogo.tsx - software marks for the launcher, the Publisher and the status bar.
// Maya, Houdini, Nuke and Photoshop are the official marks (path data from Simple Icons,
// CC0, simpleicons.org). Painter, Designer, Mari, ZBrush and Marvelous have no free mark:
// they get a monogram tile in the same weight. Every mark is drawn in currentColor so the
// caller tints it (accent by default).

import type { CSSProperties } from 'react'

const OFFICIAL: Record<string, string> = {
  maya: 'M4.348 0 .69 2.203v16.875l3.657-2.203h17.297V1.219c0-.67-.551-1.219-1.22-1.219H4.349zm18.297 3.75v14.125H4.627l-1.943 1.17v3.736c0 .67.55 1.219 1.218 1.219H23.31V3.75h-.664zm-14.471.025h2.937l1.885 7.508 1.977-7.48-.012-.028h2.857v9.354h-2.216v-6.04l-1.565 6.026v.014h-2.203l-1.656-6.28v6.28H8.174V3.775zm1.33 14.762h1.18l1.068 3.543h-.902l-.217-.773H9.568l-.197.773h-.88l1.013-3.543zm1.918 0h.932l.648 1.494.643-1.494h.894l-1.113 2.133v1.41h-.887v-1.406l-1.117-2.137zm3.826 0h1.18l1.068 3.543h-.9l-.217-.773h-1.065l-.197.773h-.88l1.011-3.543zm-5.156.582-.362 1.53h.73l-.368-1.53zm5.744 0-.36 1.53h.73l-.37-1.53z',
  houdini: 'M0 19.635V24h3.824A8.662 8.662 0 0 1 0 19.635zm16.042-4.555c0-4.037-3.253-7.92-8.111-8.089C4.483 6.873 1.801 8.136 0 10.005v4.209c1.224-3.549 4.595-5.158 7.419-5.128 3.531.041 6.251 2.703 6.275 5.72 0 2.878-1.183 4.992-4.436 5.516-1.774.296-4.548-.754-4.436-3.434.065-1.381 1.138-2.162 2.366-2.106-1.207 1.618.39 2.801 1.52 2.561a2.51 2.51 0 0 0 1.966-2.502c0-1.017-.958-2.662-3.333-2.6-2.936.068-4.785 2.183-4.85 4.797-.071 3.28 3.007 5.457 6.174 5.483 4.633.059 7.395-2.984 7.377-7.441zM0 0v6.906a12.855 12.855 0 0 1 7.931-2.609c6.801 0 11.134 4.762 11.131 10.765 0 4.17-1.946 7.308-4.995 8.938H24V0H0z',
  nuke: 'M12.293.004c6.625.162 11.865 5.664 11.703 12.29-.162 6.625-5.664 11.865-12.29 11.703C5.081 23.835-.159 18.333.003 11.707l.001-.025C.18 5.066 5.678-.158 12.293.004zm0 1.238c-5.941-.164-10.89 4.52-11.054 10.461s4.52 10.89 10.461 11.054c5.941.164 10.89-4.52 11.054-10.461l.001-.025c.15-5.932-4.53-10.866-10.462-11.029zm5.842 8.302h2.4c.976 0 .682-.873.682-.873a9.587 9.587 0 0 0-2.111-3.431l-.005.011a10.052 10.052 0 0 0-3.355-2.329.612.612 0 0 0-.894.622c-.044.802-.142 2.395-.142 2.395s.016.769-.627.769c-.813.011-1.489-.044-1.489-.044a2.314 2.314 0 0 1-1.255-.545L8.868 3.511a1.09 1.09 0 0 0-1.407-.196 9.758 9.758 0 0 0-4.713 5.384c-.256.714.333.806.731.806h6a2.086 2.086 0 0 1 1.68.627c.785.824 1.331 1.369 1.331 1.369s.48.54 1.26 1.358c.431.459.632 1.089.545 1.713 0 0-.295 5.744-.295 6-.027.398.038.993.769.775a9.756 9.756 0 0 0 5.618-4.424 1.091 1.091 0 0 0-.12-1.418l-2.471-2.607a2.303 2.303 0 0 1-.496-1.282s-.022-.682.033-1.489c.044-.643.802-.583.802-.583zm-2.362 1.374c-.475.469-1.484.229-2.22-.545-.736-.775-.924-1.801-.45-2.254.475-.453 1.502-.239 2.239.536.737.774.906 1.794.431 2.263z',
  photoshop: 'M9.85 8.42c-.37-.15-.77-.21-1.18-.2-.26 0-.49 0-.68.01-.2-.01-.34 0-.41.01v3.36c.14.01.27.02.39.02h.53c.39 0 .78-.06 1.15-.18.32-.09.6-.28.82-.53.21-.25.31-.59.31-1.03.01-.31-.07-.62-.23-.89-.17-.26-.41-.46-.7-.57zM19.75.3H4.25C1.9.3 0 2.2 0 4.55v14.899c0 2.35 1.9 4.25 4.25 4.25h15.5c2.35 0 4.25-1.9 4.25-4.25V4.55C24 2.2 22.1.3 19.75.3zm-7.391 11.65c-.399.56-.959.98-1.609 1.22-.68.25-1.43.34-2.25.34-.24 0-.4 0-.5-.01s-.24-.01-.43-.01v3.209c.01.07-.04.131-.11.141H5.52c-.08 0-.12-.041-.12-.131V6.42c0-.07.03-.11.1-.11.17 0 .33 0 .56-.01.24-.01.49-.01.76-.02s.56-.01.87-.02c.31-.01.61-.01.91-.01.82 0 1.5.1 2.06.31.5.17.96.45 1.34.82.32.32.57.71.73 1.14.149.42.229.85.229 1.3.001.86-.199 1.57-.6 2.13zm7.091 3.89c-.28.4-.671.709-1.12.891-.49.209-1.09.318-1.811.318-.459 0-.91-.039-1.359-.129-.35-.061-.7-.17-1.02-.32-.07-.039-.121-.109-.111-.189v-1.74c0-.029.011-.07.041-.09.029-.02.06-.01.09.01.39.23.8.391 1.24.49.379.1.779.15 1.18.15.38 0 .65-.051.83-.141.16-.07.27-.24.27-.42 0-.141-.08-.27-.24-.4-.16-.129-.489-.279-.979-.471-.51-.18-.979-.42-1.42-.719-.31-.221-.569-.51-.761-.85-.159-.32-.239-.67-.229-1.021 0-.43.12-.84.341-1.21.25-.4.619-.72 1.049-.92.469-.239 1.059-.349 1.769-.349.41 0 .83.03 1.24.09.3.04.59.12.86.23.039.01.08.05.1.09.01.04.02.08.02.12v1.63c0 .04-.02.08-.05.1-.09.02-.14.02-.18 0-.3-.16-.62-.27-.96-.34-.37-.08-.74-.13-1.12-.13-.2-.01-.41.02-.601.07-.129.03-.24.1-.31.2-.05.08-.08.18-.08.27s.04.18.101.26c.09.11.209.2.34.27.229.12.47.23.709.33.541.18 1.061.43 1.541.73.33.209.6.49.789.83.16.318.24.67.23 1.029.011.471-.129.94-.389 1.331z',
}

// Monogram tiles: Adobe Substance style (rounded square, two letters) for Painter and
// Designer, a ring for Mari (Foundry, like Nuke) and Unreal, a plain tile for the others.
const MONOGRAM: Record<string, { text: string; shape: 'square' | 'ring' }> = {
  substance_painter:  { text: 'Pt', shape: 'square' },
  substance_designer: { text: 'Ds', shape: 'square' },
  mari:               { text: 'Ma', shape: 'ring' },
  zbrush:             { text: 'Z',  shape: 'square' },
  marvelous:          { text: 'MD', shape: 'square' },
  unreal:             { text: 'UE', shape: 'ring' },
  tractor:            { text: 'Tr', shape: 'square' },   // farm window, not a DCC
}

// Display names used by the Publisher / Shelf (SoftwareSelector) -> launcher keys.
const NAME_TO_KEY: Record<string, string> = {
  maya: 'maya', houdini: 'houdini', nuke: 'nuke', photoshop: 'photoshop',
  painter: 'substance_painter', designer: 'substance_designer',
  'substance painter': 'substance_painter', 'substance designer': 'substance_designer',
  mari: 'mari', zbrush: 'zbrush', marvelous: 'marvelous', 'marvelous designer': 'marvelous',
  unreal: 'unreal', 'unreal engine': 'unreal',
}

export function dccLogoKey(nameOrKey: string): string {
  const k = nameOrKey.trim().toLowerCase()
  return NAME_TO_KEY[k] ?? k
}

export function hasDccLogo(nameOrKey: string): boolean {
  const k = dccLogoKey(nameOrKey)
  return k in OFFICIAL || k in MONOGRAM
}

export function DccLogo({ dcc, size = 16, color = 'var(--accent-hi)', style, title }: {
  dcc: string; size?: number; color?: string; style?: CSSProperties; title?: string
}) {
  const key = dccLogoKey(dcc)
  const common = { width: size, height: size, viewBox: '0 0 24 24', style: { color, flexShrink: 0, display: 'block', ...style } }
  const path = OFFICIAL[key]
  if (path) {
    return (
      <svg {...common} role="img" aria-label={title ?? dcc}>
        {title && <title>{title}</title>}
        <path d={path} fill="currentColor" />
      </svg>
    )
  }
  const mono = MONOGRAM[key]
  const text = mono?.text ?? (dcc.slice(0, 2) || '?')
  const fontSize = text.length > 1 ? 10.5 : 14
  return (
    <svg {...common} role="img" aria-label={title ?? dcc}>
      {title && <title>{title}</title>}
      {mono?.shape === 'ring'
        ? <circle cx="12" cy="12" r="10.6" fill="none" stroke="currentColor" strokeWidth="2" />
        : <rect x="1.2" y="1.2" width="21.6" height="21.6" rx="4.6" fill="none" stroke="currentColor" strokeWidth="2" />}
      <text x="12" y="12.6" textAnchor="middle" dominantBaseline="middle" fill="currentColor"
        style={{ font: `700 ${fontSize}px var(--sans)`, letterSpacing: '-0.02em' }}>{text}</text>
    </svg>
  )
}
