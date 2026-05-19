import { useState } from 'react'
import { Upload, Download, FolderOpen, Zap, RefreshCw, CheckCircle2, XCircle, ArrowRight, Trash2 } from 'lucide-react'
import { SoftwareSelector } from '../components/shared/SoftwareSelector'
import { Btn, SecTitle, Pill } from '../components/shared/ui'
import type { LucideIcon } from 'lucide-react'

const ShelfBtn = ({ icon: Icon, label, primary }: { icon: LucideIcon; label: string; primary?: boolean }) => (
  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 5 }}>
    <div style={{
      width: 40, height: 40, borderRadius: 9,
      border: primary ? '1px solid var(--accent)' : '1px solid var(--rule-2)',
      background: primary ? 'var(--accent-soft)' : 'var(--paper)',
      color: primary ? 'var(--accent-hi)' : 'var(--ink-3)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      boxShadow: primary ? 'var(--shadow-sm), 0 0 8px color-mix(in oklch, var(--accent) 18%, transparent)' : 'var(--shadow-sm)',
      transition: 'box-shadow 0.12s',
    }}>
      <Icon size={16} strokeWidth={1.75} />
    </div>
    <div className="lbl" style={{ fontSize: 9 }}>{label}</div>
  </div>
)

const VERSIONS = ['2024', '2025', '2025.3']

const LOG_ENTRIES = [
  { type: 'ok',   msg: 'Shelf détecté dans Maya 2025.3' },
  { type: 'ok',   msg: 'Connexion Maya OK' },
  { type: 'err',  msg: 'Nuke non connecté' },
  { type: 'info', msg: 'Retry dans 5s…' },
  { type: 'ok',   msg: 'Houdini 20.5 — shelf chargé' },
  { type: 'info', msg: 'Dernière sync : il y a 2 min' },
]

export function ShelfManager() {
  const [dcc, setDcc] = useState('Maya')
  const [version, setVersion] = useState('2025.3')

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>

      <div style={{ padding: '12px 20px 10px', borderBottom: '1px solid var(--rule)', flexShrink: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)' }}>Gestion du Shelf</div>
      </div>

      <SoftwareSelector active={dcc} onChange={setDcc} />

      {/* body — deux zones : top fixe + log flexible */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, overflow: 'hidden' }}>

        {/* zone supérieure fixe */}
        <div style={{ padding: '16px 20px 0', display: 'flex', flexDirection: 'column', gap: 16, flexShrink: 0 }}>

          {/* version */}
          <div>
            <SecTitle>Version cible</SecTitle>
            <div style={{ display: 'flex', gap: 6 }}>
              {VERSIONS.map(v => (
                <Pill key={v} active={version === v} style={{ cursor: 'pointer' }}>
                  <span onClick={() => setVersion(v)}>{v}</span>
                </Pill>
              ))}
            </div>
          </div>

          {/* aperçu shelf */}
          <div>
            <SecTitle>Aperçu du shelf</SecTitle>
            <div className="card" style={{ padding: '14px 20px', display: 'flex', gap: 20, alignItems: 'flex-start' }}>
              <ShelfBtn icon={Upload}     label="Exporter" primary />
              <ShelfBtn icon={Download}   label="Importer" />
              <ShelfBtn icon={FolderOpen} label="SAZ" />
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
              <Btn primary style={{ flex: 1, height: 32, justifyContent: 'center', gap: 6 }}>
                <Zap size={12} strokeWidth={2} />
                Installer le shelf
              </Btn>
              <Btn ghost style={{ height: 32, gap: 5 }}>
                <RefreshCw size={11} strokeWidth={2} />
                Màj
              </Btn>
              <Btn ghost style={{ height: 32, gap: 5 }}>
                <Trash2 size={11} strokeWidth={2} />
                Retirer
              </Btn>
            </div>
          </div>

        </div>

        {/* log — prend tout l'espace restant */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', padding: '16px 20px 20px', minHeight: 0 }}>
          <SecTitle>Log</SecTitle>
          <div className="card" style={{
            flex: 1, padding: '10px 14px', minHeight: 0, overflowY: 'auto',
            fontFamily: 'var(--mono)', fontSize: 10, lineHeight: 2.0,
            color: 'var(--ink-2)', display: 'flex', flexDirection: 'column', gap: 2,
          }}>
            {LOG_ENTRIES.map((e, i) => {
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
            })}
            <div style={{ flex: 1 }} />
            <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid var(--rule)', color: 'var(--ink-4)', display: 'flex', alignItems: 'center', gap: 6 }}>
              <span className="dot ok" style={{ width: 5, height: 5 }} />
              Shelf actif — {version}
            </div>
          </div>
        </div>

      </div>
    </div>
  )
}
