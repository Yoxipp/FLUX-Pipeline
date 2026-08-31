import { useEffect, useState } from 'react'
import { Upload, Download, Zap, RefreshCw, CheckCircle2, XCircle, ArrowRight, Trash2, Package } from 'lucide-react'
import { SoftwareSelector } from '../components/shared/SoftwareSelector'
import { Btn, SecTitle, Pill } from '../components/shared/ui'
import { api } from '../api/client'
import type { LucideIcon } from 'lucide-react'

const ShelfBtn = ({ icon: Icon, label, primary }: { icon: LucideIcon; label: string; primary?: boolean }) => (
  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 5 }}>
    <div style={{
      width: 40, height: 40, borderRadius: 9,
      border: primary ? '1px solid var(--accent)' : '1px solid var(--rule-2)',
      background: primary ? 'var(--accent-soft)' : 'var(--paper)',
      color: primary ? 'var(--accent-hi)' : 'var(--ink-3)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      boxShadow: 'var(--shadow-sm)',
      transition: 'box-shadow 0.12s',
    }}>
      <Icon size={16} strokeWidth={1.75} />
    </div>
    <div className="lbl" style={{ fontSize: 9 }}>{label}</div>
  </div>
)

type StatusBadge = { ok: boolean; label: string }

function Badge({ ok, label }: StatusBadge) {
  const Icon = ok ? CheckCircle2 : XCircle
  const color = ok ? 'var(--ok)' : 'var(--err)'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 10 }}>
      <Icon size={11} strokeWidth={2} color={color} style={{ flexShrink: 0 }} />
      <span style={{ color: ok ? 'var(--ink-2)' : 'var(--err)' }}>{label}</span>
    </div>
  )
}

type ShelfData = {
  versions: string[]
  installed: Record<string, boolean>
  hdas_installed: Record<string, boolean>
}

type AllShelvesResponse = Record<string, ShelfData>

type LogEntry = { type: 'ok' | 'err' | 'info'; msg: string }

