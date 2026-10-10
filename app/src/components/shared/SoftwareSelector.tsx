import { FileUp } from 'lucide-react'
import { DccLogo } from './DccLogo'
import { ExpandPicker, type PickOption } from './ExpandPicker'

// Supported DCCs (detection is version-agnostic: DCC_EXE_PATTERNS in backend/core/constants.py).
const SW_DCC = ['Maya', 'Houdini', 'Nuke', 'Marvelous', 'Painter', 'Designer', 'Mari', 'ZBrush', 'Photoshop']

interface Props {
  active?: string
  onChange?: (name: string) => void
  // Publisher shows "Fichier local" as a standalone source; the Shelf hides it.
  showLocal?: boolean
  // Only the software enabled in Settings > Logiciels is offered (same list as the
  // launcher). The active one always shows, even while it is being switched away.
  isVisible?: (name: string) => boolean
  // Extra software for this page only (Shelf Manager: Unreal, not a Publisher source).
  extra?: string[]
}

// One button with the current software (logo + name + arrow); a click slides the
// other software out to the right, a pick closes it (ADR 0044).
export function SoftwareSelector({ active = 'Maya', onChange, showLocal = true, isVisible, extra = [] }: Props) {
  const shown = [...SW_DCC, ...extra].filter(n => !isVisible || isVisible(n) || n === active)
  const options: PickOption[] = [
    ...shown.map(n => ({ value: n, label: n, icon: <DccLogo dcc={n} size={14} color="currentColor" /> })),
    ...(showLocal ? [{ value: 'Fichier local', label: 'Fichier local', icon: <FileUp size={14} strokeWidth={1.8} /> }] : []),
  ]
  return <ExpandPicker value={active} options={options} onChange={v => onChange?.(v)} />
}
