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
  // Software the user did not enable (Settings > Logiciels) still shows in the strip,
  // dimmed, after the enabled ones (ADR 0042). The active one is the trigger.
  isVisible?: (name: string) => boolean
}

// One button with the current software (logo + name + arrow); a click slides the
// other software out to the right, a pick closes it (ADR 0044).
export function SoftwareSelector({ active = 'Maya', onChange, showLocal = true, isVisible }: Props) {
  const enabled = SW_DCC.filter(n => !isVisible || isVisible(n))
  const disabled = SW_DCC.filter(n => isVisible && !isVisible(n))
  const options: PickOption[] = [
    ...enabled.map(n => ({ value: n, label: n, icon: <DccLogo dcc={n} size={14} color="currentColor" /> })),
    ...disabled.map(n => ({ value: n, label: n, muted: true, title: `${n} (non activé dans les Paramètres)`, icon: <DccLogo dcc={n} size={14} color="currentColor" /> })),
    ...(showLocal ? [{ value: 'Fichier local', label: 'Fichier local', icon: <FileUp size={14} strokeWidth={1.8} /> }] : []),
  ]
  return <ExpandPicker value={active} options={options} onChange={v => onChange?.(v)} />
}