export function ShelfManager() {
  const [dcc, setDcc] = useState('Houdini')
  const [version, setVersion] = useState('')
  const [shelfData, setShelfData] = useState<AllShelvesResponse>({})
  const [log, setLog] = useState<LogEntry[]>([])
  const [busy, setBusy] = useState(false)
  const [tools, setTools] = useState<{ id: string; label: string; installed: Record<string, boolean> }[]>([])
  const [toolVersions, setToolVersions] = useState<string[]>([])
  const [toolVersion, setToolVersion] = useState('')

  const currentData: ShelfData = shelfData[dcc] ?? { versions: [], installed: {}, hdas_installed: {} }
  const versions = currentData.versions

  function addLog(type: LogEntry['type'], msg: string) {
    setLog(prev => [...prev.slice(-49), { type, msg }])
  }

  async function fetchStatus() {
    try {
      const data = await api.getShelves()
      setShelfData(data as AllShelvesResponse)
      const dccData = (data as AllShelvesResponse)[dcc]
      if (dccData && dccData.versions.length > 0) {
        setVersion(v => v || dccData.versions[dccData.versions.length - 1])
      }
    } catch (err) {
      addLog('err', `Fetch failed: ${err}`)
    }
  }

  useEffect(() => { fetchStatus() }, [dcc])

  async function handleInstall() {
    if (!version) return
    setBusy(true)
    addLog('info', `Installing ${dcc} ${version} shelf…`)
    try {
      const res = await api.installShelf(dcc, version)
      addLog('ok', (res as { message: string }).message)
    } catch (err) {
      addLog('err', `Install failed: ${err}`)
    } finally {
      await fetchStatus()
      setBusy(false)
    }
  }

  async function handleRemove() {
    if (!version) return
    setBusy(true)
    addLog('info', `Removing ${dcc} ${version} shelf…`)
    try {
      const res = await api.removeShelf(dcc, version)
      addLog('ok', (res as { message: string }).message)
    } catch (err) {
      addLog('err', `Remove failed: ${err}`)
    } finally {
      await fetchStatus()
      setBusy(false)
    }
  }

  async function handleRefresh() {
    setBusy(true)
    addLog('info', 'Refreshing status…')
    await fetchStatus()
    addLog('ok', 'Status updated')
    setBusy(false)
  }

  async function fetchTools() {
    try {
      const d = await api.getTools()
      setTools(d.tools)
      setToolVersions(d.versions)
      setToolVersion(v => v || (d.versions[d.versions.length - 1] ?? ''))
    } catch { /* backend indispo : on ignore */ }
  }
  useEffect(() => { fetchTools() }, [])

  async function handleTool(id: string, remove: boolean) {
    if (!toolVersion) return
    setBusy(true)
    try {
      const res = remove ? await api.removeTool(id, toolVersion)
                         : await api.installTool(id, toolVersion)
      addLog('ok', res.message)
      await fetchTools()
    } catch (e: any) {
      addLog('err', String(e?.message ?? e))
    } finally {
      setBusy(false)
    }
  }

  const shelfOk = version ? (currentData.installed[version] ?? false) : false
  const hdaOk   = version ? (currentData.hdas_installed[version] ?? false) : false
  const isHoudini = dcc === 'Houdini'

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>

      <div style={{ padding: '12px 20px 10px', borderBottom: '1px solid var(--rule)', flexShrink: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)' }}>Gestion du Shelf</div>
      </div>

      <SoftwareSelector active={dcc} onChange={v => { setDcc(v); setVersion('') }} showLocal={false} />

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, overflow: 'hidden' }}>

        <div style={{ padding: '16px 20px 0', display: 'flex', flexDirection: 'column', gap: 16, flexShrink: 0 }}>

          {/* version */}
          <div>
            <SecTitle>Version cible</SecTitle>
            {versions.length === 0 ? (
              <div className="lbl" style={{ fontSize: 10, color: 'var(--ink-4)' }}>
                Aucune version {dcc} détectée
              </div>
            ) : (
              <div style={{ display: 'flex', gap: 6 }}>
                {versions.map(v => (
                  <Pill key={v} active={version === v} style={{ cursor: 'pointer' }}>
                    <span onClick={() => setVersion(v)}>{v}</span>
                  </Pill>
                ))}
              </div>
            )}
          </div>

          {/* status badges */}
          {version && (
            <div>
              <SecTitle>État</SecTitle>
              <div style={{ display: 'flex', gap: 16 }}>
                <Badge ok={shelfOk} label={shelfOk ? 'Shelf installé' : 'Shelf absent'} />
                {isHoudini && (
                  <Badge ok={hdaOk} label={hdaOk ? 'HDAs installés' : 'HDAs absents'} />
                )}
              </div>
            </div>
          )}

          {/* aperçu shelf */}
          <div>
            <SecTitle>Aperçu du shelf</SecTitle>
            <div className="card" style={{ padding: '14px 20px', display: 'flex', gap: 20, alignItems: 'flex-start' }}>
              <ShelfBtn icon={Upload}     label="Exporter" primary />
              <ShelfBtn icon={Download}   label="Importer" />
              {isHoudini && <ShelfBtn icon={Package} label="HDAs" />}
              <div style={{ flex: 1 }} />
              <div className="lbl" style={{ alignSelf: 'center', textAlign: 'right', lineHeight: 1.5 }}>
                Rendu approximatif<br />
                <span style={{ color: 'var(--ink-4)' }}>Icônes réelles dans le repo</span>
              </div>
            </div>
          </div>

          {/* actions */}
          <div>
            <SecTitle>Actions</SecTitle>
            <div style={{ display: 'flex', gap: 8 }}>
              <Btn primary disabled={!version || busy} style={{ flex: 1, height: 32, justifyContent: 'center', gap: 6 }} onClick={handleInstall}>
                <Zap size={12} strokeWidth={2} />
                {isHoudini ? 'Installer shelf + HDAs' : 'Installer le shelf'}
              </Btn>
              <Btn ghost disabled={busy} style={{ height: 32, gap: 5 }} onClick={handleRefresh}>
                <RefreshCw size={11} strokeWidth={2} />
                Màj
              </Btn>
              <Btn ghost disabled={!version || busy} style={{ height: 32, gap: 5 }} onClick={handleRemove}>
                <Trash2 size={11} strokeWidth={2} />
                Retirer
              </Btn>
            </div>
          </div>

          {/* Catalogue de tools Maya (rig toolbox / anim tool / flux) — Maya only.
              Rigging/Anim toolboxes are Maya-specific; Houdini has no equivalent. */}
          {dcc === 'Maya' && (
          <div>
            <SecTitle>Tools Maya (catalogue)</SecTitle>
            {toolVersions.length === 0 ? (
              <div className="lbl" style={{ fontSize: 10, color: 'var(--ink-4)' }}>
                Aucune version Maya détectée
              </div>
            ) : (
              <>
                <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
                  {toolVersions.map(v => (
                    <Pill key={v} active={toolVersion === v} style={{ cursor: 'pointer' }}>
                      <span onClick={() => setToolVersion(v)}>{v}</span>
                    </Pill>
                  ))}
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {tools.map(t => {
                    const ok = toolVersion ? (t.installed[toolVersion] ?? false) : false
                    return (
                      <div key={t.id} className="card" style={{ padding: '10px 14px', display: 'flex', alignItems: 'center', gap: 12 }}>
                        <div style={{ flex: 1, fontSize: 12, color: 'var(--ink)' }}>{t.label}</div>
                        <Badge ok={ok} label={ok ? 'Installé' : 'Absent'} />
                        <Btn primary disabled={busy || !toolVersion} style={{ height: 28, gap: 5 }} onClick={() => { void handleTool(t.id, false) }}>
                          <Download size={11} strokeWidth={2} />
                          Installer
                        </Btn>
                        <Btn ghost disabled={busy || !toolVersion || !ok} style={{ height: 28, gap: 5 }} onClick={() => { void handleTool(t.id, true) }}>
                          <Trash2 size={11} strokeWidth={2} />
                          Retirer
                        </Btn>
                      </div>
                    )
                  })}
                </div>
              </>
            )}
          </div>
          )}

        </div>

        {/* log */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', padding: '16px 20px 20px', minHeight: 0 }}>
          <SecTitle>Log</SecTitle>
          <div className="card" style={{
            flex: 1, padding: '10px 14px', minHeight: 0, overflowY: 'auto',
            fontFamily: 'var(--mono)', fontSize: 10, lineHeight: 2.0,
            color: 'var(--ink-2)', display: 'flex', flexDirection: 'column', gap: 2,
          }}>
            {log.length === 0 ? (
              <div style={{ color: 'var(--ink-4)' }}>En attente d&apos;une action</div>
            ) : (
              log.map((e, i) => {
                const Icon = e.type === 'ok' ? CheckCircle2 : e.type === 'err' ? XCircle : ArrowRight
                const color = e.type === 'ok' ? 'var(--ok)' : e.type === 'err' ? 'var(--err)' : 'var(--ink-4)'
                return (
                  <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                    <Icon size={11} strokeWidth={2} color={color} style={{ flexShrink: 0 }} />
                    <span style={{ color: e.type === 'err' ? 'var(--err)' : e.type === 'info' ? 'var(--ink-4)' : 'var(--ink-2)' }}>
                      {e.msg}
                    </span>
                  </div>
                )
              })
            )}
            <div style={{ flex: 1 }} />
            {version && (
              <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid var(--rule)', color: 'var(--ink-4)', display: 'flex', alignItems: 'center', gap: 6 }}>
                <span className="dot" style={{ width: 5, height: 5, background: shelfOk ? 'var(--ok)' : 'var(--err)', borderRadius: '50%' }} />
                {shelfOk ? `Shelf actif · ${version}` : `Shelf inactif · ${version}`}
                {isHoudini && (
                  <>
                    <span style={{ margin: '0 4px' }}>·</span>
                    <span className="dot" style={{ width: 5, height: 5, background: hdaOk ? 'var(--ok)' : 'var(--err)', borderRadius: '50%' }} />
                    {hdaOk ? 'HDAs OK' : 'HDAs manquants'}
                  </>
                )}
              </div>
            )}
          </div>
        </div>

      </div>
    </div>
  )
}
