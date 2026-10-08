import { useState, useEffect, useCallback, useRef } from 'react'
import { SendHorizonal } from 'lucide-react'
import { useActivity }  from '../hooks/useActivity'
import { useSettings }  from '../hooks/useSettings'
import { useProject }   from '../ProjectContext'
import { Avatar, Tag } from '../components/shared/ui'
import { api } from '../api/client'
import { HUB_CHAT_POLL_INTERVAL_MS } from '../lib/pollIntervals'
import { useI18n } from '../i18n'


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


export function Hub() {
  const { t }         = useI18n()
  const { events }    = useActivity()
  const { settings }  = useSettings()
  const user          = settings?.username ?? 'User'
  const { project }   = useProject()
  // Latest active project, so a chat poll answered after a project switch is dropped.
  const projectRef    = useRef(project)
  projectRef.current  = project

  const [chatMessages, setChatMessages] = useState<{ who: string; h: string; msg: string }[]>([])
  const [chatUsers, setChatUsers]       = useState<string[]>([])
  const [chatInput, setChatInput]       = useState('')
  // @mention autocomplete state
  const [mentionQuery, setMentionQuery] = useState<string | null>(null)
  const [mentionIdx, setMentionIdx]     = useState(0)

  // Each project has its own team chat: reload (and clear) when the project changes.
  const loadChat = useCallback(async () => {
    if (!project) { setChatMessages([]); return }
    try {
      const data = await api.getChat(project, 20)
      if (projectRef.current !== project) return
      setChatUsers(data.users)
      setChatMessages(data.messages.map(m => ({ who: m.user, h: m.time, msg: m.message })))
    } catch {}
  }, [project])

  useEffect(() => { setChatMessages([]) }, [project])

  useEffect(() => {
    void loadChat()
    const id = setInterval(() => { void loadChat() }, HUB_CHAT_POLL_INTERVAL_MS)
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
    if (!chatInput.trim() || !project) return
    const msg = chatInput
    setChatInput('')
    setMentionQuery(null)
    try {
      await api.sendChat(project, msg, user)
      await loadChat()
    } catch {}
  }, [chatInput, user, project, loadChat])

  const activityRows = events.slice(0, 40).map(e => ({ name: e.file ?? e.action, who: e.user, h: e.time, t: e.action, v: '' }))

  const now     = new Date()
  const dateStr = now.toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long' })


  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>

      {/* header: one line */}
      <div style={{ padding: '14px 22px 12px', borderBottom: '1px solid var(--rule)', flexShrink: 0, display: 'flex', alignItems: 'baseline', gap: 12 }}>
        <div style={{ fontSize: 17, fontWeight: 600, color: 'var(--ink)' }}>
          {t('hub.hello')}, <span style={{ color: 'var(--accent-hi)' }}>{user}</span>
        </div>
        <div style={{ fontSize: 11, color: 'var(--ink-3)', textTransform: 'capitalize' }}>{dateStr}</div>
      </div>

      {/* body */}
      <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>

        {/* ── activité | chat (the shortcut grid repeated the sidebar, ADR 0044) ── */}
        <div style={{ flex: 1, display: 'flex', minHeight: 0, minWidth: 0 }}>

          {/* activité récente */}
          <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', minHeight: 0, borderRight: '1px solid var(--rule)' }}>
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

          {/* chat */}
          <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', minHeight: 0, background: 'var(--paper-2)' }}>
            <div style={{ padding: '7px 14px', borderBottom: '1px solid var(--rule)', display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
              <div className="cap">{t('hub.teamChat')}</div>
              {project && <span className="lbl" style={{ color: 'var(--ink-3)' }}>{project}</span>}
            </div>
            <div style={{ flex: 1, padding: '10px 14px', display: 'flex', flexDirection: 'column', gap: 10, overflowY: 'auto', minHeight: 0 }}>
              {chatMessages.length === 0 && (
                <div style={{ fontSize: 11, color: 'var(--ink-4)', fontFamily: 'var(--mono)' }}>
                  {project ? t('hub.noMessage') : t('hub.chatNoProject')}
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
                disabled={!project}
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

      </div>
    </div>
  )
}
