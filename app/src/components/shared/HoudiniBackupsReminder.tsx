// HoudiniBackupsReminder — floating panel shown to the supervisors of the active project
// at 13h and 18h (2026-11-22, ADR 0092): "N backups Houdini a nettoyer". Nothing is
// deleted without a click. A slot missed while FLUX was closed shows at the next opening
// the same day (only the latest passed slot). Each slot is answered once per machine
// (localStorage, a convenience: lost storage only means the panel may show again).
// The full list and the manual run live in Reglages > Avance > Disque.

import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Trash2 } from 'lucide-react'
import { api } from '../../api/client'
import type { HoudiniBackupScan } from '../../api/client'
import { rolesApi } from '../../api/roles'
import { useProject } from '../../ProjectContext'
import { humanSize } from '../../pages/disk/HoudiniBackupsPanel'
import { Btn } from './ui'
import { toast } from 'sonner'

export const REMINDER_HOURS = [13, 18]
const STORE_KEY = 'flux.houdiniBackups.answered'
const CHECK_MS = 60_000

/** Key of the latest slot already passed today ("2026-11-22@13"), null before the first one. */
export function currentSlot(now: Date, hours: number[] = REMINDER_HOURS): string | null {
  const passed = hours.filter(h => now.getHours() >= h)
  if (!passed.length) return null
  const d = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
  return `${d}@${Math.max(...passed)}`
}

function answered(project: string): string {
  try { return (JSON.parse(localStorage.getItem(STORE_KEY) || '{}') as Record<string, string>)[project] || '' } catch { return '' }
}

function markAnswered(project: string, slot: string): void {
  try {
    const all = JSON.parse(localStorage.getItem(STORE_KEY) || '{}') as Record<string, string>
    all[project] = slot
    localStorage.setItem(STORE_KEY, JSON.stringify(all))
  } catch { /* storage off: the panel may show again */ }
}

export function HoudiniBackupsReminder() {
  const { project } = useProject()
  const navigate = useNavigate()
  const [isSup, setIsSup] = useState(false)
  const [shown, setShown] = useState<{ slot: string; scan: HoudiniBackupScan } | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    setIsSup(false); setShown(null)
    if (!project) return
    let alive = true
    rolesApi.get(project).then(r => { if (alive) setIsSup(r.me.role === 'supervisor') }).catch(() => undefined)
    return () => { alive = false }
  }, [project])

  const check = useCallback(async () => {
    if (!project || !isSup || shown || busy) return
    const slot = currentSlot(new Date())
    if (!slot || answered(project) === slot) return
    try {
      const scan = await api.scanHoudiniBackups(project)
      if (!scan.enabled || scan.items.length === 0) { markAnswered(project, slot); return }
      setShown({ slot, scan })
    } catch { /* backend busy or down: next tick */ }
  }, [project, isSup, shown, busy])

  useEffect(() => {
    void check()
    const id = window.setInterval(() => { void check() }, CHECK_MS)
    return () => window.clearInterval(id)
  }, [check])

  if (!shown || !project) return null
  const { slot, scan } = shown
  const close = () => { markAnswered(project, slot); setShown(null) }

  const clean = async () => {
    setBusy(true)
    try {
      const r = await api.applyHoudiniBackups(project, scan.items.map(i => i.id))
      toast.success(`${r.deleted} backup(s) Houdini supprime(s), ${humanSize(r.freed)} liberes`)
      r.errors.slice(0, 3).forEach(e => toast.warning(e))
      close()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div role="dialog" aria-label="Backups Houdini a nettoyer" style={{
      position: 'fixed', right: 18, bottom: 40, zIndex: 900, width: 320, padding: 14,
      background: 'var(--paper-2)', border: '1px solid var(--rule-2)', borderRadius: 8,
      boxShadow: '0 4px 14px rgba(0,0,0,0.25)', fontFamily: 'var(--sans)', fontSize: 11, color: 'var(--ink)',
    }}>
      <div style={{ fontWeight: 600, fontSize: 12, marginBottom: 6 }}>Backups Houdini a nettoyer</div>
      <div style={{ color: 'var(--ink-2)', lineHeight: 1.5, marginBottom: 12 }}>
        {project} : <b>{scan.items.length}</b> backup(s) de plus de {scan.days} jours, {humanSize(scan.total_size)}.
        Le plus recent de chaque scene reste. Suppression definitive.
      </div>
      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
        <Btn ghost sm disabled={busy} onClick={close}>Plus tard</Btn>
        <Btn ghost sm disabled={busy} onClick={() => { close(); navigate('/settings?tab=advanced&sub=disk') }}>Voir la liste</Btn>
        <Btn primary sm disabled={busy} onClick={() => { void clean() }}>
          <Trash2 size={11} strokeWidth={2} />
          Nettoyer
        </Btn>
      </div>
    </div>
  )
}
