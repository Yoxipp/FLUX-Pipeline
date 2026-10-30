// ChatWidget.tsx — the Team page chat, Teams-like (ADR 0077): the project team chat (the same
// messages as the home page) by channels, threads, reactions, pinned messages, attached files
// (copied by the backend) and calls by link (no media server, ADR 0062): a channel's call
// link opens in the system browser; "Nouvelle reunion" makes a Jitsi link or opens Meet /
// Teams to paste one, posts it in the channel and can notify everyone's phone.
// Channels, call links and pins: leads. A reaction belongs to its author.

import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent, type KeyboardEvent } from 'react'
import { Archive, Eye, Hash, Lock, MessageSquareReply, Paperclip, Phone, Pin, PinOff, Plus, Send, Video, X } from 'lucide-react'
import { toast } from 'sonner'
import { setMyPresence, teamApi, type TeamAttachment, type TeamEmoji, type TeamMessage, type TeamRecord } from '../../api/team'
import { PresenceDot } from '../../hooks/usePresence'
import { PeoplePanel } from '../../components/shared/PeoplePanel'
import type { PageAccess, PageDataOp } from '../flow_editor/types'
import { AccessPicker, cleanAccess, isEveryone } from './PageAccess'
import { useTr } from '../flow_editor/useTr'
import type { DataWidgetProps } from './DataWidgets'

