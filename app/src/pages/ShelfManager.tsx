import { useCallback, useEffect, useState } from 'react'
import { Zap, RefreshCw, CheckCircle2, XCircle, ArrowRight, Trash2 } from 'lucide-react'
import { SoftwareSelector } from '../components/shared/SoftwareSelector'
import { Btn, SecTitle, Pill, Check } from '../components/shared/ui'
import { FluxLogo } from '../components/shared/Logo'
import { api } from '../api/client'
import { useProject } from '../ProjectContext'

// Shelf tool tints — ANIM (orange) / RIG (blue), matching the Maya shelf icons.
const ANIM_COLOR = 'oklch(70% 0.15 52)'
const RIG_COLOR  = 'oklch(60% 0.18 250)'
// Painter shelf = the project's export presets, green F (2026-09-26).
const PAINTER_COLOR = 'oklch(72% 0.17 150)'
// Maya base rigs of the Flux shelf: Camera Rig green, Light Rig yellow (2026-09-26).
const CAM_COLOR   = 'oklch(72% 0.17 150)'
const LIGHT_COLOR = 'oklch(84% 0.16 92)'
// ZBrush: FLUX menu of the bridge (Export FLUX, Save +1) on top of the FLUX UI (2026-09-30).
const ZBRUSH_COLOR = 'oklch(70% 0.15 52)'

// "FLUX_BEAUTY_MAPS" -> "BEAUTY" for the shelf button label.
function presetLabel(name: string): string {
  return name.replace(/^FLUX_/i, '').replace(/_MAPS$/i, '') || name
}

