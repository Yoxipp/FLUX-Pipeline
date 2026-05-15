import React, { useState, useEffect, useCallback } from 'react'
import { ChevronDown } from 'lucide-react'
import { SoftwareSelector } from '../components/shared/SoftwareSelector'
import { Btn, SecTitle, FolderIcon } from '../components/shared/ui'
import { api } from '../api/client'
import { useSettings } from '../hooks/useSettings'

// ── FileBadge : affiche les tokens du fichier en cours ───────────────────────
const FileBadge = ({ classToken, typeName, assetName, instance }: {
  classToken: string; typeName: string; assetName: string; instance: string
}) => (
  <div style={{
    display: 'flex', width: '100%',
    border: '1px solid var(--rule-2)', borderRadius: 6, overflow: 'hidden',
    fontFamily: 'var(--mono)', fontSize: 11, boxShadow: 'var(--shadow-xs)',
  }}>
    {[
      { label: 'CLASS',    value: classToken || 'CHAR', tinted: true },
      { label: 'TYPE',     value: typeName   || '—' },
      { label: 'NAME',     value: assetName  || '—' },
      { label: 'INSTANCE', value: instance   || '—' },
      { label: 'LAST',     value: 'LAST',  accent: true },
    ].map((seg, i) => (
      <div key={i} style={{
        flex: 1, padding: '6px 9px',
        borderLeft: i > 0 ? '1px solid var(--rule-2)' : 'none',
        background: seg.tinted ? 'var(--accent-soft)' : (seg as { accent?: boolean }).accent ? 'var(--paper-2)' : 'var(--paper)',
        display: 'flex', flexDirection: 'column', gap: 3,
      }}>
        <div style={{ fontSize: 8, color: 'var(--ink-4)', letterSpacing: '0.12em', textTransform: 'uppercase' }}>{seg.label}</div>
        <div style={{ fontWeight: seg.tinted || (seg as { accent?: boolean }).accent ? 600 : 400, color: seg.tinted ? 'var(--accent-hi)' : (seg as { accent?: boolean }).accent ? 'var(--ink-2)' : 'var(--ink-4)', fontSize: 11 }}>{seg.value}</div>
      </div>
    ))}
  </div>
)

const UsdTreeRow = ({ depth = 0, glyph = '·', label, color, last }: {
  depth?: number; glyph?: string; label: string; color?: string; last?: boolean
}) => (
  <div style={{ display: 'flex', alignItems: 'center', fontFamily: 'var(--mono)', fontSize: 11, lineHeight: '22px', color: color ?? 'var(--ink-2)' }}>
    {Array.from({ length: depth }).map((_, i) => (
      <span key={i} style={{ display: 'inline-block', width: 16, color: 'var(--ink-4)' }}>
        {i === depth - 1 ? (last ? '└─' : '├─') : '│ '}
      </span>
    ))}
    <span style={{ marginRight: 6, color: 'var(--ink-3)' }}>{glyph}</span>
    <span>{label}</span>
  </div>
)

const PresetBtn = ({ title, sub, active, onClick }: {
  title: string; sub: string; active?: boolean; onClick?: () => void
}) => (
  <div onClick={onClick} style={{
    border: active ? '1px solid var(--accent)' : '1px solid var(--rule-2)',
    background: active ? 'var(--accent-soft)' : 'var(--paper-2)',
    padding: '9px 10px', borderRadius: 7, cursor: 'pointer',
    display: 'flex', flexDirection: 'column', gap: 3,
    boxShadow: 'var(--shadow-xs)',
    transition: 'border-color 0.12s, background 0.12s',
  }}>
    <div style={{ fontSize: 11, fontWeight: 600, color: active ? 'var(--ink)' : 'var(--ink-2)' }}>{title}</div>
    <div className="lbl" style={{ fontSize: 9 }}>{sub}</div>
  </div>
)

// ── InputRow : label + champ texte éditable ───────────────────────────────────
const InputRow = ({ label, value, onChange, placeholder, w = 260, readOnly }: {
  label: string; value: string; onChange?: (v: string) => void
  placeholder?: string; w?: number; readOnly?: boolean
}) => (
  <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 9 }}>
    <div style={{ width: 96, textAlign: 'right', color: 'var(--ink-3)', fontSize: 11, fontFamily: 'var(--mono)' }}>{label}</div>
    <input
      value={value}
      readOnly={readOnly}
      onChange={e => onChange?.(e.target.value)}
      placeholder={placeholder}
      style={{
        width: w, height: 28,
        background: 'var(--bg-deep)', border: '1px solid var(--rule-2)',
        borderRadius: 5, padding: '0 8px',
        fontFamily: 'var(--mono)', fontSize: 11,
        color: readOnly ? 'var(--ink-4)' : 'var(--ink)',
        boxShadow: 'var(--shadow-inset)', outline: 'none',
      }}
    />
  </div>
)