const GENERAL = 'general'
const REFRESH_MS = 4000
const EMOJI: Record<TeamEmoji, string> = { like: '\u{1F44D}', love: '❤️', laugh: '\u{1F602}', question: '❓', check: '✅' }
const URL_RE = /(https?:\/\/[^\s<>"]+)/g
const fail = (err: unknown) => toast.error((err as Error).message)

export function openLink(url: string) {
  if (!/^https:\/\//.test(url)) { toast.info('Seuls les liens https:// s’ouvrent depuis FLUX.'); return }
  if (window.electronAPI?.openExternal) void window.electronAPI.openExternal(url)
  else window.open(url, '_blank', 'noopener')
}
const chanOf = (m: TeamMessage) => m.channel || GENERAL
const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 24) || 'flux'
const sizeTxt = (n: number) => n > 1 << 20 ? `${(n / (1 << 20)).toFixed(1)} Mo` : `${Math.max(1, Math.round(n / 1024))} Ko`

function Text({ text, users }: { text: string; users: Set<string> }) {
  // Links open in the system browser; @names of real artists stand out.
  const parts = text.split(URL_RE)
  return <>{parts.map((part, i) => i % 2
    ? <a key={i} href={part} onClick={e => { e.preventDefault(); openLink(part) }} style={{ color: 'var(--accent)', wordBreak: 'break-all' }}>{part}</a>
    : part.split(/(@[A-Za-z0-9_.-]+)/g).map((bit, j) => bit.startsWith('@') && users.has(bit.slice(1).toUpperCase())
        ? <b key={`${i}-${j}`} style={{ color: 'var(--accent)' }}>{bit}</b> : <span key={`${i}-${j}`}>{bit}</span>))}</>
}

// Access of a channel record (stored as JSON text), undefined = everyone.
function accessOf(r: TeamRecord | undefined): PageAccess | undefined {
  if (!r?.access) return undefined
  try { const a = JSON.parse(r.access) as PageAccess; return isEveryone(a) ? undefined : a } catch { return undefined }
}
const accessLabel = (a: PageAccess) => [...(a.users ?? []), ...(a.roles ?? []), ...(a.departments ?? [])].join(', ')

// fill: the built-in Team page (/team) shows it at the full height of the window.
export function ChatWidget({ widget: w, project, preview, fill }: DataWidgetProps & { fill?: boolean }) {
  const { tr } = useTr()
  const [messages, setMessages] = useState<TeamMessage[]>([])
  const [users, setUsers] = useState<string[]>([])
  const [records, setRecords] = useState<TeamRecord[]>([])
  const [lead, setLead] = useState(false)
  const [filesDir, setFilesDir] = useState('')
  const [me, setMe] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [channel, setChannel] = useState(() => { try { return localStorage.getItem(`flux.team.channel.${project}`) || GENERAL } catch { return GENERAL } })
  const [thread, setThread] = useState<string | null>(null)
  const [newChannel, setNewChannel] = useState<string | null>(null)
  const [callMenu, setCallMenu] = useState(false)
  const [paste, setPaste] = useState<{ label: string } | null>(null)
  const [notifyAll, setNotifyAll] = useState(true)
  const [linkEdit, setLinkEdit] = useState<string | null>(null)
  const [accessEdit, setAccessEdit] = useState<{ value: PageAccess | undefined } | null>(null)
  const [menu, setMenu] = useState<{ name: string; x: number; y: number } | null>(null)   // right click on a channel (leads)
  useEffect(() => {
    if (!menu) return
    const close = () => setMenu(null)
    const key = (e: globalThis.KeyboardEvent) => { if (e.key === 'Escape') setMenu(null) }
    window.addEventListener('mousedown', close)
    window.addEventListener('keydown', key)
    return () => { window.removeEventListener('mousedown', close); window.removeEventListener('keydown', key) }
  }, [menu])
  const etag = useRef<string | undefined>(undefined)
  const listRef = useRef<HTMLDivElement>(null)
  const atBottom = useRef(true)

  const load = useCallback(() => {
    if (!project || preview) return
    teamApi.messages(project).then(r => { setMessages(r.messages); setUsers(r.users); setError(null) }).catch(err => setError((err as Error).message))
    teamApi.meta(project, etag.current).then(r => {
      etag.current = r.etag
      setLead(r.lead)
      setFilesDir(r.files_dir)
      if (!r.unchanged) setRecords(r.records)
    }).catch(() => undefined)
  }, [project, preview])
  useEffect(() => {
    etag.current = undefined
    setMessages([]); setRecords([])
    load()
    const t = setInterval(load, REFRESH_MS)
    return () => clearInterval(t)
  }, [load])
  useEffect(() => {
    import('../../api/flows').then(m => m.flowsApi.getRights()).then(r => setMe(r.user ?? '')).catch(() => setMe(''))
  }, [])
  useEffect(() => { try { if (project) localStorage.setItem(`flux.team.channel.${project}`, channel) } catch { /* private mode */ } }, [channel, project])
  useEffect(() => { const el = listRef.current; if (el && atBottom.current) el.scrollTop = el.scrollHeight }, [messages, channel])

  // -- derived ---------------------------------------------------------------
  const userSet = useMemo(() => new Set(users.map(u => u.toUpperCase())), [users])
  const channels = useMemo(() => {
    const recs = records.filter(r => r.kind === 'channel' && r.name)
    const byName = new Map(recs.map(r => [r.name!, r]))
    const names = [GENERAL, ...[...byName.keys()].filter(n => n !== GENERAL && !byName.get(n)!.archived).sort()]
    return { names, byName, archived: recs.filter(r => r.archived && r.name !== GENERAL) }
  }, [records])
  const current = channels.names.includes(channel) ? channel : GENERAL
  const chanRec = channels.byName.get(current)
  const roots = useMemo(() => messages.filter(m => chanOf(m) === current && !m.reply_to), [messages, current])
  const replies = useMemo(() => {
    const m = new Map<string, TeamMessage[]>()
    for (const msg of messages) if (msg.reply_to) m.set(msg.reply_to, [...(m.get(msg.reply_to) ?? []), msg])
    return m
  }, [messages])
  const reactions = useMemo(() => {
    const m = new Map<string, Map<TeamEmoji, { n: number; mine?: TeamRecord; who: string[] }>>()
    for (const r of records) {
      if (r.kind !== 'reaction' || !r.target || !r.emoji) continue
      const per = m.get(r.target) ?? new Map()
      const x = per.get(r.emoji) ?? { n: 0, who: [] }
      x.n++; x.who.push(r._created_by)
      if (r._created_by === me) x.mine = r
      per.set(r.emoji, x)
      m.set(r.target, per)
    }
    return m
  }, [records, me])
  const pins = useMemo(() => new Map(records.filter(r => r.kind === 'pin' && r.target).map(r => [r.target!, r])), [records])
  const pinned = messages.filter(m => pins.has(m.id) && chanOf(m) === current)
  const unread = useMemo(() => {
    // Messages of the other channels since this viewer last opened them (kept on this machine).
    const out: Record<string, number> = {}
    for (const name of channels.names) {
      let seen = ''
      try { seen = localStorage.getItem(`flux.team.seen.${project}.${name}`) || '' } catch { /* private mode */ }
      out[name] = messages.filter(m => chanOf(m) === name && `${m.date} ${m.time}` > seen && m.user !== me).length
    }
    return out
  }, [messages, channels.names, project, me])
  useEffect(() => {
    const last = roots[roots.length - 1]
    if (last) try { localStorage.setItem(`flux.team.seen.${project}.${current}`, `${last.date} ${last.time}`) } catch { /* private mode */ }
  }, [roots, current, project])

  // -- writes ----------------------------------------------------------------
  const meta = (ops: PageDataOp[]) => project ? teamApi.writeMeta(project, ops).then(load).catch(fail) : undefined
  const send = async (body: { message: string; reply_to?: string; attachments?: TeamAttachment[]; notify_all?: boolean }) => {
    if (!project) return
    await teamApi.send(project, { ...body, channel: current === GENERAL ? undefined : current })
    atBottom.current = true
    load()
  }
  const react = (msg: string, emoji: TeamEmoji) => {
    const mine = reactions.get(msg)?.get(emoji)?.mine
    void meta(mine ? [{ op: 'del', rid: mine.rid }] : [{ op: 'put', fields: { kind: 'reaction', target: msg, emoji } }])
  }
  const togglePin = (msg: string) => {
    const pin = pins.get(msg)
    void meta(pin ? [{ op: 'del', rid: pin.rid }] : [{ op: 'put', fields: { kind: 'pin', target: msg } }])
  }
  const createChannel = (name: string) => {
    const n = name.trim().toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-+/, '').slice(0, 32)
    if (!n) return
    const old = channels.archived.find(r => r.name === n)
    void meta(old ? [{ op: 'put', rid: old.rid, fields: { archived: null } }] : [{ op: 'put', fields: { kind: 'channel', name: n } }])
    setNewChannel(null)
    setChannel(n)
  }
  const saveLink = (url: string) => {
    const link = url.trim() || null
    void meta(chanRec ? [{ op: 'put', rid: chanRec.rid, fields: { call_link: link } }] : [{ op: 'put', fields: { kind: 'channel', name: current, call_link: link } }])
    setLinkEdit(null)
  }
  // Who sees the channel (leads): people, roles, departments, like a TOOL page (ADR 0078).
  const saveAccess = (value: PageAccess | undefined) => {
    const clean = value ? cleanAccess(value) : undefined
    const access = clean ? JSON.stringify(clean) : null
    void meta(chanRec ? [{ op: 'put', rid: chanRec.rid, fields: { access } }] : [{ op: 'put', fields: { kind: 'channel', name: current, access } }])
    setAccessEdit(null)
  }
  const join = (url: string) => { openLink(url); void setMyPresence('meeting') }
  const postCall = (label: string, url: string) => {
    if (!/^https:\/\/\S+$/.test(url)) { toast.error(tr('Colle un lien https://', 'Paste an https:// link')); return }
    setPaste(null); setCallMenu(false)
    send({ message: `\u{1F4DE} ${label} : ${url}`, notify_all: notifyAll }).catch(fail)
  }
  const newMeeting = (kind: 'jitsi' | 'meet' | 'teams') => {
    if (kind === 'jitsi') {
      const url = `https://meet.jit.si/FLUX-${slug(project ?? '')}-${current}-${Math.random().toString(36).slice(2, 8)}`
      postCall(tr('Reunion Jitsi', 'Jitsi meeting'), url)
      join(url)
      return
    }
    openLink(kind === 'meet' ? 'https://meet.google.com/new' : 'https://teams.microsoft.com/l/meeting/new')
    setPaste({ label: kind === 'meet' ? 'Google Meet' : 'Teams' })
  }

  if (!project) return <div className="tp-note" style={{ padding: 12 }}>{tr('Ouvre un projet : le chat est celui de son equipe.', 'Open a project: the chat is its team’s.')}</div>
  if (preview) return <div className="tp-note" style={{ padding: 12 }}>{tr('Apercu : le chat d’equipe du projet s’affiche ici.', 'Preview: the project team chat shows here.')}</div>

  const root = thread ? messages.find(m => m.id === thread) : undefined
  const height = fill ? undefined : w.height ?? 560
  return (
    <div style={{ border: '1px solid var(--rule)', borderRadius: 8, background: 'var(--paper)', display: 'flex', height, overflow: 'hidden', position: 'relative',
                  ...(fill ? { flex: 1, minHeight: 0 } : {}) }}>
      {/* channels */}
      <div style={{ width: 170, flex: 'none', borderRight: '1px solid var(--rule)', display: 'flex', flexDirection: 'column', background: 'var(--paper-2)' }}>
        <div className="cap" style={{ padding: '8px 10px 4px' }}>{w.label || tr('Canaux', 'Channels')}</div>
        <div style={{ flex: 1, overflow: 'auto' }}>
          {channels.names.map(n => (
            <div key={n} onClick={() => { setChannel(n); setThread(null) }}
                 onContextMenu={e => { if (!lead || n === GENERAL) return; e.preventDefault(); setMenu({ name: n, x: e.clientX, y: e.clientY }) }}
                 style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '4px 10px', cursor: 'pointer', fontSize: 12.5,
                          background: n === current ? 'var(--paper)' : undefined, fontWeight: n === current || unread[n] ? 600 : 400 }}>
              {accessOf(channels.byName.get(n)) ? <Lock size={11} style={{ opacity: 0.6 }} /> : <Hash size={12} style={{ opacity: 0.6 }} />}
              <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis' }}>{n}</span>
              {channels.byName.get(n)?.call_link && <Phone size={11} style={{ opacity: 0.6 }} />}
              {n !== current && unread[n] > 0 && <span className="tag" style={{ fontSize: 10 }}>{unread[n]}</span>}
              {lead && n !== GENERAL && n === current && (
                <button type="button" title={tr('Archiver le canal', 'Archive the channel')} onClick={e => { e.stopPropagation(); void meta([{ op: 'put', rid: channels.byName.get(n)!.rid, fields: { archived: true } }]); setChannel(GENERAL) }}
                        style={iconBtn}><Archive size={11} /></button>
              )}
            </div>
          ))}
        </div>
        {lead && (newChannel === null
          ? <button type="button" className="btn ghost sm" style={{ margin: 6 }} onClick={() => setNewChannel('')}><Plus size={12} /> {tr('Canal', 'Channel')}</button>
          : <input autoFocus value={newChannel} placeholder={tr('nom-du-canal', 'channel-name')} onChange={e => setNewChannel(e.target.value)}
                   onKeyDown={e => { if (e.key === 'Enter') createChannel(newChannel); if (e.key === 'Escape') setNewChannel(null) }}
                   onBlur={() => setNewChannel(null)} style={{ ...input, margin: 6 }} />)}
      </div>

      {/* channel */}
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}
           onDragOver={e => { if (e.dataTransfer.types.includes('Files')) e.preventDefault() }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 10px', borderBottom: '1px solid var(--rule)' }}>
          <b style={{ fontSize: 13 }}># {current}</b>
          {accessOf(chanRec) && <span className="tag" style={{ fontSize: 10 }} title={accessLabel(accessOf(chanRec)!)}><Lock size={9} /> {tr('restreint', 'restricted')}</span>}
          <span style={{ flex: 1 }} />
          {chanRec?.call_link && <button type="button" className="btn sm" onClick={() => join(chanRec.call_link!)}
                                         title={chanRec.call_link}><Phone size={12} /> {tr('Rejoindre l’appel', 'Join the call')}</button>}
          <button type="button" className="btn ghost sm" onClick={() => setCallMenu(s => !s)} style={{ background: callMenu ? 'var(--paper-2)' : undefined }}>
            <Video size={12} /> {tr('Nouvelle reunion', 'New meeting')}</button>
        </div>
        {accessEdit && (
          <div style={{ padding: '6px 10px', borderBottom: '1px solid var(--rule)', background: 'var(--paper-2)' }}>
            <AccessPicker value={accessEdit.value} onChange={value => setAccessEdit({ value })} project={project} />
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 4 }}>
              <span className="tp-note" style={{ flex: 1, color: 'var(--ink-4)' }}>
                {tr('Les leads et superviseurs voient tous les canaux. Visible dans FLUX seulement : le fichier du chat reste lisible sur le partage.',
                    'Leads and supervisors see every channel. FLUX visibility only: the chat file stays readable on the share.')}</span>
              <button type="button" className="btn sm" onClick={() => saveAccess(accessEdit.value)}>{tr('Enregistrer', 'Save')}</button>
              <button type="button" className="btn ghost sm" onClick={() => setAccessEdit(null)}><X size={12} /></button>
            </div>
          </div>
        )}
        {(callMenu || paste || linkEdit !== null) && (
          <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 6, padding: '6px 10px', borderBottom: '1px solid var(--rule)', background: 'var(--paper-2)' }}>
            {linkEdit !== null ? <>
              <input autoFocus defaultValue={linkEdit} placeholder="https://..." style={{ ...input, flex: 1, minWidth: 200 }}
                     onKeyDown={e => { if (e.key === 'Enter') saveLink((e.target as HTMLInputElement).value); if (e.key === 'Escape') setLinkEdit(null) }} id="flux-team-link" />
              <button type="button" className="btn sm" onClick={() => saveLink((document.getElementById('flux-team-link') as HTMLInputElement).value)}>{tr('Enregistrer', 'Save')}</button>
              <button type="button" className="btn ghost sm" onClick={() => setLinkEdit(null)}><X size={12} /></button>
            </> : paste ? <>
              <span className="cap">{tr(`Cree la reunion ${paste.label} dans le navigateur, puis colle son lien :`, `Create the ${paste.label} meeting in the browser, then paste its link:`)}</span>
              <input autoFocus placeholder="https://..." style={{ ...input, flex: 1, minWidth: 200 }} id="flux-team-paste"
                     onKeyDown={e => { if (e.key === 'Enter') postCall(paste.label, (e.target as HTMLInputElement).value.trim()); if (e.key === 'Escape') setPaste(null) }} />
              <button type="button" className="btn sm" onClick={() => postCall(paste.label, (document.getElementById('flux-team-paste') as HTMLInputElement).value.trim())}>{tr('Poster', 'Post')}</button>
              <button type="button" className="btn ghost sm" onClick={() => setPaste(null)}><X size={12} /></button>
            </> : <>
              <button type="button" className="btn sm" onClick={() => newMeeting('jitsi')} title={tr('Lien genere tout de suite, sans compte (le premier arrive se connecte sur meet.jit.si)', 'Link made at once, no account')}>Jitsi</button>
              <button type="button" className="btn sm" onClick={() => newMeeting('meet')}>Google Meet</button>
              <button type="button" className="btn sm" onClick={() => newMeeting('teams')}>Teams</button>
              {lead && <button type="button" className="btn ghost sm" title={tr('Lien d’appel permanent du canal (Discord, Teams, Meet, Jitsi) : bouton Rejoindre', 'Permanent call link of the channel: Join button')}
                               onClick={() => { setCallMenu(false); setLinkEdit(chanRec?.call_link ?? '') }}><Phone size={12} /> {tr('Lien d’appel du canal', 'Channel call link')}</button>}
              <label className="cap" style={{ display: 'inline-flex', alignItems: 'center', gap: 4, marginLeft: 8 }}>
                <input type="checkbox" checked={notifyAll} onChange={e => setNotifyAll(e.target.checked)} />
                {tr('Prevenir l’equipe (telephone)', 'Notify the team (phone)')}</label>
            </>}
          </div>
        )}
        {pinned.length > 0 && (
          <div style={{ padding: '4px 10px', borderBottom: '1px solid var(--rule)', background: 'var(--paper-2)', maxHeight: 74, overflow: 'auto' }}>
            {pinned.map(m => (
              <div key={m.id} style={{ fontSize: 12, display: 'flex', gap: 6, alignItems: 'center' }}>
                <Pin size={11} style={{ flex: 'none', color: 'var(--accent)' }} /><b>{m.user}</b>
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{m.message}</span>
              </div>
            ))}
          </div>
        )}
        <div ref={listRef} onScroll={e => { const el = e.currentTarget; atBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40 }}
             style={{ flex: 1, overflow: 'auto', padding: '6px 4px' }}>
          {error && <div className="tp-note" style={{ color: 'var(--err)', padding: 8 }}>{error}</div>}
          {!roots.length && !error && <div className="tp-note" style={{ color: 'var(--ink-4)', padding: 12 }}>{tr('Aucun message dans ce canal.', 'No message in this channel.')}</div>}
          {roots.map(m => (
            <Message key={m.id} m={m} users={userSet} reacts={reactions.get(m.id)} replies={replies.get(m.id)?.length ?? 0} pinned={pins.has(m.id)}
                     lead={lead} project={project} filesDir={filesDir} onReact={react} onReply={() => setThread(m.id)} onPin={() => togglePin(m.id)} />
          ))}
        </div>
        <Composer users={users} project={project} placeholder={tr(`Message dans #${current} (@nom previent l’artiste)`, `Message in #${current} (@name notifies)`)}
                  onSend={(message, attachments) => send({ message, attachments })} />
      </div>

      {menu && (
        <div onMouseDown={e => e.stopPropagation()}
             style={{ position: 'fixed', left: menu.x, top: menu.y, zIndex: 80, minWidth: 180, padding: 4, background: 'var(--paper)',
                      border: '1px solid var(--rule-2)', borderRadius: 6, boxShadow: '0 2px 8px oklch(0% 0 0 / 0.2)', display: 'flex', flexDirection: 'column' }}>
          <div className="cap" style={{ padding: '3px 8px' }}># {menu.name}</div>
          <button type="button" className="btn ghost sm" style={{ justifyContent: 'flex-start' }}
                  onClick={() => { setChannel(menu.name); setThread(null); setAccessEdit({ value: accessOf(channels.byName.get(menu.name)) }); setMenu(null) }}>
            <Eye size={12} /> {tr('Qui voit ce canal...', 'Who sees this channel...')}</button>
          <button type="button" className="btn ghost sm" style={{ justifyContent: 'flex-start' }}
                  onClick={() => { setChannel(menu.name); setThread(null); setLinkEdit(channels.byName.get(menu.name)?.call_link ?? ''); setMenu(null) }}>
            <Phone size={12} /> {tr('Lien d’appel du canal...', 'Channel call link...')}</button>
          <button type="button" className="btn ghost sm" style={{ justifyContent: 'flex-start' }}
                  onClick={() => { void meta([{ op: 'put', rid: channels.byName.get(menu.name)!.rid, fields: { archived: true } }]); if (current === menu.name) setChannel(GENERAL); setMenu(null) }}>
            <Archive size={12} /> {tr('Archiver', 'Archive')}</button>
        </div>
      )}

      {/* thread */}
      {root && (
        <div style={{ width: 300, flex: 'none', borderLeft: '1px solid var(--rule)', display: 'flex', flexDirection: 'column' }}>
          <div style={{ display: 'flex', alignItems: 'center', padding: '6px 10px', borderBottom: '1px solid var(--rule)' }}>
            <b style={{ fontSize: 12.5 }}>{tr('Fil', 'Thread')}</b><span style={{ flex: 1 }} />
            <button type="button" className="btn ghost sm" onClick={() => setThread(null)}><X size={12} /></button>
          </div>
          <div style={{ flex: 1, overflow: 'auto', padding: '6px 4px' }}>
            <Message m={root} users={userSet} reacts={reactions.get(root.id)} replies={0} pinned={pins.has(root.id)} lead={lead}
                     project={project} filesDir={filesDir} onReact={react} onPin={() => togglePin(root.id)} />
            <div style={{ borderTop: '1px solid var(--rule)', margin: '4px 8px' }} />
            {(replies.get(root.id) ?? []).map(r => (
              <Message key={r.id} m={r} users={userSet} reacts={reactions.get(r.id)} replies={0} pinned={false} lead={false}
                       project={project} filesDir={filesDir} onReact={react} />
            ))}
          </div>
          <Composer users={users} project={project} placeholder={tr('Repondre dans le fil', 'Reply in the thread')}
                    onSend={(message, attachments) => send({ message, attachments, reply_to: root.id })} />
        </div>
      )}

      {/* everyone of the pipeline, online or not (collapsible) */}
      <PeoplePanel storageKey="flux.people.team" />
    </div>
  )
}

