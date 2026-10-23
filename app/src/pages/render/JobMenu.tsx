// JobMenu.tsx: the Tractor Dashboard job menu in FLUX (2026-10-23). Short words + icons.
// Trace and Pin work on any job (read only / local to FLUX); the rest only on the user's FLUX jobs
// (the backend checks the user too).

import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'
import {
  ArchiveX, ArrowUpDown, ArrowUpToLine, Lock, Pause, Pin, PinOff, Play, RefreshCcw, RotateCcw, ScanSearch, SkipForward, Unlock,
} from 'lucide-react'
import type { RenderJob, RenderJobAction } from '../../api/client'
import { useTr } from './renderUi'

export type JobMenuChoice = RenderJobAction | 'trace' | 'pin' | 'unpin' | 'priority'

type Item = { id: JobMenuChoice; label: string; icon: ReactNode; danger?: boolean }

export function JobMenu({ job, pinned, x, y, onPick, onClose }: {
  job: RenderJob; pinned: boolean; x: number; y: number
  onPick: (choice: JobMenuChoice) => void; onClose: () => void
}) {
  const { tr } = useTr()
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const close = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) onClose() }
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', esc)
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', esc) }
  }, [onClose])

  const state = job.state ?? 'waiting'
  const mine = !!job.flux_user
  const live = state !== 'deleted'
  const items: Item[] = []
  if (mine && live) {
    items.push(state === 'paused'
      ? { id: 'resume', label: tr('Reprendre', 'Resume'), icon: <Play size={12} /> }
      : { id: 'pause', label: tr('Pause des nouvelles taches', 'Pause new tasks'), icon: <Pause size={12} /> })
    if (job.numError > 0) {
      items.push({ id: 'retry', label: tr('Relancer les erreurs', 'Retry errors'), icon: <RotateCcw size={12} /> })
      items.push({ id: 'skip_errors', label: tr('Ignorer les erreurs', 'Skip errors'), icon: <SkipForward size={12} /> })
    }
    items.push({ id: 'restart', label: tr('Redemarrer le job', 'Restart job'), icon: <RefreshCcw size={12} />, danger: true })
    // The engine only shuffles a job still in its queue ("unknown status" on a finished one, job 34031).
    if (state === 'waiting' || state === 'active' || state === 'paused') {
      items.push({ id: 'shuffle_top', label: tr('Passer en tete de file', 'Shuffle to top'), icon: <ArrowUpToLine size={12} /> })
      items.push({ id: 'priority', label: tr(`Priorite (${job.priority ?? '?'})...`, `Priority (${job.priority ?? '?'})...`), icon: <ArrowUpDown size={12} /> })
    }
    items.push({ id: 'lock', label: tr('Verrouiller', 'Lock'), icon: <Lock size={12} /> })
    items.push({ id: 'unlock', label: tr('Deverrouiller', 'Unlock'), icon: <Unlock size={12} /> })
    items.push({ id: 'archive', label: tr('Archiver', 'Archive'), icon: <ArchiveX size={12} />, danger: true })
  }
  items.push({ id: 'trace', label: tr('Trace (pourquoi il attend)', 'Trace (why it waits)'), icon: <ScanSearch size={12} /> })
  items.push(pinned
    ? { id: 'unpin', label: tr('Desepingler', 'Unpin'), icon: <PinOff size={12} /> }
    : { id: 'pin', label: tr('Epingler en haut', 'Pin to top'), icon: <Pin size={12} /> })

  return (
    <div ref={ref} onClick={e => e.stopPropagation()}
      style={{ position: 'fixed', left: Math.min(x, window.innerWidth - 230), top: Math.min(y, window.innerHeight - items.length * 28 - 16),
        zIndex: 50, width: 220, padding: 4, background: 'var(--paper)', border: '1px solid var(--rule-2)', borderRadius: 6,
        boxShadow: '0 2px 10px rgba(0,0,0,.18)' }}>
      {!mine && <div style={{ padding: '4px 8px', fontSize: 10.5, color: 'var(--ink-3)' }}>{tr("Pas un de vos jobs FLUX : lecture seule", 'Not one of your FLUX jobs: read only')}</div>}
      {items.map(it => (
        <button key={it.id} type="button" onClick={() => { onClose(); onPick(it.id) }}
          style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%', padding: '5px 8px', border: 'none', borderRadius: 4,
            background: 'none', cursor: 'pointer', fontSize: 11.5, fontFamily: 'var(--sans)', textAlign: 'left',
            color: it.danger ? 'var(--err)' : 'var(--ink)' }}
          onMouseEnter={e => { e.currentTarget.style.background = 'var(--paper-2)' }}
          onMouseLeave={e => { e.currentTarget.style.background = 'none' }}>
          {it.icon}{it.label}
        </button>
      ))}
    </div>
  )
}
