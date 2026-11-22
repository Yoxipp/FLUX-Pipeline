// HoudiniBackupsPanel — Disque: Houdini backups and autosave copies of the active project
// (ADR 0090 point 8, ADR 0092). The backend lists only files older than the setting and
// always keeps the newest of each scene; deletion is final, so the user picks and confirms.
// The same scan feeds the 13h / 18h panel of the supervisors (HoudiniBackupsReminder).

import { useCallback, useEffect, useState } from 'react'
import { Trash2, Search } from 'lucide-react'
import { api } from '../../api/client'
import type { HoudiniBackupScan } from '../../api/client'
import { Btn, Check, SecTitle } from '../../components/shared/ui'
import { toast } from 'sonner'

const errMsg = (e: unknown): string => (e instanceof Error ? e.message : String(e))

export function humanSize(n: number): string {
  if (n < 1024) return `${n} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let v = n / 1024
  let i = 0
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++ }
  return `${v.toFixed(v < 10 ? 2 : v < 100 ? 1 : 0)} ${units[i]}`
}

export function HoudiniBackupsPanel({ activeProject }: { activeProject: string | null }) {
  const [scan, setScan] = useState<HoudiniBackupScan | null>(null)
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)

  const analyse = useCallback(async () => {
    if (!activeProject) return
    setBusy(true)
    try {
      const r = await api.scanHoudiniBackups(activeProject)
      setScan(r)
      setPicked(new Set(r.items.map(i => i.id)))
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setBusy(false)
    }
  }, [activeProject])

  useEffect(() => { setScan(null); setPicked(new Set()) }, [activeProject])

  const clean = async () => {
    if (!activeProject || picked.size === 0) return
    if (!window.confirm(`Supprimer definitivement ${picked.size} backup(s) Houdini ? Pas d annulation.`)) return
    setBusy(true)
    try {
      const r = await api.applyHoudiniBackups(activeProject, [...picked])
      toast.success(`${r.deleted} backup(s) supprime(s), ${humanSize(r.freed)} liberes`)
      r.errors.slice(0, 3).forEach(e => toast.warning(e))
      await analyse()
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setBusy(false)
    }
  }

  const items = scan?.items ?? []
  const pickedSize = items.filter(i => picked.has(i.id)).reduce((n, i) => n + i.size, 0)

  return (
    <div style={{ marginBottom: 20 }}>
      <SecTitle>Backups Houdini</SecTitle>
      <div style={{ fontSize: 11, color: 'var(--ink-3)', marginBottom: 10, lineHeight: 1.5 }}>
        Projet actif : backups Houdini des travaux FLUX Work (backup/, *_bak*) et copies d autosave de ce poste, plus
        vieux que le reglage avance. Le plus recent de chaque scene reste, les versions wNNN ne sont jamais touchees.
        Suppression definitive.
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <Btn onClick={() => { void analyse() }} disabled={!activeProject || busy}
          title={activeProject ? undefined : 'Aucun projet actif'}>
          <Search size={12} strokeWidth={2} />
          {busy ? 'Analyse…' : 'Analyser'}
        </Btn>
        {!activeProject && <span style={{ fontSize: 11, color: 'var(--ink-3)' }}>Aucun projet actif.</span>}
      </div>

      {scan && !scan.enabled && (
        <div style={{ fontSize: 11, color: 'var(--ink-3)' }}>Cleaner coupe (reglage avance a 0 jour).</div>
      )}
      {scan && scan.enabled && (
        <div style={{ border: '1px solid var(--rule-2)', borderRadius: 6, overflow: 'hidden' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 10px', fontSize: 11,
                        background: 'var(--paper-2)', borderBottom: '1px solid var(--rule)' }}>
            <span><b>{items.length}</b> backup(s) de plus de {scan.days} j · {humanSize(scan.total_size)}</span>
            <span style={{ color: 'var(--ink-3)' }}>{scan.kept} gardé(s)</span>
            <div style={{ flex: 1 }} />
            <Btn ghost sm onClick={() => setPicked(new Set(items.map(i => i.id)))}>Tout</Btn>
            <Btn ghost sm onClick={() => setPicked(new Set())}>Aucun</Btn>
            <Btn primary sm onClick={() => { void clean() }} disabled={busy || picked.size === 0}>
              <Trash2 size={11} strokeWidth={2} />
              Nettoyer ({picked.size} · {humanSize(pickedSize)})
            </Btn>
          </div>
          {items.length === 0 && (
            <div style={{ padding: 12, fontSize: 11, color: 'var(--ink-3)' }}>Rien a nettoyer.</div>
          )}
          {items.map(i => (
            <div key={i.id}
              onClick={() => setPicked(prev => { const n = new Set(prev); if (n.has(i.id)) n.delete(i.id); else n.add(i.id); return n })}
              style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '5px 10px', fontSize: 11,
                       borderBottom: '1px solid var(--rule)', cursor: 'pointer' }}>
              <div style={{ width: 14 }}><Check on={picked.has(i.id)} /></div>
              <span style={{ width: 70, color: 'var(--ink-3)', flexShrink: 0 }}>{i.where === 'autosave' ? 'autosave' : 'backup'}</span>
              <span style={{ flex: 1, minWidth: 0, fontFamily: 'var(--mono)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                title={i.path}>{i.path}</span>
              <span style={{ fontFamily: 'var(--mono)', color: 'var(--ink-3)', width: 130, textAlign: 'right', flexShrink: 0 }}>
                {i.age_days} j · {humanSize(i.size)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
