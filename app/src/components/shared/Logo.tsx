// Logo.tsx — the official FLUX logo. Single source of truth for the mark so it
// can be swapped in one place. The image is used as-is (never recolored/retouched).

import fluxLogo from '../../assets/flux_logo.png'

export function FluxLogo({ size = 24, style }: { size?: number; style?: React.CSSProperties }) {
  return (
    <img
      src={fluxLogo}
      alt="FLUX"
      width={size}
      height={size}
      style={{ width: size, height: size, objectFit: 'contain', display: 'block', ...style }}
    />
  )
}
