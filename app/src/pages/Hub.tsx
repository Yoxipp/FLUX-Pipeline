import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Upload, BookOpen, FolderOpen, Activity, SendHorizonal, Layers,
} from 'lucide-react'
import { useActivity }  from '../hooks/useActivity'
import { useSettings }  from '../hooks/useSettings'
import { useDccStatus } from '../hooks/useDccStatus'
import { Avatar, Tag } from '../components/shared/ui'
import { api } from '../api/client'
import type { LucideIcon } from 'lucide-react'

const SHORTCUTS: { ic: LucideIcon; t: string; s: string; path: string; active?: boolean }[] = [
  { ic: FolderOpen, t: 'Folder Manager', s: 'Naviguer & importer', path: '/projects', active: true },
  { ic: Upload,     t: 'Publisher',      s: 'Exporter un asset',   path: '/publisher' },
  { ic: Layers,     t: 'USD Assembler',  s: 'Composer des layers', path: '/usd' },
  { ic: BookOpen,   t: 'Shelf Manager',  s: 'Installer / màj',     path: '/shelf' },
  { ic: Activity,   t: 'Activité',       s: 'Historique équipe',   path: '/activity' },
]

const DCC_STATUS_ITEMS = [
  { name: 'Maya',               key: 'Maya' },
  { name: 'Houdini',            key: 'Houdini' },
  { name: 'Nuke',               key: 'Nuke' },
  { name: 'Substance Painter',  key: 'SubstanceP' },
  { name: 'Substance Designer', key: 'SubstanceD' },
  { name: 'ZBrush',             key: 'ZBrush' },
  { name: 'Marvelous Designer', key: 'Marvelous' },
  { name: 'Photoshop',          key: 'Photoshop' },
]

