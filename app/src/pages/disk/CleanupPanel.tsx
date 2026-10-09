// CleanupPanel — put an asset or a whole project back on the current FLUX layout
// (2026-09-25, ADR 0033). The rules live in the backend and follow the running FLUX
// code (asset_cleanup.py): files go back to their FLUX place, identical duplicates are
// dropped, a journal undoes it. Anything unsure is a warning, never touched.

import { useCallback, useEffect, useState } from 'react'
import { Sparkles, RotateCcw, Copy } from 'lucide-react'
import { api } from '../../api/client'
import type { CleanupItem, CleanupScan } from '../../api/client'
import { Btn, Check, SecTitle } from '../../components/shared/ui'
import { toast } from 'sonner'

const errMsg = (e: unknown): string => (e instanceof Error ? e.message : String(e))

const ACTION_LABEL: Record<CleanupItem['action'], string> = {
  move:     'Remettre à sa place',
  drop_dup: 'Doublon identique',
  drop_tmp: 'Temporaire',
  rm_empty: 'Dossier vide',
  warn:     'Gardé',
}

function humanSize(n: number): string {
  if (n < 1024) return `${n} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let v = n / 1024
  let i = 0
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++ }
  return `${v.toFixed(v < 10 ? 2 : v < 100 ? 1 : 0)} ${units[i]}`
}

const selectStyle: React.CSSProperties = {
  padding: '4px 8px', fontSize: 11, fontFamily: 'var(--sans)', background: 'var(--paper-2)',
  color: 'var(--ink)', border: '1px solid var(--rule-2)', borderRadius: 5,
}

export function CleanupPanel({ activeProject }: { activeProject: string | null }) {
  const [projects, setProjects] = useState<string[]>([])
  const [project, setProject] = useState(activeProject ?? '')
  const [assets, setAssets] = useState<string[]>([])
  const [asset, setAsset] = useState('')          // '' = the whole project
  const [scan, setScan] = useState<CleanupScan | null>(null)
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)
  const [backups, setBackups] = useState<{ id: string; files: number }[]>([])
  const [cloneName, setCloneName] = useState('')
  const [showUnknown, setShowUnknown] = useState(false)

  useEffect(() => { api.getProjects().then(r => setProjects(r.projects)).catch(() => undefined) }, [])
  useEffect(() => { if (!project && activeProject) setProject(activeProject) }, [activeProject, project])
  const loadBackups = useCallback(() => {
    if (!project) { setBackups([]); return }
    api.getCleanupBackups(project).then(r => setBackups(r.backups)).catch(() => setBackups([]))
  }, [project])
  useEffect(() => {
    setScan(null); setAsset('')
    if (!project) { setAssets([]); return }
    api.getAssets(project).then(r => setAssets(r.assets)).catch(() => setAssets([]))
    loadBackups()
    setCloneName(`${project}_CLEAN`)
  }, [project, loadBackups])

  const analyse = async () => {
    if (!project) return
    setBusy(true)
    try {
      const r = await api.scanCleanup(project, asset || undefined)
      setScan(r)
      setPicked(new Set(r.items.filter(i => i.safe).map(i => i.id)))
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setBusy(false)
    }
  }

  const apply = async () => {
    if (!project || picked.size === 0) return
    if (!window.confirm(`Appliquer ${picked.size} opération(s) ? (annulable)`)) return
    setBusy(true)
    try {
      const r = await api.applyCleanup(project, [...picked], asset || undefined)
      toast.success(`${r.moved} fichier(s) remis à leur place, ${r.dropped} doublon(s) / temporaire(s) retiré(s)`)
      r.errors.slice(0, 3).forEach(e => toast.warning(e))
      loadBackups()
      await analyse()
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setBusy(false)
    }
  }

  const restore = async (id: string) => {
    if (!window.confirm(`Annuler le nettoyage du ${id} ?`)) return
    setBusy(true)
    try {
      const r = await api.restoreCleanup(project, id)
      toast.success(`${r.restored} fichier(s) remis comme avant`)
      if (r.already_there.length) toast.warning(`${r.already_there.length} chemin(s) repris depuis : laissés tels quels`)
      loadBackups()
      setScan(null)
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setBusy(false)
    }
  }

  const clone = async () => {
    if (!project || !cloneName.trim()) return
    if (!window.confirm(`Cloner ${project} en ${cloneName.trim()}, remis sur la structure FLUX actuelle ? Le projet d'origine ne change pas.`)) return
    setBusy(true)
    try {
      const r = await api.cloneProject(project, cloneName.trim())
      toast.success(`Projet ${r.project} créé : ${r.moved} fichier(s) remis à leur place, ${r.dropped} doublon(s) retiré(s)`)
      if (r.warnings) toast.warning(`${r.warnings} avertissement(s) : à voir en analysant ${r.project}`)
      api.getProjects().then(p => setProjects(p.projects)).catch(() => undefined)
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setBusy(false)
    }
  }

  const safeItems = scan?.items.filter(i => i.safe) ?? []
  const warnItems = scan?.items.filter(i => !i.safe) ?? []
  const pickedFiles = safeItems.filter(i => picked.has(i.id)).reduce((n, i) => n + Math.max(i.files, 1), 0)

  return (
    <div style={{ marginBottom: 20 }}>
      <SecTitle>Nettoyage (structure FLUX actuelle)</SecTitle>
      <div style={{ fontSize: 11, color: 'var(--ink-3)', marginBottom: 10, lineHeight: 1.5 }}>
        Les règles suivent le code FLUX en cours : chaque fichier publié est remis à sa place FLUX, un doublon identique
        est retiré, et seul ce qui est sûr se fait (annulable). Le reste est un avertissement et n'est jamais touché.
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
        <select value={project} onChange={e => setProject(e.target.value)} style={selectStyle}>
          <option value="">Projet…</option>
          {projects.map(p => <option key={p} value={p}>{p}</option>)}
        </select>
        <select value={asset} onChange={e => { setAsset(e.target.value); setScan(null) }} style={selectStyle} disabled={!project}>
          <option value="">Tout le projet</option>
          {assets.map(a => <option key={a} value={a}>{a}</option>)}
        </select>
        <Btn onClick={() => { void analyse() }} disabled={!project || busy}>
          <Sparkles size={12} strokeWidth={2} />
          {busy ? 'Analyse…' : 'Analyser'}
        </Btn>
        <div style={{ flex: 1 }} />
        <input value={cloneName} onChange={e => setCloneName(e.target.value)} disabled={!project}
          placeholder="NOM_DU_CLONE" style={{ ...selectStyle, width: 170, fontFamily: 'var(--mono)' }} />
        <Btn onClick={() => { void clone() }} disabled={!project || !cloneName.trim() || busy}
          title="Copie du projet remise sur la structure FLUX actuelle ; l'original ne change pas">
          <Copy size={12} strokeWidth={2} />
          Cloner propre
        </Btn>
      </div>

      {scan && (
        <div style={{ border: '1px solid var(--rule-2)', borderRadius: 6, overflow: 'hidden', marginBottom: 10 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 10px', fontSize: 11,
                        background: 'var(--paper-2)', borderBottom: '1px solid var(--rule)' }}>
            <span><b>{safeItems.length}</b> opération(s)</span>
            <span style={{ color: 'var(--warn)' }}><b>{warnItems.length}</b> avertissement(s)</span>
            <span style={{ color: 'var(--ink-3)' }}>{scan.unknown.length} fichier(s) non FLUX gardé(s)</span>
            <div style={{ flex: 1 }} />
            <Btn ghost sm onClick={() => setPicked(new Set(safeItems.map(i => i.id)))}>Tout</Btn>
            <Btn ghost sm onClick={() => setPicked(new Set())}>Aucun</Btn>
            <Btn primary sm onClick={() => { void apply() }} disabled={busy || picked.size === 0}>
              Appliquer ({pickedFiles} élément(s))
            </Btn>
          </div>
          {scan.items.length === 0 && (
            <div style={{ padding: 12, fontSize: 11, color: 'var(--ink-3)' }}>Rien à faire : tout suit la structure FLUX.</div>
          )}
          {[...safeItems, ...warnItems].map(i => {
            const on = picked.has(i.id)
            return (
              <div key={i.id}
                onClick={() => {
                  if (!i.safe) return
                  setPicked(prev => { const n = new Set(prev); if (n.has(i.id)) n.delete(i.id); else n.add(i.id); return n })
                }}
                style={{ display: 'flex', alignItems: 'flex-start', gap: 10, padding: '6px 10px', fontSize: 11,
                         borderBottom: '1px solid var(--rule)', cursor: i.safe ? 'pointer' : 'default' }}>
                <div style={{ width: 14, paddingTop: 1 }}>
                  {i.safe ? <Check on={on} /> : <span title="Pas sûr : gardé" style={{ color: 'var(--warn)' }}>!</span>}
                </div>
                <span style={{ width: 140, color: i.safe ? 'var(--ink-2)' : 'var(--warn)', flexShrink: 0 }}>{ACTION_LABEL[i.action]}</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontFamily: 'var(--mono)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                    title={i.target ? `${i.path} -> ${i.target}` : i.path}>
                    {i.path}/{i.target && i.action === 'move' ? <span style={{ color: 'var(--accent-hi)' }}>{'  →  '}{i.target}/</span> : null}
                  </div>
                  <div style={{ color: i.safe ? 'var(--ink-3)' : 'var(--warn)', fontSize: 11 }}>
                    {i.reason}{i.warning ? ` · ${i.warning}` : ''}
                    {i.names.length > 0 && <span style={{ fontFamily: 'var(--mono)' }}>{' · '}{i.names.join(', ')}{i.files > i.names.length ? '…' : ''}</span>}
                  </div>
                </div>
                <span style={{ fontFamily: 'var(--mono)', color: 'var(--ink-3)', width: 110, textAlign: 'right', flexShrink: 0 }}>
                  {i.files > 1 ? `${i.files} f. · ` : ''}{humanSize(i.bytes)}
                </span>
              </div>
            )
          })}
          {scan.unknown.length > 0 && (
            <div style={{ padding: '6px 10px', fontSize: 11, color: 'var(--ink-3)' }}>
              <span style={{ cursor: 'pointer', textDecoration: 'underline' }} onClick={() => setShowUnknown(v => !v)}>
                {showUnknown ? 'Masquer' : 'Voir'} les fichiers non FLUX (fichiers de travail, jamais déplacés)
              </span>
              {showUnknown && scan.unknown.slice(0, 300).map(u => (
                <div key={u} style={{ fontFamily: 'var(--mono)' }}>{u}</div>
              ))}
            </div>
          )}
        </div>
      )}

      {backups.length > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', fontSize: 11 }}>
          <span style={{ color: 'var(--ink-3)' }}>Nettoyages annulables :</span>
          {backups.slice(0, 6).map(b => (
            <Btn key={b.id} ghost sm onClick={() => { void restore(b.id) }} disabled={busy}
              title={`Remettre comme avant les ${b.files} fichier(s) de ce nettoyage`}>
              <RotateCcw size={11} strokeWidth={2} />
              {b.id} ({b.files})
            </Btn>
          ))}
        </div>
      )}
    </div>
  )
}
