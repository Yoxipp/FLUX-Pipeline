// Folder Manager icons: folder / file tiles with version and format badges.

// ── Icônes SVG ────────────────────────────────────────────────────────────────

// Version badge colours: LAST is the active publish (green), a locked version is
// a frozen snapshot (orange). Drawn on the file/folder icon itself.
const VER_LAST_BG = '#1F9E6A'
const VER_NUM_BG  = '#E8912A'

// Parse the trailing "_<FORMAT>_<VERSION>" of a published name (file or folder),
// e.g. CHAR_RIG_PATRICK_ALL_A_USD_LAST → { format: 'USD', version: 'LAST' } or
// ..._USD_V003 → { format: 'USD', version: 'V003' }. Returns {} when the name is
// not a versioned publish (plain assets/tasks/instances), so no badge is drawn.
export function parseVersionMeta(name: string): { version?: string; format?: string } {
  // The version token is the last "_" segment up to its first dot, so multi-dot
  // names keep their badge: X_LAST.bgeo.sc, X_LAST.bgeo.sc.link (ADR 0017).
  const us = name.lastIndexOf('_')
  if (us <= 0) return {}
  const parts = name.slice(0, us).split('_')
  const last = name.slice(us + 1).split('.')[0]
  parts.push(last)
  const m = /^(LAST|v\d+|V\d+)$/.exec(last)
  if (!m) return {}
  const version = last.toUpperCase()
  const fmtTok = parts[parts.length - 2]
  const format = /^[A-Za-z]{2,5}$/.test(fmtTok) ? fmtTok.toUpperCase() : undefined
  return { version, format }
}

// Small version/format chips drawn inside an icon's SVG viewBox. `w` is the
// viewBox width so the chips can be centred for both the file (30) and folder (40).
function IconBadges({ version, format, w, versionY, formatY }: {
  version?: string; format?: string; w: number; versionY: number; formatY?: number
}) {
  const bw = Math.min(28, w - 4)
  const x = (w - bw) / 2
  const cx = w / 2
  return (
    <>
      {version && (
        <>
          <rect x={x} y={versionY} width={bw} height="10" rx="2" fill={version === 'LAST' ? VER_LAST_BG : VER_NUM_BG} />
          <text x={cx} y={versionY + 7.5} textAnchor="middle" fontSize="6.5" fontWeight="700" fontFamily="monospace" fill="#fff" letterSpacing="0.2">{version}</text>
        </>
      )}
      {format && formatY !== undefined && (
        <>
          <rect x={x} y={formatY} width={bw} height="10" rx="2" fill="rgba(18,18,18,0.55)" />
          <text x={cx} y={formatY + 7.5} textAnchor="middle" fontSize="6.5" fontWeight="700" fontFamily="monospace" fill="#fff" letterSpacing="0.2">{format}</text>
        </>
      )}
    </>
  )
}

export function FolderSvg({ size = 40, selected = false, version, format }: {
  size?: number; selected?: boolean; version?: string; format?: string
}) {
  const body = selected ? 'var(--accent)'    : '#F5A623'
  const tab  = selected ? 'var(--accent-hi)' : '#FFCA5C'
  return (
    <svg width={size} height={Math.round(size * 0.82)} viewBox="0 0 40 33" fill="none">
      <path d="M2 7 L2 4 Q2 2 4 2 L15 2 L18.5 7 Z" fill={tab} />
      <path d="M0 9 Q0 7 2 7 L38 7 Q40 7 40 9 L40 31 Q40 33 38 33 L2 33 Q0 33 0 31 Z" fill={body} />
      <IconBadges version={version} format={format} w={40} versionY={10} formatY={21} />
    </svg>
  )
}

const EXT_BADGE: Record<string, { bg: string; fg: string }> = {
  usd:  { bg: '#E07820', fg: '#fff' },
  usda: { bg: '#E07820', fg: '#fff' },
  usdc: { bg: '#E07820', fg: '#fff' },
  usdz: { bg: '#E07820', fg: '#fff' },
  abc:  { bg: '#1A9E6E', fg: '#fff' },
  gbx:  { bg: '#5A8A2E', fg: '#fff' },
  obj:  { bg: '#7B6FAA', fg: '#fff' },
  ma:   { bg: '#1E88C8', fg: '#fff' },
  mb:   { bg: '#1565A8', fg: '#fff' },
  ztl:  { bg: '#D03030', fg: '#fff' },
  hip:   { bg: '#C8541E', fg: '#fff' },
  hiplc: { bg: '#C8541E', fg: '#fff' },
  hipnc: { bg: '#C8541E', fg: '#fff' },
  bgeo:  { bg: '#B8661E', fg: '#fff' },
  'bgeo.sc': { bg: '#B8661E', fg: '#fff' },
  vdb:   { bg: '#4A6FA5', fg: '#fff' },
  exr:   { bg: '#6A4FA0', fg: '#fff' },
  nk:    { bg: '#D0A020', fg: '#1a1a1a' },
  psd:   { bg: '#2A6FC0', fg: '#fff' },
  fbx:   { bg: '#5E6B78', fg: '#fff' },
}
// Any other format still gets a neutral chip.
const EXT_BADGE_DEFAULT = { bg: '#4A4A4A', fg: '#fff' }
// Chip text for extensions too long for the 26px chip.
const EXT_LABEL: Record<string, string> = { 'bgeo.sc': 'BGEO', 'bgeo.gz': 'BGEO', hiplc: 'HIPLC', hipnc: 'HIPNC' }

// Format of a publish entry: a LAST .link / .flux.json reports its target's format and
// compound extensions stay whole (X_LAST.bgeo.sc.link -> 'bgeo.sc', ADR 0017).
export function getExt(filename: string): string {
  let name = filename.toLowerCase()
  if (name.endsWith('.flux.json')) name = name.slice(0, -'.flux.json'.length)
  else if (name.endsWith('.link')) name = name.slice(0, -'.link'.length)
  for (const comp of ['.bgeo.sc', '.bgeo.gz', '.geo.sc', '.geo.gz']) {
    if (name.endsWith(comp)) return comp.slice(1)
  }
  const dot = name.lastIndexOf('.')
  return dot >= 0 ? name.slice(dot + 1) : ''
}

export function FileSvg({ size = 36, selected = false, ext = '', version }: {
  size?: number; selected?: boolean; ext?: string; version?: string
}) {
  const body   = selected ? 'var(--accent)'    : 'var(--ink-2)'
  const corner = selected ? 'var(--accent-hi)' : 'var(--ink-3)'
  const badge  = ext ? (EXT_BADGE[ext] ?? EXT_BADGE_DEFAULT) : undefined
  return (
    <svg width={size} height={Math.round(size * 1.22)} viewBox="0 0 30 37" fill="none">
      <path d="M2 0 L20 0 L30 10 L30 35 Q30 37 28 37 L2 37 Q0 37 0 35 L0 2 Q0 0 2 0Z" fill={body} />
      <path d="M20 0 L20 10 L30 10Z" fill={corner} />
      {/* version chip sits above the format badge */}
      <IconBadges version={version} w={30} versionY={13} />
      {badge && (
        <>
          <rect x="2" y="25" width="26" height="10" rx="2" fill={badge.bg} />
          <text x="15" y="33" textAnchor="middle" fontSize="6.5" fontWeight="700"
            fontFamily="monospace" fill={badge.fg} letterSpacing="0.3">
            {(EXT_LABEL[ext] ?? ext.toUpperCase()).slice(0, 5)}
          </text>
        </>
      )}
    </svg>
  )
}
