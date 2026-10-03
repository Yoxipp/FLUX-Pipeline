export interface HoverRect { left: number; top: number; right: number; bottom: number; width: number; height: number }

/** All inputs are viewport pixels, never layout coordinates from a zoomed ancestor. */
export function tooltipPosition(anchor: HoverRect, width: number, height: number, viewportWidth: number, viewportHeight: number, gap: number, side: 'top' | 'bottom' | 'left' | 'right' = 'top', align: 'start' | 'center' | 'end' = 'center', padding = 10) {
  const spaces = { top: anchor.top, bottom: viewportHeight - anchor.bottom, left: anchor.left, right: viewportWidth - anchor.right }
  const opposite = { top: 'bottom', bottom: 'top', left: 'right', right: 'left' } as const
  const required = (side === 'top' || side === 'bottom' ? height : width) + gap + padding
  if (spaces[side] < required && spaces[opposite[side]] > spaces[side]) side = opposite[side]
  const vertical = side === 'top' || side === 'bottom'
  const crossStart = vertical ? anchor.left : anchor.top
  const crossSize = vertical ? anchor.width : anchor.height
  const tooltipCrossSize = vertical ? width : height
  const cross = crossStart + (align === 'start' ? 0 : align === 'end' ? crossSize - tooltipCrossSize : (crossSize - tooltipCrossSize) / 2)
  const x = vertical ? cross : side === 'left' ? anchor.left - gap - width : anchor.right + gap
  const y = vertical ? side === 'top' ? anchor.top - gap - height : anchor.bottom + gap : cross
  const left = Math.max(padding, Math.min(x, viewportWidth - width - padding))
  const top = Math.max(padding, Math.min(y, viewportHeight - height - padding))
  return { left, top, side, arrow: vertical ? Math.max(10, Math.min(anchor.left + anchor.width / 2 - left, width - 10)) : Math.max(10, Math.min(anchor.top + anchor.height / 2 - top, height - 10)) }
}