const ShelfBtn =({ icon, label, primary }: { icon: React.ReactNode; label: string; primary?: boolean }) => (
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
      {icon}
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
  const [tools, setTools] = useState<{ id: string; label: string; selected: boolean }[]>([])
  const [toolVersions, setToolVersions] = useState<string[]>([])
  const [toolVersion, setToolVersion] = useState('')
  const [toolsInstalled, setToolsInstalled] = useState<Record<string, boolean>>({})
  const [checked, setChecked] = useState<Record<string, boolean>>({})

  // Painter: the export presets of the current project (project.json texturing.painter_presets).
  const { project } = useProject()
  const [painterBundled, setPainterBundled] = useState<string[]>([])
  const [painterPicked, setPainterPicked] = useState<string[]>([])
  const loadPainterPresets = useCallback(async () => {
    try {
      const r = await api.getPainterPresets(project || undefined)
      setPainterBundled(r.bundled)
      setPainterPicked(r.project)
    } catch { /* backend indispo : on ignore */ }
  }, [project])
  useEffect(() => { if (dcc === 'Painter') void loadPainterPresets() }, [dcc, loadPainterPresets])
  async function togglePainterPreset(name: string) {
    if (!project) return
    const next = painterPicked.includes(name) ? painterPicked.filter(n => n !== name) : [...painterPicked, name]
    setPainterPicked(next)
    try {
      await api.putPainterPresets(project, next)
      addLog('ok', `Presets Painter de ${project} : ${next.length ? next.join(', ') : 'tous'}`)
    } catch (e: any) {
      addLog('err', String(e?.message ?? e))
      void loadPainterPresets()
    }
  }
  const isPainter = dcc === 'Painter'
  // What the Publisher will offer: the project's presets, all of them when none is picked.
  const painterShelf = painterPicked.length ? painterPicked : painterBundled

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
      setToolsInstalled(d.installed)
      setChecked(Object.fromEntries(d.tools.map(t => [t.id, t.selected])))
    } catch { /* backend indispo : on ignore */ }
  }
  useEffect(() => { fetchTools() }, [])

  // Install the single Flux shelf with the checked tools (selection persists backend-side).
  async function handleApplyTools() {
    if (!toolVersion) return
    setBusy(true)
    const ids = tools.filter(t => checked[t.id]).map(t => t.id)
    addLog('info', `Installation shelf Flux (${ids.length} tool(s))…`)
    try {
      const res = await api.applyTools(toolVersion, ids)
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
  const isZBrush = dcc === 'ZBrush'

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>

      <div style={{ padding: '12px 20px 10px', borderBottom: '1px solid var(--rule)', flexShrink: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)' }}>Gestion du Shelf</div>
      </div>

      <SoftwareSelector active={dcc} onChange={v => { setDcc(v); setVersion('') }} showLocal={false} />

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, overflow: 'hidden' }}>

        <div style={{ padding: '16px 20px 0', display: 'flex', flexDirection: 'column', gap: 16, flexShrink: 0 }}>

          {/* version */}
          {!isPainter && <div>
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
          </div>}

          {/* status badges */}
          {version && !isPainter && (
            <div>
              <SecTitle>État</SecTitle>
              <div style={{ display: 'flex', gap: 16 }}>
                <Badge ok={shelfOk} label={isZBrush ? (shelfOk ? 'UI FLUX installée' : 'UI FLUX absente') : shelfOk ? 'Shelf installé' : 'Shelf absent'} />
                {isHoudini && (
                  <Badge ok={hdaOk} label={hdaOk ? 'HDAs installés' : 'HDAs absents'} />
                )}
              </div>
            </div>
          )}

          {/* aperçu shelf */}
          <div>
            <SecTitle>Aperçu du shelf</SecTitle>
            <div className="card" style={{ padding: '14px 20px', display: 'flex', flexWrap: 'wrap', gap: 20, alignItems: 'center', minHeight: 62 }}>
              {isPainter ? (
                painterShelf.length ? painterShelf.map(p => (
                  <ShelfBtn key={p} icon={<FluxLogo size={20} color={PAINTER_COLOR} />} label={presetLabel(p)} />
                )) : <div className="lbl" style={{ fontSize: 10, color: 'var(--ink-4)' }}>Aucun preset FLUX livré</div>
              ) : isZBrush ? (
                <>
                  <ShelfBtn icon={<FluxLogo size={20} color={ZBRUSH_COLOR} />} label="EXPORT FLUX" primary />
                  <ShelfBtn icon={<FluxLogo size={20} color={CAM_COLOR} />} label="SAVE +1" />
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 3, marginLeft: 6, paddingLeft: 16, borderLeft: '1px solid var(--rule-2)' }}>
                    <div style={{ fontSize: 11, color: 'var(--ink)', fontFamily: 'var(--mono)' }}>flux_ui_zbrush</div>
                    <div className="lbl" style={{ fontSize: 9.5, color: 'var(--ink-3)' }}>UI FLUX (template Rongeart) · menu FLUX · auto-save QuickSave 10 min</div>
                  </div>
                </>
              ) : dcc === 'Maya' ? (
                <>
                  <ShelfBtn icon={<FluxLogo size={20} color={ANIM_COLOR} />} label="ANIM" />
                  <ShelfBtn icon={<FluxLogo size={20} color={RIG_COLOR} />} label="RIG" />
                  <ShelfBtn icon={<FluxLogo size={20} color={CAM_COLOR} />} label="CAM" />
                  <ShelfBtn icon={<FluxLogo size={20} color={LIGHT_COLOR} />} label="LIGHT" />
                </>
              ) : (
                <>
                  {/* One button per FLUX node (HDA): same list as resources/shelves/houdini/Flux.shelf. */}
                  {['Import', 'Export', 'Anim', 'Shot', 'Crowd', 'Lighting'].map(l => (
                    <ShelfBtn key={l} icon={<FluxLogo size={20} color={ANIM_COLOR} />} label={l} />
                  ))}
                </>
              )}
            </div>
          </div>

          {/* PAINTER: export presets of the project (moved from the Folder Manager). */}
          {isPainter && (
            <div>
              <SecTitle>Presets d'export Painter{project ? ` · ${project}` : ''}</SecTitle>
              {!project ? (
                <div className="lbl" style={{ fontSize: 10, color: 'var(--ink-4)' }}>Choisis un projet pour régler ses presets.</div>
              ) : (
                <div className="card" style={{ padding: '8px 14px', display: 'flex', flexDirection: 'column', gap: 2 }}>
                  {painterBundled.map(p => {
                    const on = painterPicked.includes(p)
                    return (
                      <div key={p} onClick={() => { void togglePainterPreset(p) }}
                        style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0', cursor: 'pointer',
                                 fontFamily: 'var(--mono)', fontSize: 11, color: on ? 'var(--ink)' : 'var(--ink-3)' }}>
                        <Check on={on} />
                        <FluxLogo size={13} color={PAINTER_COLOR} />
                        {p}
                      </div>
                    )
                  })}
                </div>
              )}
              <div className="lbl" style={{ fontSize: 10, color: 'var(--ink-4)', lineHeight: 1.5, marginTop: 6 }}>
                Le Publisher ne propose que les presets cochés pour ce projet ; aucun coché : tous.
                Les presets FLUX sont copiés dans Painter à l'installation du bridge (Autostart).
              </div>
            </div>
          )}

          {/* actions. Houdini: installing the shelf also installs (or rebuilds, when
              Houdini is connected) the FLUX HDAs; removing it keeps them (Autostart). */}
          {!isPainter && <div>
            <SecTitle>Actions</SecTitle>
            <div style={{ display: 'flex', gap: 8 }}>
              <Btn primary disabled={!version || busy} style={{ flex: 1, height: 32, justifyContent: 'center', gap: 6 }} onClick={handleInstall}>
                <Zap size={12} strokeWidth={2} />
                {isHoudini ? 'Installer shelf + HDAs' : isZBrush ? 'Installer UI FLUX + bridge' : 'Installer le shelf'}
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
            {isHoudini && (
              <div className="lbl" style={{ fontSize: 10, color: 'var(--ink-4)', lineHeight: 1.5, marginTop: 6 }}>
                Installer copie la shelf et les HDAs (reconstruits si Houdini est ouvert).
                Retirer enlève la shelf seulement : l'Autostart garde les HDAs.
              </div>
            )}
            {isZBrush && (
              <div className="lbl" style={{ fontSize: 10, color: 'var(--ink-4)', lineHeight: 1.5, marginTop: 6 }}>
                Installer remplace l'interface de ZBrush par l'UI FLUX (la tienne est gardée une fois de côté)
                et installe le bridge : menu FLUX avec Export FLUX et Save +1. Retirer remet ton interface. Relance ZBrush.
              </div>
            )}
          </div>}

          {/* Catalogue de tools Maya (rig toolbox / anim tool / flux) — Maya only.
              Rigging/Anim toolboxes are Maya-specific; Houdini has no equivalent. */}
          {dcc === 'Maya' && (
          <div>
            <SecTitle>Tools de la shelf Flux</SecTitle>
            {toolVersions.length === 0 ? (
              <div className="lbl" style={{ fontSize: 10, color: 'var(--ink-4)' }}>
                Aucune version Maya détectée
              </div>
            ) : (
              <>
                <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
                  {toolVersions.map(v => (
                    <Pill key={v} active={toolVersion === v} onClick={() => setToolVersion(v)} style={{ cursor: 'pointer' }}>{v}</Pill>
                  ))}
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {tools.map(t => (
                    <div
                      key={t.id}
                      className="card"
                      onClick={() => setChecked(c => ({ ...c, [t.id]: !c[t.id] }))}
                      style={{ padding: '10px 14px', display: 'flex', alignItems: 'center', gap: 12, cursor: 'pointer' }}
                    >
                      <div style={{
                        width: 16, height: 16, borderRadius: 4, flexShrink: 0,
                        border: '1.5px solid ' + (checked[t.id] ? 'var(--accent)' : 'var(--rule-2)'),
                        background: checked[t.id] ? 'var(--accent)' : 'transparent',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                      }}>
                        {checked[t.id] && <span style={{ color: 'white', fontSize: 10, fontWeight: 700, lineHeight: 1 }}>✓</span>}
                      </div>
                      <div style={{ flex: 1, fontSize: 12, color: 'var(--ink)' }}>{t.label}</div>
                    </div>
                  ))}
                </div>
                <div style={{ display: 'flex', gap: 10, marginTop: 10, alignItems: 'center' }}>
                  <Btn primary disabled={busy || !toolVersion} style={{ height: 30, gap: 6, justifyContent: 'center' }} onClick={() => { void handleApplyTools() }}>
                    <Zap size={12} strokeWidth={2} />
                    Installer les tools cochés
                  </Btn>
                  <div className="lbl" style={{ fontSize: 9, color: 'var(--ink-4)' }}>
                    {toolVersion && (toolsInstalled[toolVersion] ? `Shelf Flux installée · ${toolVersion}` : `Non installée · ${toolVersion}`)}
                  </div>
                </div>
                <div className="lbl" style={{ fontSize: 9, color: 'var(--ink-4)', marginTop: 6 }}>
                  Une seule shelf « Flux » regroupe les tools cochés. Ton choix est conservé pour les réinstallations.
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
