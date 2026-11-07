// NavRail: the thin navigation bar, icons only (mockup A, 2026-11-06). Sidebar owns the
// routes and the DCC state and hands them over, so removing one of the two bars stays easy.
import { useEffect, useRef, useState } from 'react'
import { Play } from 'lucide-react'

export interface RailItem {
  id: string
  icon: React.ElementType
  label: string
  group?: string           // shown before the label in the tooltip
  active: boolean
  route?: string           // detachable page, same gestures as the wide bar
  notif?: number
  child?: boolean          // sub-entry of the item above (Assets / Shots)
  onClick: () => void
}

interface Props {
  sections: RailItem[][]
  launcher: React.ReactNode
  launcherState: 'ok' | 'warn' | 'err' | ''
}

// Drag a page out of the window (or right-click it) to open it in its own window (U4).
// The drop point is checked against the window rectangle: a drop inside does nothing.
export function detachIfOutside(e: React.DragEvent, route: string) {
  const { screenX: x, screenY: y } = e
  if (x === 0 && y === 0) return      // cancelled drag (Escape)
  const inside = x >= window.screenX && x <= window.screenX + window.outerWidth
    && y >= window.screenY && y <= window.screenY + window.outerHeight
  if (!inside) window.electronAPI?.detachPage?.(route)
}

export function NavRail({ sections, launcher, launcherState }: Props) {
  const [tip, setTip] = useState<{ group?: string; label: string; top: number } | null>(null)
  const [open, setOpen] = useState(false)
  const flyout = useRef<HTMLDivElement>(null)
  const launcherBtn = useRef<HTMLButtonElement>(null)

  // Close on an outside click or Escape. Launcher menus live in a portal: they count as inside.
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      const target = e.target as Element | null
      if (!target || flyout.current?.contains(target) || launcherBtn.current?.contains(target)) return
      if (target.closest('.launcher-menu')) return
      setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      // A menu open inside the flyout takes Escape first.
      if (e.key === 'Escape' && !document.querySelector('.launcher-menu')) { setOpen(false); launcherBtn.current?.focus() }
    }
    document.addEventListener('mousedown', onDown)
    // Capture, registered before any menu opens: runs while that menu is still in the DOM.
    document.addEventListener('keydown', onKey, true)
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey, true) }
  }, [open])

  const showTip = (el: HTMLElement, item: RailItem) => {
    const r = el.getBoundingClientRect()
    setTip({ group: item.group, label: item.label, top: r.top + r.height / 2 })
  }

  return (
    <nav className="nav-rail" aria-label="Navigation principale">
      <div className="nav-rail-items">
        {sections.map((items, i) => (
          <div key={items[0]?.id ?? i} className="nav-rail-section">
            {items.map(item => {
              const Icon = item.icon
              const detachable = !!item.route && !!window.electronAPI?.detachPage
              return (
                <button key={item.id} type="button"
                  className={`nav-rail-btn${item.active ? ' active' : ''}${item.child ? ' child' : ''}`}
                  aria-label={item.group ? `${item.group}, ${item.label}` : item.label}
                  aria-current={item.active ? 'page' : undefined}
                  onClick={item.onClick}
                  onMouseEnter={e => showTip(e.currentTarget, item)} onMouseLeave={() => setTip(null)}
                  onFocus={e => showTip(e.currentTarget, item)} onBlur={() => setTip(null)}
                  draggable={detachable}
                  onDragStart={detachable ? (e => { setTip(null); e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', item.route!) }) : undefined}
                  onDragEnd={detachable ? (e => detachIfOutside(e, item.route!)) : undefined}
                  onContextMenu={detachable ? (e => { e.preventDefault(); window.electronAPI?.detachPage?.(item.route!) }) : undefined}>
                  <Icon size={item.child ? 14 : 18} strokeWidth={1.75} />
                  {!!item.notif && <span className="nav-rail-badge">{item.notif}</span>}
                </button>
              )
            })}
          </div>
        ))}
      </div>

      <div className="nav-rail-foot">
        <button ref={launcherBtn} type="button" className={`nav-rail-btn${open ? ' active' : ''}`}
          aria-label="Launcher" aria-expanded={open} title="Launcher" onClick={() => setOpen(v => !v)}>
          <Play size={18} strokeWidth={1.75} fill="currentColor" />
          {launcherState && <span className={`nav-rail-dot ${launcherState}`} />}
        </button>
      </div>

      {tip && !open && (
        <div role="tooltip" className="nav-rail-tip" style={{ top: tip.top }}>
          {tip.group && <span>{tip.group}</span>} {tip.label}
        </div>
      )}
      {open && (
        <div ref={flyout} role="dialog" aria-label="Launcher" className="nav-rail-flyout">
          <div className="cap" style={{ padding: '2px 14px 6px' }}>LAUNCHER</div>
          {launcher}
        </div>
      )}
    </nav>
  )
}
