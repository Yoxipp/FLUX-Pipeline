// ScrollMore.tsx - a vertical scroll area that shows a down arrow at its bottom while
// there is more content below (2026-10-09, Home columns). A click on the arrow
// scrolls one page down; the arrow hides once the end is reached.

import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState,
  type CSSProperties, type ReactNode, type UIEvent } from 'react'
import { ChevronDown } from 'lucide-react'

export const ScrollMore = forwardRef<HTMLDivElement, {
  children: ReactNode
  style?: CSSProperties
  onScroll?: (e: UIEvent<HTMLDivElement>) => void
}>(function ScrollMore({ children, style, onScroll }, ref) {
  const inner = useRef<HTMLDivElement>(null)
  useImperativeHandle(ref, () => inner.current as HTMLDivElement)
  const [more, setMore] = useState(false)

  const measure = useCallback(() => {
    const el = inner.current
    if (el) setMore(el.scrollHeight - el.scrollTop - el.clientHeight > 4)
  }, [])

  // Content and size change without a scroll event (new rows, window resize).
  useEffect(() => {
    const el = inner.current
    if (!el) return
    measure()
    const resize = new ResizeObserver(measure)
    resize.observe(el)
    const mutate = new MutationObserver(measure)
    mutate.observe(el, { childList: true, subtree: true })
    return () => { resize.disconnect(); mutate.disconnect() }
  }, [measure])

  return (
    <div style={{ flex: 1, minHeight: 0, position: 'relative', display: 'flex', flexDirection: 'column' }}>
      <div ref={inner} style={{ flex: 1, overflowY: 'auto', minHeight: 0, ...style }}
        onScroll={e => { measure(); onScroll?.(e) }}>
        {children}
      </div>
      {more && (
        <button type="button" aria-label="Descendre" title="Il y a la suite plus bas"
          onClick={() => inner.current?.scrollBy({ top: inner.current.clientHeight * 0.8, behavior: 'smooth' })}
          style={{ position: 'absolute', bottom: 8, left: '50%', transform: 'translateX(-50%)', width: 28, height: 22,
            display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: 11, cursor: 'pointer',
            background: 'var(--paper-3, var(--paper-2))', border: '1px solid var(--rule)', color: 'var(--ink-2)',
            boxShadow: '0 1px 3px rgba(0,0,0,0.25)' }}>
          <ChevronDown size={14} />
        </button>
      )}
    </div>
  )
})