export function Hub() {
  const navigate      = useNavigate()
  const { events }    = useActivity()
  const { settings }  = useSettings()
  const dccStatus     = useDccStatus()
  const user          = settings?.username ?? 'User'

  const [chatMessages, setChatMessages] = useState<{ who: string; h: string; msg: string }[]>([])
  const [chatInput, setChatInput]       = useState('')

  const loadChat = useCallback(async () => {
    try {
      const data = await api.getChat(20)
      if (data.messages.length > 0) {
        setChatMessages(data.messages.map(m => ({ who: m.user, h: m.time, msg: m.message })))
      }
    } catch {}
  }, [])

  useEffect(() => {
    void loadChat()
    const id = setInterval(() => { void loadChat() }, 10_000)
    return () => clearInterval(id)
  }, [loadChat])

  const sendChat = useCallback(async () => {
    if (!chatInput.trim()) return
    const msg = chatInput
    setChatInput('')
    try {
      await api.sendChat(msg, user)
      await loadChat()
    } catch {}
  }, [chatInput, user, loadChat])

  const activityRows = events.slice(0, 4).map(e => ({ name: e.file ?? e.action, who: e.user, h: e.time, t: e.action, v: '' }))

  const now     = new Date()
  const dateStr = now.toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long' })
  const timeStr = now.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })

  const dccItems = DCC_STATUS_ITEMS
    .map(d => ({ name: d.name, connected: dccStatus[d.key]?.connected ?? false }))
    .filter(d => d.connected)

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>

      {/* header */}
      <div style={{ padding: '16px 22px 14px', borderBottom: '1px solid var(--rule)', flexShrink: 0 }}>
        <div style={{ fontSize: 18, fontWeight: 600, color: 'var(--ink)' }}>
          Bonjour, <span style={{ color: 'var(--accent-hi)' }}>{user}</span>
        </div>
        <div style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink-3)', marginTop: 4 }}>
          {dateStr} · {timeStr}
        </div>
      </div>

      {/* body */}
      <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>

        {/* ── colonne gauche : activité + chat ── */}
        <div style={{ flex: 1, borderRight: '1px solid var(--rule)', display: 'flex', flexDirection: 'column', minHeight: 0 }}>

          {/* activité récente — 40% */}
          <div style={{ flex: '0 0 40%', display: 'flex', flexDirection: 'column', minHeight: 0, borderBottom: '1px solid var(--rule)' }}>
            <div style={{ padding: '10px 16px 6px', flexShrink: 0 }}><div className="cap">ACTIVITÉ RÉCENTE</div></div>
            <div style={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>
              {activityRows.length === 0 && (
                <div style={{ padding: '10px 16px', fontSize: 11, color: 'var(--ink-4)', fontFamily: 'var(--mono)' }}>
                  Aucune activité récente
                </div>
              )}
              {activityRows.map((r, i) => (
                <div key={i} className="row" style={{ padding: '8px 16px' }}>
                  <div style={{ width: 7, height: 7, borderRadius: 3, background: 'var(--accent-soft)', border: '1px solid var(--accent)', flexShrink: 0 }} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.name}</div>
                    <div className="lbl" style={{ marginTop: 2 }}>{r.who} · <span style={{ color: 'var(--ink-3)' }}>{r.h}</span>{r.t ? ` · ${r.t}` : ''}</div>
                  </div>
                  {r.v && <Tag kind="ver">{r.v}</Tag>}
                </div>
              ))}
            </div>
          </div>

          {/* chat — 60% */}
          <div style={{ flex: '0 0 60%', display: 'flex', flexDirection: 'column', minHeight: 0, background: 'var(--paper-2)' }}>
            <div style={{ padding: '7px 14px', borderBottom: '1px solid var(--rule)', display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
              <div style={{ width: 14, height: 14, borderRadius: 4, border: '1px solid var(--rule-2)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: 'var(--mono)', fontSize: 8, fontWeight: 700, color: 'var(--ink-2)', boxShadow: 'var(--shadow-xs)' }}>D</div>
              <div className="cap">TEAM CHAT</div>
            </div>
            <div style={{ flex: 1, padding: '10px 14px', display: 'flex', flexDirection: 'column', gap: 10, overflowY: 'auto', minHeight: 0 }}>
              {chatMessages.length === 0 && (
                <div style={{ fontSize: 11, color: 'var(--ink-4)', fontFamily: 'var(--mono)' }}>
                  Aucun message
                </div>
              )}
              {chatMessages.map((m, i) => (
                <div key={i} style={{ display: 'flex', gap: 8 }}>
                  <Avatar ch={m.who[0]} size={20} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', gap: 6, alignItems: 'baseline' }}>
                      <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--ink)' }}>{m.who}</span>
                      <span className="lbl">{m.h}</span>
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--ink-2)', marginTop: 2, lineHeight: 1.4 }}>{m.msg}</div>
                  </div>
                </div>
              ))}
            </div>
            <div style={{ padding: '8px 10px', borderTop: '1px solid var(--rule)', display: 'flex', gap: 6, flexShrink: 0 }}>
              <input
                value={chatInput}
                onChange={e => setChatInput(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') void sendChat() }}
                placeholder="Message…"
                style={{
                  flex: 1, height: 28,
                  background: 'var(--bg-deep)', border: '1px solid var(--rule-2)',
                  borderRadius: 5, padding: '0 8px',
                  fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink)',
                  boxShadow: 'var(--shadow-inset)', outline: 'none',
                }}
              />
              <div
                onClick={() => void sendChat()}
                className="scale-hover"
                style={{
                  width: 28, height: 28, borderRadius: 7,
                  border: '1px solid var(--accent)', background: 'var(--accent-soft)',
                  color: 'var(--accent-hi)', display: 'flex', alignItems: 'center', justifyContent: 'center',
                  cursor: 'pointer', boxShadow: 'var(--shadow-xs)', transition: 'background 0.12s, transform 0.12s',
                }}>
                <SendHorizonal size={13} strokeWidth={2} />
              </div>
            </div>
          </div>
        </div>

        {/* ── colonne droite : raccourcis + DCC status ── */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>

          {/* raccourcis */}
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, padding: '10px 16px 0' }}>
            <div style={{ marginBottom: 8 }}><div className="cap">RACCOURCIS</div></div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, flex: 1, alignContent: 'start' }}>
              {SHORTCUTS.map((c, i) => {
                const Icon = c.ic
                return (
                  <div
                    key={i}
                    onClick={() => navigate(c.path)}
                    className="scale-hover"
                    style={{
                      border: c.active ? '1px solid var(--accent)' : '1px solid var(--rule-2)',
                      padding: '14px 12px', minHeight: 88,
                      background: c.active ? 'var(--accent-soft)' : 'var(--paper-2)',
                      display: 'flex', flexDirection: 'column', gap: 8,
                      borderRadius: 8, cursor: 'pointer',
                      boxShadow: 'var(--shadow-sm)',
                      transition: 'border-color 0.12s, background 0.12s, transform 0.12s',
                    }}
                  >
                    <div style={{
                      width: 28, height: 28, borderRadius: 6,
                      background: c.active ? 'color-mix(in oklch, var(--accent) 20%, transparent)' : 'var(--paper)',
                      border: '1px solid ' + (c.active ? 'var(--accent)' : 'var(--rule-2)'),
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      color: c.active ? 'var(--accent-hi)' : 'var(--ink-3)',
                      boxShadow: 'var(--shadow-xs)',
                    }}>
                      <Icon size={14} strokeWidth={1.75} />
                    </div>
                    <div style={{ fontSize: 12, fontWeight: 600, color: c.active ? 'var(--ink)' : 'var(--ink-2)' }}>{c.t}</div>
                    <div className="lbl" style={{ marginTop: -2 }}>{c.s}</div>
                  </div>
                )
              })}
            </div>
          </div>

          {/* DCC status */}
          <div style={{ padding: '10px 16px 16px', flexShrink: 0 }}>
            <div style={{ marginBottom: 8 }}><div className="cap">CONNEXION DCC</div></div>
            <div className="card" style={{ padding: '4px 0' }}>
              {dccItems.length === 0
                ? <div style={{ padding: '10px 12px', fontSize: 11, color: 'var(--ink-4)', fontFamily: 'var(--mono)' }}>
                    Aucun DCC connecté
                  </div>
                : dccItems.map((d, i) => (
                    <div key={i} style={{
                      display: 'flex', alignItems: 'center', gap: 10,
                      padding: '7px 12px',
                      borderBottom: i < dccItems.length - 1 ? '1px solid var(--rule)' : 'none',
                    }}>
                      <span className="dot ok" style={{ width: 6, height: 6, flexShrink: 0 }} />
                      <span style={{ flex: 1, fontSize: 11, color: 'var(--ink)', fontFamily: 'var(--mono)' }}>{d.name}</span>
                      <span style={{ fontSize: 10, color: 'var(--ok)', fontFamily: 'var(--mono)' }}>connecté</span>
                    </div>
                  ))
              }
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
