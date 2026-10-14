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

/** Scales a rect measured in a zoomed subtree back to viewport pixels. */
export function scaleRect(rect: HoverRect, factor: number): HoverRect {
  return { left: rect.left * factor, top: rect.top * factor, right: rect.right * factor, bottom: rect.bottom * factor, width: rect.width * factor, height: rect.height * factor }
}

/** Product of the CSS `zoom` of the element and its ancestors below body (body/html also scale portals). */
export function effectiveZoom(element: Element | null) {
  let zoom = 1
  for (let node = element; node && node !== document.body; node = node.parentElement) {
    const value = getComputedStyle(node).zoom
    const parsed = parseFloat(value)
    if (Number.isFinite(parsed) && parsed > 0) zoom *= parsed / (value.endsWith('%') ? 100 : 1)
  }
  return zoom
}

let legacyZoomRects: boolean | null = null
/** Chromium < 128 (Electron 31) reports rects under a CSS `zoom` ancestor unzoomed. */
function rectsIgnoreZoom() {
  if (legacyZoomRects != null) return legacyZoomRects
  const probe = document.createElement('div'), inner = document.createElement('div')
  probe.style.cssText = 'position:fixed;left:0;top:0;zoom:2;visibility:hidden;pointer-events:none'
  inner.style.cssText = 'margin-left:10px;width:10px;height:1px'
  probe.appendChild(inner); document.body.appendChild(probe)
  legacyZoomRects = inner.getBoundingClientRect().left < 15
  probe.remove()
  return legacyZoomRects
}

/** Viewport pixels of an element, valid for `position: fixed` content portaled to body. */
export function viewportRect(element: Element): HoverRect {
  const rect = element.getBoundingClientRect()
  return rectsIgnoreZoom() ? scaleRect(rect, effectiveZoom(element)) : rect
}