const PRESETS = [
  { title: 'Asset',   sub: 'Geo + mat + meta',    id: 'asset' },
  { title: 'Rig',     sub: 'SkelRoot + weights',   id: 'rig' },
  { title: 'Anim',    sub: 'SkelAnim + cache',     id: 'anim' },
  { title: 'LookDev', sub: 'Matériaux + shaders',  id: 'lookdev' },
  { title: 'Layout',  sub: 'Xforms + références',  id: 'layout' },
  { title: 'Full',    sub: 'Tout inclure',          id: 'full' },
]

const CLASS_TOKENS = ['CHAR', 'PROPS', 'ENV', 'CFXRIG', 'FXRIG']

export function Publisher() {
  const { settings } = useSettings()
  const [dcc, setDcc]               = useState('Maya')
  const [preset, setPreset]         = useState('asset')
  const [projects, setProjects]     = useState<string[]>([])
  const [project, setProject]       = useState('')
  const [classToken, setClassToken] = useState('CHAR')
  const [typeName, setTypeName]     = useState('')
  const [assetName, setAssetName]   = useState('')
  const [instance, setInstance]     = useState('')
  const [sourcePath, setSourcePath] = useState('')
  const [description, setDescription] = useState('')
  const [publishing, setPublishing] = useState(false)
  const [result, setResult]         = useState<{ ok: boolean; msg: string } | null>(null)

  // Houdini mode state
  const [ropNodePath, setRopNodePath]   = useState('')
  const [houdiniExt, setHoudiniExt]     = useState('.abc')
  const [isSequence, setIsSequence]     = useState(false)
  const [frameStart, setFrameStart]     = useState(1)
  const [frameEnd, setFrameEnd]         = useState(100)
  const [frameStep, setFrameStep]       = useState(1)
  const [houdiniConnected, setHoudiniConnected]   = useState(false)
  const [houdiniVersion, setHoudiniVersion]       = useState<string | null>(null)

  useEffect(() => {
    api.getProjects()
      .then(d => {
        setProjects(d.projects)
        if (d.projects.length > 0) setProject(d.projects[0])
      })
      .catch(() => {})
  }, [])

  // Poll Houdini state when in Houdini mode
  useEffect(() => {
    if (dcc !== 'Houdini') return
    let cancelled = false
    const poll = async () => {
      try {
        const ping = await api.pingDcc('houdini')
        if (cancelled) return
        setHoudiniConnected(ping.connected)
        setHoudiniVersion(ping.version)
        if (ping.connected) {
          const state = await api.getHoudiniState()
          if (!cancelled && state.selected_nodes?.length > 0)
            setRopNodePath(state.selected_nodes[0])
        }
      } catch { /* Houdini offline */ }
    }
    void poll()
    const id = setInterval(() => void poll(), 3000)
    return () => { cancelled = true; clearInterval(id) }
  }, [dcc])

  const reset = useCallback(() => {
    setClassToken('CHAR')
    setTypeName('')
    setAssetName('')
    setInstance('')
    setSourcePath('')
    setDescription('')
    setResult(null)
  }, [])

  const handlePublish = useCallback(async () => {
    if (!project) { setResult({ ok: false, msg: 'Sélectionne un projet' }); return }

    setPublishing(true)
    setResult(null)

    // filename = CLASS_TYPE_NAME[_instance] — instance optional
    const instancePart = instance.trim() ? `_${instance.trim()}` : ''
    const filename = `${classToken}_${typeName}_${assetName}${instancePart}`

    try {
      if (dcc === 'Houdini') {
        if (!typeName || !assetName) {
          setResult({ ok: false, msg: 'Remplis Type et Name' })
          setPublishing(false)
          return
        }
        const res = await api.publishHoudiniRop({
          project_name:  project,
          filename,
          extension:     houdiniExt,
          rop_node_path: ropNodePath || undefined,
          is_sequence:   isSequence,
          frame_range:   isSequence ? [frameStart, frameEnd, frameStep] : undefined,
          description:   description || undefined,
          user:          settings?.username ?? undefined,
        })
        setResult({ ok: true, msg: `v${res.version_str} → ${res.rop_node}` })
      } else {
        if (!sourcePath.trim()) {
          setResult({ ok: false, msg: 'Indique le fichier source' })
          setPublishing(false)
          return
        }
        const res = await api.publish({
          source_path:  sourcePath,
          project_name: project,
          description:  description || undefined,
          user:         settings?.username ?? undefined,
        })
        setResult({ ok: res.success, msg: res.message })
      }
    } catch (e) {
      setResult({ ok: false, msg: e instanceof Error ? e.message : 'Erreur inconnue' })
    } finally {
      setPublishing(false)
    }
  }, [dcc, project, sourcePath, description, settings?.username, classToken, typeName, assetName,
      instance, houdiniExt, ropNodePath, isSequence, frameStart, frameEnd, frameStep])

  const selectStyle: React.CSSProperties = {
    height: 28, background: 'var(--bg-deep)', border: '1px solid var(--rule-2)',
    borderRadius: 5, padding: '0 24px 0 8px',
    fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink)',
    boxShadow: 'var(--shadow-inset)', appearance: 'none', cursor: 'pointer', outline: 'none',
  }

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>

      <div style={{ padding: '12px 20px', borderBottom: '1px solid var(--rule)', display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.1em', color: 'var(--ink)' }}>Publish Asset</div>
        <div style={{ flex: 1 }} />
        <Btn kbd sm>Ctrl+P</Btn>
      </div>

      <SoftwareSelector active={dcc} onChange={setDcc} />

      <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>

        {/* ── gauche : token + description ── */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', borderRight: '1px solid var(--rule)', minWidth: 0, overflow: 'hidden' }}>

          <div style={{ flex: 1, padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 14, overflowY: 'auto', minHeight: 0 }}>

            {/* projet + mode */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <div className="cap">PROJET</div>
              <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
                <span style={{ position: 'absolute', left: 8, pointerEvents: 'none', display: 'flex' }}>
                  <FolderIcon color="var(--accent)" />
                </span>
                <select value={project} onChange={e => setProject(e.target.value)} style={{ ...selectStyle, width: 200, paddingLeft: 26 }}>
                  {projects.length === 0
                    ? <option value="">Aucun projet</option>
                    : projects.map(p => <option key={p} value={p}>{p}</option>)
                  }
                </select>
                <ChevronDown size={11} strokeWidth={2} color="var(--ink-3)" style={{ position: 'absolute', right: 7, pointerEvents: 'none' }} />
              </div>
              <div style={{ display: 'flex', alignItems: 'center', border: '1px solid var(--rule-2)', fontFamily: 'var(--mono)', fontSize: 10, overflow: 'hidden', borderRadius: 6, boxShadow: 'var(--shadow-xs)' }}>
                <div style={{ padding: '3px 9px', background: 'var(--accent-soft)', color: 'var(--accent-hi)', fontWeight: 600, borderRight: '1px solid var(--accent)' }}>Asset</div>
                <div style={{ padding: '3px 9px', color: 'var(--ink-3)' }}>Shot</div>
              </div>
            </div>

            <FileBadge classToken={classToken} typeName={typeName} assetName={assetName} instance={instance} />

            <div style={{ marginTop: 4 }}>
              {/* Class */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 9 }}>
                <div style={{ width: 96, textAlign: 'right', color: 'var(--ink-3)', fontSize: 11, fontFamily: 'var(--mono)' }}>Class :</div>
                <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
                  <select value={classToken} onChange={e => setClassToken(e.target.value)} style={{ ...selectStyle, width: 120 }}>
                    {CLASS_TOKENS.map(t => <option key={t} value={t}>{t}</option>)}
                  </select>
                  <ChevronDown size={11} strokeWidth={2} color="var(--ink-3)" style={{ position: 'absolute', right: 7, pointerEvents: 'none' }} />
                </div>
              </div>
              <InputRow label="Type :"     value={typeName}  onChange={setTypeName}  placeholder="ex: Rig" />
              <InputRow label="Name :"     value={assetName} onChange={setAssetName} placeholder="ex: HorseBody" />
              <InputRow label="Instance :" value={instance}  onChange={setInstance}  placeholder="ex: moustache  (optionnel)" />
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
                <div style={{ width: 96, textAlign: 'right', fontSize: 9, fontFamily: 'var(--mono)', color: 'var(--ink-4)', letterSpacing: '0.06em' }}>PUBLIÉ PAR</div>
                <div style={{ fontSize: 10, fontFamily: 'var(--mono)', color: 'var(--ink-3)' }}>
                  {settings?.username ?? '—'}
                </div>
              </div>
            </div>

            {/* source / ROP — conditionnel selon DCC */}
            {dcc === 'Houdini' ? (
              <div>
                <div className="cap" style={{ marginBottom: 6 }}>NODE ROP</div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 7 }}>
                  <div style={{
                    width: 7, height: 7, borderRadius: '50%', flexShrink: 0,
                    background: houdiniConnected ? 'var(--ok)' : 'var(--err)',
                  }} />
                  <div style={{ fontSize: 10, fontFamily: 'var(--mono)', color: 'var(--ink-3)' }}>
                    {houdiniConnected
                      ? `Connecté${houdiniVersion ? ` — Houdini ${houdiniVersion}` : ''}`
                      : 'Houdini non connecté — lance le serveur FLUX dans Houdini'}
                  </div>
                </div>
                <input
                  value={ropNodePath}
                  onChange={e => setRopNodePath(e.target.value)}
                  placeholder="/out/rop_alembic1  (auto-rempli depuis la sélection)"
                  style={{
                    width: '100%', height: 28,
                    background: 'var(--bg-deep)', border: '1px solid var(--rule-2)',
                    borderRadius: 5, padding: '0 8px',
                    fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink)',
                    boxShadow: 'var(--shadow-inset)', outline: 'none',
                  }}
                />
              </div>
            ) : (
              <div>
                <div className="cap" style={{ marginBottom: 6 }}>FICHIER SOURCE</div>
                <input
                  value={sourcePath}
                  onChange={e => setSourcePath(e.target.value)}
                  placeholder="Colle le chemin du fichier à publier…"
                  style={{
                    width: '100%', height: 28,
                    background: 'var(--bg-deep)', border: '1px solid var(--rule-2)',
                    borderRadius: 5, padding: '0 8px',
                    fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink)',
                    boxShadow: 'var(--shadow-inset)', outline: 'none',
                  }}
                />
              </div>
            )}
          </div>

          {/* description + résultat */}
          <div style={{ padding: '0 20px 16px', flexShrink: 0 }}>
            <SecTitle>Description</SecTitle>
            <textarea
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="Décris la modification effectuée…"
              style={{
                width: '100%', height: 90, resize: 'none',
                background: 'var(--paper-2)', border: '1px solid var(--rule-2)',
                borderRadius: 6, padding: '10px 12px',
                fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-3)',
                fontStyle: 'italic', outline: 'none',
                boxShadow: 'var(--shadow-inset)',
              }}
            />
            {result && (
              <div style={{ marginTop: 6, fontSize: 11, fontFamily: 'var(--mono)', color: result.ok ? 'var(--ok)' : 'var(--err)' }}>
                {result.ok ? '✓ ' : '✗ '}{result.msg}
              </div>
            )}
          </div>
        </div>

        {/* ── droite : presets / houdini format ── */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, overflow: 'hidden' }}>

          {dcc === 'Houdini' ? (<>
            {/* FORMAT */}
            <div style={{ padding: '16px 20px 12px', flexShrink: 0 }}>
              <SecTitle>FORMAT</SecTitle>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {['.abc', '.bgeo', '.usd', '.obj', '.hip'].map(ext => (
                  <div key={ext} onClick={() => setHoudiniExt(ext)} style={{
                    padding: '5px 10px', borderRadius: 6, cursor: 'pointer', fontSize: 11,
                    fontFamily: 'var(--mono)', fontWeight: houdiniExt === ext ? 600 : 400,
                    border: houdiniExt === ext ? '1px solid var(--accent)' : '1px solid var(--rule-2)',
                    background: houdiniExt === ext ? 'var(--accent-soft)' : 'var(--paper-2)',
                    color: houdiniExt === ext ? 'var(--accent-hi)' : 'var(--ink-3)',
                    transition: 'all 0.1s',
                  }}>{ext}</div>
                ))}
              </div>
            </div>

            {/* SEQUENCE */}
            <div style={{ padding: '0 20px 12px', flexShrink: 0 }}>
              <SecTitle>SÉQUENCE ANIMÉE</SecTitle>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: isSequence ? 10 : 0 }}>
                <div onClick={() => setIsSequence(v => !v)} style={{
                  width: 32, height: 18, borderRadius: 9, cursor: 'pointer', flexShrink: 0,
                  background: isSequence ? 'var(--accent)' : 'var(--rule-2)',
                  position: 'relative', transition: 'background 0.15s',
                }}>
                  <div style={{
                    position: 'absolute', top: 2, left: isSequence ? 16 : 2,
                    width: 14, height: 14, borderRadius: '50%', background: 'white',
                    transition: 'left 0.15s', boxShadow: '0 1px 3px rgba(0,0,0,.3)',
                  }} />
                </div>
                <div style={{ fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--ink-3)' }}>
                  {isSequence ? 'Activé — dossier versionné + $F4' : 'Désactivé — fichier unique LAST'}
                </div>
              </div>
              {isSequence && (
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  {([['Start', frameStart, setFrameStart], ['End', frameEnd, setFrameEnd], ['Step', frameStep, setFrameStep]] as const).map(([lbl, val, set]) => (
                    <div key={lbl} style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                      <div style={{ fontSize: 9, color: 'var(--ink-4)', fontFamily: 'var(--mono)', textTransform: 'uppercase' }}>{lbl}</div>
                      <input type="number" value={val} onChange={e => set(Number(e.target.value))} style={{
                        width: 56, height: 26, background: 'var(--bg-deep)', border: '1px solid var(--rule-2)',
                        borderRadius: 5, padding: '0 6px', fontFamily: 'var(--mono)', fontSize: 11,
                        color: 'var(--ink)', boxShadow: 'var(--shadow-inset)', outline: 'none',
                      }} />
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* OUTPUT PREVIEW */}
            <div style={{ flex: 1, padding: '0 20px 16px', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
              <SecTitle>APERÇU OUTPUT</SecTitle>
              <div className="subcard" style={{ flex: 1, padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 4, minHeight: 0, overflowY: 'auto' }}>
                {(() => {
                  const parts = [classToken, typeName || '…', assetName || '…']
                  if (instance.trim()) parts.push(instance.trim())
                  const base = parts.join('_')
                  if (isSequence) return (<>
                    <div style={{ fontSize: 10, fontFamily: 'var(--mono)', color: 'var(--ink-3)' }}>{base}_v001/</div>
                    <div style={{ fontSize: 10, fontFamily: 'var(--mono)', color: 'var(--ink)', paddingLeft: 12 }}>
                      {base}_v001.$F4{houdiniExt}
                    </div>
                  </>)
                  return (
                    <div style={{ fontSize: 10, fontFamily: 'var(--mono)', color: 'var(--ink)' }}>
                      {base}_LAST{houdiniExt}
                    </div>
                  )
                })()}
                {ropNodePath && (
                  <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid var(--rule)', fontSize: 9, fontFamily: 'var(--mono)', color: 'var(--ink-4)' }}>
                    ROP : {ropNodePath}
                  </div>
                )}
              </div>
            </div>
          </>) : (<>
            <div style={{ padding: '16px 20px 12px', flexShrink: 0 }}>
              <SecTitle>PRESET D'EXPORT</SecTitle>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 7 }}>
                {PRESETS.map(p => (
                  <PresetBtn key={p.id} title={p.title} sub={p.sub} active={preset === p.id} onClick={() => setPreset(p.id)} />
                ))}
              </div>
            </div>

            <div style={{ flex: 1, padding: '0 20px 16px', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
              <SecTitle>APERÇU USD</SecTitle>
              <div className="subcard" style={{ flex: 1, padding: '10px 12px', display: 'flex', flexDirection: 'column', minHeight: 0, overflowY: 'auto' }}>
                <UsdTreeRow depth={0} glyph="◈" label={assetName || 'Asset'} color="var(--ink)" />
                <UsdTreeRow depth={1} glyph="◇" label="Geo" last={false} />
                <UsdTreeRow depth={2} glyph="·" label="Body_Mesh" last />
                <UsdTreeRow depth={1} glyph="◇" label="SkelRoot" last={false} />
                <UsdTreeRow depth={2} glyph="·" label="Skeleton" last />
                <UsdTreeRow depth={1} glyph="◇" label="Materials" last />
                <div style={{ flex: 1 }} />
                <div style={{ marginTop: 10, paddingTop: 8, borderTop: '1px solid var(--rule)', display: 'flex', gap: 8, justifyContent: 'space-between', alignItems: 'center' }}>
                  <div className="lbl">Format : USDA</div>
                  <div className="lbl">Preset : <span style={{ color: 'var(--accent-hi)' }}>{preset}</span></div>
                </div>
              </div>
            </div>
          </>)}
        </div>
      </div>

      <div style={{ borderTop: '1px solid var(--rule)', padding: '9px 20px', display: 'flex', gap: 8, justifyContent: 'flex-end', flexShrink: 0 }}>
        <Btn ghost onClick={reset}>Réinitialiser</Btn>
        <Btn primary onClick={() => void handlePublish()}>
          {publishing ? 'Publication…' : 'Publish →'}
        </Btn>
      </div>
    </div>
  )
}
