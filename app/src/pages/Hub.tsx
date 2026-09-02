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
import { useI18n } from '../i18n'
import type { LucideIcon } from 'lucide-react'

const SHORTCUTS: { ic: LucideIcon; titleKey: string; subKey: string; path: string; active?: boolean }[] = [
  { ic: FolderOpen, titleKey: 'nav.folderManager', subKey: 'hub.sc.folderManager', path: '/projects', active: true },
  { ic: Upload,     titleKey: 'nav.publisher',     subKey: 'hub.sc.publisher',     path: '/publisher' },
  { ic: Layers,     titleKey: 'nav.usdAssembler',  subKey: 'hub.sc.usd',           path: '/usd' },
  { ic: BookOpen,   titleKey: 'nav.shelfManager',  subKey: 'hub.sc.shelf',         path: '/shelf' },
  { ic: Activity,   titleKey: 'nav.activity',      subKey: 'hub.sc.activity',      path: '/activity' },
]

// Render chat text with @mentions. Only the mention of the CURRENT user stands out
// (bold accent); mentions of other people render as plain text — you shouldn't see
// everyone else's name in bold orange, only your own ping.
function renderChatText(text: string, currentUser: string) {
  const parts = text.split(/(@\w+)/g)
  return parts.map((part, i) => {
    if (part.startsWith('@') && part.slice(1).toLowerCase() === currentUser.toLowerCase()) {
      return <span key={i} style={{ color: 'var(--accent-hi)', fontWeight: 600 }}>{part}</span>
    }
    return <span key={i}>{part}</span>
  })
}

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
  const { t }         = useI18n()
  const { events }    = useActivity()
  const { settings }  = useSettings()
  const dccStatus     = useDccStatus()
  const user          = settings?.username ?? 'User'

  const [chatMessages, setChatMessages] = useState<{ who: string; h: string; msg: string }[]>([])
  const [chatUsers, setChatUsers]       = useState<string[]>([])
  const [chatInput, setChatInput]       = useState('')
  // @mention autocomplete state
  const [mentionQuery, setMentionQuery] = useState<string | null>(null)
  const [mentionIdx, setMentionIdx]     = useState(0)

  const loadChat = useCallback(async () => {
    try {
      const data = await api.getChat(20)
      setChatUsers(data.users)
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

  // Being on the Hub (where the chat lives) clears the user's @mention badge.
  useEffect(() => {
    void api.markMentionsRead().then(() => window.dispatchEvent(new Event('flux:mentions'))).catch(() => {})
  }, [])

  // Users matching the current @query (empty query = all), max 6.
  const mentionMatches = mentionQuery === null ? [] : chatUsers
    .filter(u => u.toLowerCase().startsWith(mentionQuery.toLowerCase()) && u !== user)
    .slice(0, 6)

  // Detect a trailing "@partial" token at the caret so we can autocomplete it.
  const onChatInput = (value: string) => {
    setChatInput(value)
    const m = /(?:^|\s)@(\w*)$/.exec(value)
    if (m) { setMentionQuery(m[1]); setMentionIdx(0) }
    else setMentionQuery(null)
  }

  const applyMention = (name: string) => {
    setChatInput(prev => prev.replace(/@(\w*)$/, `@${name} `))
    setMentionQuery(null)
  }

  const sendChat = useCallback(async () => {
    if (!chatInput.trim()) return
    const msg = chatInput
    setChatInput('')
    setMentionQuery(null)
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
          {t('hub.hello')}, <span style={{ color: 'var(--accent-hi)' }}>{user}</span>
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
            <div style={{ padding: '10px 16px 6px', flexShrink: 0 }}><div className="cap">{t('hub.recentActivity')}</div></div>
            <div style={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>
              {activityRows.length === 0 && (
                <div style={{ padding: '10px 16px', fontSize: 11, color: 'var(--ink-4)', fontFamily: 'var(--mono)' }}>
                  {t('hub.noRecentActivity')}
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
              <div className="cap">{t('hub.teamChat')}</div>
            </div>
            <div style={{ flex: 1, padding: '10px 14px', display: 'flex', flexDirection: 'column', gap: 10, overflowY: 'auto', minHeight: 0 }}>
              {chatMessages.length === 0 && (
                <div style={{ fontSize: 11, color: 'var(--ink-4)', fontFamily: 'var(--mono)' }}>
                  {t('hub.noMessage')}
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
                    <div style={{ fontSize: 11, color: 'var(--ink-2)', marginTop: 2, lineHeight: 1.4 }}>{renderChatText(m.msg, user)}</div>
                  </div>
                </div>
              ))}
            </div>
            <div style={{ padding: '8px 10px', borderTop: '1px solid var(--rule)', display: 'flex', gap: 6, flexShrink: 0, position: 'relative' }}>
              {/* @mention autocomplete dropdown */}
              {mentionQuery !== null && mentionMatches.length > 0 && (
                <div style={{
                  position: 'absolute', bottom: 'calc(100% + 4px)', left: 10, minWidth: 160,
                  background: 'var(--paper)', border: '1px solid var(--rule-2)', borderRadius: 7,
                  boxShadow: 'var(--shadow-md)', overflow: 'hidden', zIndex: 20,
                }}>
                  {mentionMatches.map((u, i) => (
                    <div
                      key={u}
                      onMouseDown={e => { e.preventDefault(); applyMention(u) }}
                      onMouseEnter={() => setMentionIdx(i)}
                      style={{
                        display: 'flex', alignItems: 'center', gap: 6, padding: '6px 10px',
                        cursor: 'pointer', fontSize: 11,
                        background: i === mentionIdx ? 'var(--accent-soft)' : 'transparent',
                        color: i === mentionIdx ? 'var(--accent-hi)' : 'var(--ink-2)',
                      }}
                    >
                      <Avatar ch={u[0]?.toUpperCase() ?? '?'} size={16} />
                      {u}
                    </div>
                  ))}
                </div>
              )}
              <input
                value={chatInput}
                onChange={e => onChatInput(e.target.value)}
                onKeyDown={e => {
                  if (mentionQuery !== null && mentionMatches.length > 0) {
                    if (e.key === 'ArrowDown') { e.preventDefault(); setMentionIdx(i => (i + 1) % mentionMatches.length); return }
                    if (e.key === 'ArrowUp')   { e.preventDefault(); setMentionIdx(i => (i - 1 + mentionMatches.length) % mentionMatches.length); return }
                    if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); applyMention(mentionMatches[mentionIdx]); return }
                    if (e.key === 'Escape')    { setMentionQuery(null); return }
                  }
                  if (e.key === 'Enter') void sendChat()
                }}
                placeholder={t('hub.messagePlaceholder')}
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
            <div style={{ marginBottom: 8 }}><div className="cap">{t('hub.shortcuts')}</div></div>
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
                    <div style={{ fontSize: 12, fontWeight: 600, color: c.active ? 'var(--ink)' : 'var(--ink-2)' }}>{t(c.titleKey)}</div>
                    <div className="lbl" style={{ marginTop: -2 }}>{t(c.subKey)}</div>
                  </div>
                )
              })}
            </div>
          </div>

          {/* DCC status */}
          <div style={{ padding: '10px 16px 16px', flexShrink: 0 }}>
            <div style={{ marginBottom: 8 }}><div className="cap">{t('hub.dccConnection')}</div></div>
            <div className="card" style={{ padding: '4px 0' }}>
              {dccItems.length === 0
                ? <div style={{ padding: '10px 12px', fontSize: 11, color: 'var(--ink-4)', fontFamily: 'var(--mono)' }}>
                    {t('hub.noDcc')}
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