function Message({ m, users, reacts, replies, pinned, lead, project, filesDir, onReact, onReply, onPin }: {
  m: TeamMessage; users: Set<string>; reacts?: Map<TeamEmoji, { n: number; mine?: TeamRecord; who: string[] }>
  replies: number; pinned: boolean; lead: boolean; project: string; filesDir: string
  onReact: (msg: string, e: TeamEmoji) => void; onReply?: () => void; onPin?: () => void
}) {
  const { tr } = useTr()
  const [hover, setHover] = useState(false)
  const open = (a: TeamAttachment) => { if (filesDir && window.electronAPI?.openPath) void window.electronAPI.openPath(`${filesDir}/${a.file}`); else window.open(teamApi.fileUrl(project, a.file), '_blank') }
  return (
    <div onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
         style={{ position: 'relative', padding: '5px 8px', borderRadius: 6, background: hover ? 'var(--paper-2)' : undefined }}>
      <div style={{ display: 'flex', gap: 6, alignItems: 'baseline', fontSize: 12 }}>
        <PresenceDot user={m.user} style={{ alignSelf: 'center' }} /><b>{m.user}</b><span style={{ color: 'var(--ink-4)', fontSize: 11 }}>{m.date} {m.time}</span>
        {pinned && <Pin size={10} style={{ color: 'var(--accent)' }} />}
      </div>
      <div style={{ fontSize: 13, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}><Text text={m.message} users={users} /></div>
      {!!m.attachments?.length && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 4 }}>
          {m.attachments.map(a => a.image
            ? <img key={a.file} src={teamApi.fileUrl(project, a.file)} alt={a.name} title={a.name} onClick={() => open(a)} loading="lazy"
                   style={{ maxWidth: 220, maxHeight: 160, borderRadius: 6, border: '1px solid var(--rule)', cursor: 'pointer' }} />
            : <button key={a.file} type="button" className="btn ghost sm" onClick={() => open(a)}><Paperclip size={11} /> {a.name} ({sizeTxt(a.size)})</button>)}
        </div>
      )}
      {(reacts?.size || replies > 0) ? (
        <div style={{ display: 'flex', gap: 4, marginTop: 3, flexWrap: 'wrap' }}>
          {[...(reacts ?? new Map())].map(([e, r]) => (
            <button key={e} type="button" title={r.who.join(', ')} onClick={() => onReact(m.id, e)}
                    style={{ ...chip, border: r.mine ? '1.5px solid var(--accent)' : '1px solid var(--rule-2)' }}>{EMOJI[e as TeamEmoji]} {r.n}</button>
          ))}
          {replies > 0 && onReply && <button type="button" onClick={onReply} style={{ ...chip, color: 'var(--accent)' }}>
            {replies} {replies > 1 ? tr('reponses', 'replies') : tr('reponse', 'reply')}</button>}
        </div>
      ) : null}
      {hover && (
        <div style={{ position: 'absolute', right: 6, top: -10, display: 'flex', gap: 2, padding: 2, background: 'var(--paper)', border: '1px solid var(--rule)',
                      borderRadius: 6, boxShadow: '0 1px 4px oklch(0% 0 0 / 0.15)' }}>
          {(Object.keys(EMOJI) as TeamEmoji[]).map(e => <button key={e} type="button" onClick={() => onReact(m.id, e)} style={iconBtn}>{EMOJI[e]}</button>)}
          {onReply && <button type="button" title={tr('Repondre dans un fil', 'Reply in a thread')} onClick={onReply} style={iconBtn}><MessageSquareReply size={13} /></button>}
          {lead && onPin && <button type="button" title={pinned ? tr('Desepingler', 'Unpin') : tr('Epingler', 'Pin')} onClick={onPin} style={iconBtn}>
            {pinned ? <PinOff size={13} /> : <Pin size={13} />}</button>}
        </div>
      )}
    </div>
  )
}

