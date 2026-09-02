// Logo.tsx — the official FLUX logo. Single source of truth for the mark so it
// can be swapped in one place.
//
// The mark is rendered through a CSS mask (not an <img>) so it can be tinted
// dynamically to any colour while keeping the original shape, transparency and
// vector crispness. By default it follows the Hub accent colour (`--accent`),
// so changing the accent in the settings recolours the logo automatically.
// Pass an explicit `color` (e.g. "orange" / "blue") to force a fixed tint.

import fluxLogo from '../../assets/flux_logo.svg'

export function FluxLogo({
  size = 24,
  color = 'var(--accent)',
  style,
}: {
  size?: number
  color?: string
  style?: React.CSSProperties
}) {
  return (
    <span
      role="img"
      aria-label="FLUX"
      style={{
        display: 'block',
        width: size,
        height: size,
        backgroundColor: color,
        WebkitMaskImage: `url(${fluxLogo})`,
        maskImage: `url(${fluxLogo})`,
        WebkitMaskRepeat: 'no-repeat',
        maskRepeat: 'no-repeat',
        WebkitMaskPosition: 'center',
        maskPosition: 'center',
        WebkitMaskSize: 'contain',
        maskSize: 'contain',
        ...style,
      }}
    />
  )
}