function Composer({ users, project, placeholder, onSend }: {
  users: string[]; project: string; placeholder: string; onSend: (message: string, attachments: TeamAttachment[]) => Promise<void>
}) {
  const { tr } = useTr()
  const [text, setText] = useState('')
  const [files, setFiles] = useState<TeamAttachment[]>([])
  const [busy, setBusy] = useState(false)
  const at = /@([A-Za-z0-9_.-]*)$/.exec(text)
  // A name already typed in full is not suggested again (Enter then sends).
  const suggest = at && !users.some(u => u.toUpperCase() === at[1].toUpperCase())
    ? users.filter(u => u.toUpperCase().startsWith(at[1].toUpperCase())).slice(0, 6) : []
  const attachPaths = async (paths: string[]) => {
    for (const p of paths) {
      try { const a = await teamApi.attach(project, p); setFiles(f => [...f.filter(x => x.file !== a.file), a]) } catch (err) { fail(err) }
    }
  }
  const pick = async () => {
    const paths = await window.electronAPI?.openFiles?.([{ name: tr('Fichiers', 'Files'), extensions: ['*'] }])
    if (paths?.length) await attachPaths(paths)
  }
  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    const dropped = [...e.dataTransfer.files]
    if (!dropped.length) return
    e.preventDefault()
    const toPath = window.electronAPI?.pathForFile
    if (!toPath) { toast.info(tr('Deposer un fichier : seulement dans FLUX (Electron).', 'Dropping a file: only in the FLUX app.')); return }
    void attachPaths(dropped.map(f => toPath(f)).filter(Boolean))
  }
  const submit = async () => {
    const msg = text.trim()
    if ((!msg && !files.length) || busy) return
    setBusy(true)
    try { await onSend(msg || files.map(f => f.name).join(', '), files); setText(''); setFiles([]) } catch (err) { fail(err) } finally { setBusy(false) }
  }
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      if (suggest.length && at) { setText(text.slice(0, at.index) + `@${suggest[0]} `); return }
      void submit()
    }
  }
  return (
    <div onDrop={onDrop} onDragOver={e => { if (e.dataTransfer.types.includes('Files')) e.preventDefault() }}
         style={{ borderTop: '1px solid var(--rule)', padding: 8, position: 'relative' }}>
      {suggest.length > 0 && (
        <div style={{ position: 'absolute', bottom: '100%', left: 8, background: 'var(--paper)', border: '1px solid var(--rule)', borderRadius: 6, boxShadow: '0 2px 8px oklch(0% 0 0 / 0.15)', zIndex: 3 }}>
          {suggest.map(u => <div key={u} onMouseDown={e => { e.preventDefault(); setText(text.slice(0, at!.index) + `@${u} `) }}
                                 style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 10px', fontSize: 12, cursor: 'pointer' }}>
                                 <PresenceDot user={u} />@{u}</div>)}
        </div>
      )}
      {files.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 6 }}>
          {files.map(f => <span key={f.file} className="tag" style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <Paperclip size={10} />{f.name}
            <button type="button" onClick={() => setFiles(x => x.filter(y => y.file !== f.file))} style={iconBtn}><X size={10} /></button></span>)}
        </div>
      )}
      <div style={{ display: 'flex', gap: 6, alignItems: 'flex-end' }}>
        {window.electronAPI?.openFiles && <button type="button" className="btn ghost sm" title={tr('Joindre un fichier (copie dans le projet)', 'Attach a file (copied into the project)')}
                                                 onClick={() => { void pick() }}><Paperclip size={13} /></button>}
        <textarea value={text} onChange={e => setText(e.target.value)} onKeyDown={onKey} rows={2} placeholder={placeholder}
                  style={{ ...input, flex: 1, height: 'auto', resize: 'none', padding: 6, fontFamily: 'inherit' }} />
        <button type="button" className="btn sm" disabled={busy || (!text.trim() && !files.length)} onClick={() => { void submit() }}><Send size={13} /></button>
      </div>
    </div>
  )
}

const input: React.CSSProperties = { height: 26, padding: '0 8px', border: '1px solid var(--rule-2)', background: 'var(--bg-deep)', borderRadius: 5, fontSize: 12, color: 'var(--ink)', minWidth: 0 }
const iconBtn: React.CSSProperties = { border: 'none', background: 'transparent', padding: '1px 3px', cursor: 'pointer', color: 'inherit', display: 'inline-flex', alignItems: 'center', fontSize: 13 }
const chip: React.CSSProperties = { fontSize: 11, lineHeight: '16px', padding: '0 6px', borderRadius: 8, cursor: 'pointer', color: 'var(--ink)', background: 'var(--paper)' }
