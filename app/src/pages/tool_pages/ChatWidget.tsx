// ChatWidget.tsx — the project team chat as a TOOL widget (ADR 0077, 0091): channels, threads,
// reactions, pinned messages, attached files (copied by the backend). No Discord link, no call
// link, no presence (ADR 0091). Channels and pins: leads. A reaction belongs to its author.
// ADR 0081: a message starting with /name runs the active flows with a TeamCommand node of
// that name, on this workstation; `/` completes the commands allowed in the channel.
// P5 (Discord-like options, 2026-10-31): right click on a channel / group for everyone
// (mark as read, mute, copy a link); leads also rename, write the topic, make it read only,
// change its type (text, voice, forum, announcement), duplicate it, set who sees a group.
// A forum lists its posts (the first line of a root message is the post title).

import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent, type KeyboardEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Archive, Bell, BellOff, CheckCheck, ChevronDown, ChevronRight, Copy, Eye, FolderPlus, Hash, Link2, Lock, Megaphone, MessageSquareReply, MessagesSquare, Paperclip, Pencil, Pin, PinOff, Plus, Send, Trash2, Users, Volume2, X } from 'lucide-react'
import { toast } from 'sonner'
import { teamApi, type TeamAttachment, type TeamChannelType, type TeamEmoji, type TeamMessage, type TeamMutes, type TeamRecord } from '../../api/team'
import { flowsApi } from '../../api/flows'
import type { PageAccess, PageDataOp, TeamCommand } from '../flow_editor/types'
import { AccessPicker, cleanAccess, isEveryone } from './PageAccess'
import { useTr } from '../flow_editor/useTr'
import type { DataWidgetProps } from './DataWidgets'

const GENERAL = 'general'
const REFRESH_MS = 4000
const EMOJI: Record<TeamEmoji, string> = { like: '\u{1F44D}', love: '❤️', laugh: '\u{1F602}', question: '❓', check: '✅' }
const URL_RE = /(https?:\/\/[^\s<>"]+)/g
const COMMAND_RE = /^\/([A-Za-z][A-Za-z0-9_-]*)(\s|$)/
const VIDEO_RE = /\.(mp4|m4v|webm|mov)$/i     // played inline (Chromium: .mov only when H.264 / AAC)
const fail = (err: unknown) => toast.error((err as Error).message)

export function openLink(url: string) {
  if (!/^https:\/\//.test(url)) { toast.info('Seuls les liens https:// s’ouvrent depuis FLUX.'); return }
  if (window.electronAPI?.openExternal) void window.electronAPI.openExternal(url)
  else window.open(url, '_blank', 'noopener')
}
const chanOf = (m: TeamMessage) => m.channel || GENERAL
// Channel order: order, then the name without case.
const byOrder = (a: TeamRecord, b: TeamRecord) => ((a.order ?? Infinity) - (b.order ?? Infinity)) || (String(a.name).toLowerCase() < String(b.name).toLowerCase() ? -1 : String(a.name).toLowerCase() > String(b.name).toLowerCase() ? 1 : 0)
// The text channels of a group come before its voice ones.
const textFirst = (a: TeamRecord, b: TeamRecord) => Number(a.type === 'voice') - Number(b.type === 'voice')
const sizeTxt = (n: number) => n > 1 << 20 ? `${(n / (1 << 20)).toFixed(1)} Mo` : `${Math.max(1, Math.round(n / 1024))} Ko`

// Internal link of a channel / message (P5 "Copier le lien"): opens the TOOL page of the chat
// widget there (ADR 0091). An old /team?channel=.. link (Team page, removed) opens the channel
// in the chat widget it is shown in.
export const teamLink = (page: string, channel: string, message?: string) =>
  `/tool?page=${encodeURIComponent(page)}&channel=${encodeURIComponent(channel)}${message ? `&message=${encodeURIComponent(message)}` : ''}`
const TEAM_LINK_RE = /(\/(?:tool\?page=[A-Za-z0-9_.-]+&|team\?)channel=[a-z0-9_-]+(?:&message=[A-Za-z0-9_.:%-]+)?)/g

function Text({ text, users }: { text: string; users: Set<string> }) {
  // Links open in the system browser; FLUX chat links open the TOOL page; @names of real artists stand out.
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const go = (seg: string) => {
    if (seg.startsWith('/tool')) { navigate(seg); return }
    // Old /team?channel=..&message=.. link: same channel in the widget showing it.
    const q = new URLSearchParams(seg.slice(seg.indexOf('?') + 1))
    const next = new URLSearchParams(params)
    for (const k of ['channel', 'message']) { const v = q.get(k); if (v) next.set(k, v); else next.delete(k) }
    setParams(next)
  }
  const parts = text.split(URL_RE)
  return <>{parts.map((part, i) => i % 2
    ? <a key={i} href={part} onClick={e => { e.preventDefault(); openLink(part) }} style={{ color: 'var(--accent)', wordBreak: 'break-all' }}>{part}</a>
    : part.split(TEAM_LINK_RE).map((seg, k) => k % 2
      ? <a key={`${i}-${k}`} href={seg} onClick={e => { e.preventDefault(); go(seg) }} style={{ color: 'var(--accent)', wordBreak: 'break-all' }}>{seg}</a>
      : seg.split(/(@[A-Za-z0-9_.-]+)/g).map((bit, j) => bit.startsWith('@') && users.has(bit.slice(1).toUpperCase())
        ? <b key={`${i}-${k}-${j}`} style={{ color: 'var(--accent)' }}>{bit}</b> : <span key={`${i}-${k}-${j}`}>{bit}</span>)))}</>
}

// Access of a channel record (stored as JSON text), undefined = everyone.
function accessOf(r: TeamRecord | undefined): PageAccess | undefined {
  if (!r?.access) return undefined
  try { const a = JSON.parse(r.access) as PageAccess; return isEveryone(a) ? undefined : a } catch { return undefined }
}
const accessLabel = (a: PageAccess) => [...(a.users ?? []), ...(a.roles ?? [])].join(', ')
const TYPES: TeamChannelType[] = ['text', 'voice', 'forum', 'announcement']
const TYPE_LABEL: Record<TeamChannelType, [string, string]> = {
  text: ['Canal texte', 'Text channel'], voice: ['Canal vocal', 'Voice channel'],
  forum: ['Forum', 'Forum'], announcement: ['Annonces', 'Announcements'],
}
const readOnly = (r?: TeamRecord) => !!r && (!!r.read_only || r.type === 'announcement')
// A forum post: the first line of its root message is its title (an old Discord thread copied in starts "Fil : ").
const postTitle = (m: TeamMessage) => (m.message.split('\n')[0] || '').replace(/^Fil : /, '').slice(0, 120)
function ChanIcon({ rec, size = 12 }: { rec?: TeamRecord; size?: number }) {
  const st = { opacity: 0.6, flex: 'none' as const }
  if (rec?.type === 'voice') return <Volume2 size={size} style={st} />
  if (rec?.type === 'announcement') return <Megaphone size={size} style={st} />
  if (rec?.type === 'forum') return <MessagesSquare size={size} style={st} />
  return accessOf(rec) ? <Lock size={size - 1} style={st} /> : <Hash size={size} style={st} />
}

// A chat link (?channel=..&message=.. on the TOOL page URL) opens that channel and message (P5).
export function ChatWidget({ page, widget: w, project, preview }: DataWidgetProps) {
  const { tr } = useTr()
  const [params] = useSearchParams()
  const focus = { channel: params.get('channel') ?? undefined, message: params.get('message') ?? undefined }
  const [messages, setMessages] = useState<TeamMessage[]>([])
  const [users, setUsers] = useState<string[]>([])
  const [records, setRecords] = useState<TeamRecord[]>([])
  const [lead, setLead] = useState(false)
  const [filesDir, setFilesDir] = useState('')
  const [me, setMe] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [channel, setChannel] = useState(() => { try { return localStorage.getItem(`flux.team.channel.${project}`) || GENERAL } catch { return GENERAL } })
  const [thread, setThread] = useState<string | null>(null)
  const [newChannel, setNewChannel] = useState<{ name: string; type: TeamChannelType; group: string } | null>(null)
  const [groupEdit, setGroupEdit] = useState<{ rid?: string; name: string } | null>(null)   // new group (no rid) or rename
  // Who sees a channel or a group (leads). inherit: a channel of a restricted group follows it.
  const [accessEdit, setAccessEdit] = useState<{ value: PageAccess | undefined; kind: 'channel' | 'group'; rid?: string; name: string; inherit?: boolean } | null>(null)
  // One line edits of a channel (leads): name shown, topic, voice status, voice limit.
  const [fieldEdit, setFieldEdit] = useState<{ rid?: string; name: string; field: 'title' | 'topic' | 'voice_status' | 'user_limit'; value: string } | null>(null)
  const [mutes, setMutes] = useState<TeamMutes>({ channels: [], groups: [] })   // this artist's (USER/<artist>/team_mutes.json)
  const [panel, setPanel] = useState(false)          // pinned messages and active threads of the channel
  const [flash, setFlash] = useState<string | null>(null)   // message highlighted after a link
  const [seenTick, setSeenTick] = useState(0)        // "mark as read" re-counts the unread
  const [menu, setMenu] = useState<{ name: string; group?: TeamRecord; x: number; y: number } | null>(null)   // right click on a channel / group (leads)
  const [commands, setCommands] = useState<TeamCommand[]>([])
  const [askArchive, setAskArchive] = useState<{ label: string; note?: string; run: () => void } | null>(null)   // archive asks first (2026-10-31)
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
  useEffect(() => {
    if (!project || preview) return
    teamApi.mutes(project).then(setMutes).catch(() => setMutes({ channels: [], groups: [] }))
  }, [project, preview])
  useEffect(() => {
    if (focus?.channel) { setChannel(focus.channel); setThread(null) }
    if (focus?.message) setFlash(focus.message)
  }, [focus?.channel, focus?.message])
  useEffect(() => { const el = listRef.current; if (el && atBottom.current) el.scrollTop = el.scrollHeight }, [messages, channel])

  // -- derived ---------------------------------------------------------------
  const userSet = useMemo(() => new Set(users.map(u => u.toUpperCase())), [users])
  // Channels by group (ADR 0084): #general first, then the channels without a group, then each
  // group in its order. A channel whose group is archived falls back to no group.
  const channels = useMemo(() => {
    const recs = records.filter(r => r.kind === 'channel' && r.name)
    const byName = new Map(recs.map(r => [r.name!, r]))
    const groups = records.filter(r => r.kind === 'group' && !r.archived).sort(byOrder)
    const live = new Set(groups.map(g => g.rid))
    const active = recs.filter(r => r.name !== GENERAL && !r.archived).sort(byOrder)
    const inGroup = (gid: string) => active.filter(r => (r.group && live.has(r.group) ? r.group : '') === gid).sort(textFirst).map(r => r.name!)
    const sections = [{ group: undefined as TeamRecord | undefined, names: [GENERAL, ...inGroup('')] },
                      ...groups.map(g => ({ group: g as TeamRecord | undefined, names: inGroup(g.rid) }))]
    return { names: sections.flatMap(s => s.names), sections, byName }
  }, [records])
  const shownName = (key: string) => channels.byName.get(key)?.title || key
  const [collapsed, setCollapsed] = useState<Set<string>>(() => {
    try { return new Set(JSON.parse(localStorage.getItem(`flux.team.collapsed.${project}`) || '[]')) } catch { return new Set() }
  })
  const toggleGroup = (rid: string) => setCollapsed(prev => {
    const next = new Set(prev)
    if (!next.delete(rid)) next.add(rid)
    try { localStorage.setItem(`flux.team.collapsed.${project}`, JSON.stringify([...next])) } catch { /* private mode */ }
    return next
  })
  const [drag, setDrag] = useState<{ kind: 'channel' | 'group'; name: string } | null>(null)
  const [over, setOver] = useState<string | null>(null)   // drop target shown while dragging: channel key, g:<rid>, end:<rid>
  const startDrag = (e: DragEvent, kind: 'channel' | 'group', name: string) => {
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', name)
    setDrag({ kind, name })
  }
  const endDrag = () => { setDrag(null); setOver(null) }
  const dragOver = (e: DragEvent, target: string, ok: boolean) => {
    if (!drag || !ok) return
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
    if (over !== target) setOver(target)
  }
  const dropLine = (target: string) => drag && over === target ? { boxShadow: 'inset 0 2px 0 var(--accent)' } : {}
  const current = channels.names.includes(channel) ? channel : GENERAL
  useEffect(() => {
    if (!project || preview) { setCommands([]); return }
    flowsApi.teamCommands(project, current).then(r => setCommands(r.commands)).catch(() => setCommands([]))
  }, [project, preview, current])
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
  const muted = useCallback((name: string) => {
    const g = channels.byName.get(name)?.group
    return mutes.channels.includes(name) || (!!g && mutes.groups.includes(g))
  }, [mutes, channels.byName])
  const unread = useMemo(() => {
    // Messages of the other channels since this viewer last opened them (kept on this machine).
    // A muted channel counts only the messages that @mention this artist (P5).
    const out: Record<string, number> = {}
    const tag = me ? `@${me.toUpperCase()}` : ''
    for (const name of channels.names) {
      let seen = ''
      try { seen = localStorage.getItem(`flux.team.seen.${project}.${name}`) || '' } catch { /* private mode */ }
      const quiet = muted(name)
      out[name] = messages.filter(m => chanOf(m) === name && `${m.date} ${m.time}` > seen && m.user !== me
                                       && (!quiet || (!!tag && m.message.toUpperCase().includes(tag)))).length
    }
    return out
  }, [messages, channels.names, project, me, muted, seenTick])  // eslint-disable-line react-hooks/exhaustive-deps
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
  const runCommand = async (text: string, reply_to?: string) => {
    if (!project) return
    const r = await flowsApi.runTeamCommand({ project, text, reply_to, channel: current === GENERAL ? undefined : current })
    const refused = r.runs.filter(x => x.status === 'refused' || x.status === 'skipped')
    if (refused.length) toast.error(refused.map(x => `${x.flow} : ${x.error ?? x.status}`).join('\n'))
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
  const markRead = (names: string[]) => {
    for (const n of names) {
      const last = messages.filter(m => chanOf(m) === n).pop()
      if (last) try { localStorage.setItem(`flux.team.seen.${project}.${n}`, `${last.date} ${last.time}`) } catch { /* private mode */ }
    }
    setSeenTick(t => t + 1)
  }
  const toggleMute = (what: { channel?: string; group?: string }) => {
    if (!project) return
    const next = { channels: [...mutes.channels], groups: [...mutes.groups] }
    const list = what.group ? next.groups : next.channels
    const id = (what.group ?? what.channel)!
    const at = list.indexOf(id)
    if (at >= 0) list.splice(at, 1); else list.push(id)
    setMutes(next)
    teamApi.setMutes(project, next).then(setMutes).catch(fail)
  }
  const copyLink = (channelKey: string, message?: string) => {
    navigator.clipboard.writeText(teamLink(page.id, channelKey, message))
      .then(() => toast.success(tr('Lien copie : colle-le dans un message', 'Link copied: paste it in a message')))
      .catch(fail)
  }
  // Same type, group, access, topic, read only and limit; no messages; "<name>-copie" (P5).
  const duplicate = (key: string) => {
    const r = channels.byName.get(key)
    if (!r) return
    const base = `${shownName(key).slice(0, 26)}-copie`
    let n = base
    for (let i = 2; channels.names.some(k => shownName(k) === n); i++) n = `${base.slice(0, 32 - String(i).length - 1)}-${i}`
    let k = n
    for (let i = 2; channels.byName.has(k) || k === GENERAL; i++) k = `${n.slice(0, 32 - String(i).length - 1)}-${i}`
    void meta([{ op: 'put', fields: { kind: 'channel', name: k, ...(k !== n ? { title: n } : {}), type: r.type ?? null, group: r.group ?? null,
                                      access: r.access ?? null, topic: r.topic ?? null, read_only: r.read_only ?? null,
                                      user_limit: r.user_limit ?? null, order: (r.order ?? channels.names.length) + 0.5 } }])
    setChannel(k)
  }
  const saveField = () => {
    if (!fieldEdit) return
    const { rid, name, field, value } = fieldEdit
    let v: unknown = value.trim() || null
    if (field === 'title') {
      const t = value.trim().toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-+/, '').slice(0, 32)
      v = t && t !== name ? t : null
    }
    if (field === 'user_limit') { const n = parseInt(value, 10); v = Number.isFinite(n) && n > 0 ? Math.min(n, 99) : null }
    void meta(rid ? [{ op: 'put', rid, fields: { [field]: v } }] : [{ op: 'put', fields: { kind: 'channel', name, [field]: v } }])
    setFieldEdit(null)
  }
  const editField = (key: string, field: 'title' | 'topic' | 'voice_status' | 'user_limit') => {
    const r = channels.byName.get(key)
    const value = field === 'title' ? shownName(key) : String((r as Record<string, unknown> | undefined)?.[field] ?? '')
    setChannel(key); setThread(null)
    setFieldEdit({ rid: r?.rid, name: key, field, value })
  }
  const createChannel = ({ name, type, group }: { name: string; type: TeamChannelType; group: string }) => {
    const n = name.trim().toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-+/, '').slice(0, 32)
    if (!n) return
    // An archived channel never comes back here (Projects > Archived): the same name starts
    // empty under a new key (lighting-2) that shows "lighting" (2026-10-31).
    if (channels.names.some(k => shownName(k) === n)) { toast.error(tr(`#${n} existe deja`, `#${n} already exists`)); return }
    let key = n
    for (let i = 2; channels.byName.has(key) || key === GENERAL; i++) key = `${n.slice(0, 32 - String(i).length - 1)}-${i}`
    const place = { type: type === 'text' ? null : type, group: group || null, order: channels.names.length + 1 }
    void meta([{ op: 'put', fields: { kind: 'channel', name: key, ...(key !== n ? { title: n } : {}), ...place } }])
    setNewChannel(null)
    setChannel(key)
  }
  const saveGroup = ({ rid, name }: { rid?: string; name: string }) => {
    const label = name.trim()
    setGroupEdit(null)
    if (!label) return
    void meta(rid ? [{ op: 'put', rid, fields: { name: label } }]
                  : [{ op: 'put', fields: { kind: 'group', name: label, order: channels.sections.length } }])
  }
  // Drag to arrange (leads): a channel dropped on a channel goes before it, in its group; on a
  // group header, at the end of that group. The section is renumbered 1..n (few writes).
  const moveChannel = (name: string, group: string, before?: string) => {
    const section = channels.sections.find(s => (s.group?.rid ?? '') === group)
    if (!section || name === before) return
    const list = section.names.filter(n => n !== GENERAL && n !== name)
    const at = before ? list.indexOf(before) : -1
    list.splice(at < 0 ? list.length : at, 0, name)
    list.sort((a, b) => textFirst(channels.byName.get(a) ?? {} as TeamRecord, channels.byName.get(b) ?? {} as TeamRecord))
    const ops: PageDataOp[] = []
    list.forEach((n, i) => {
      const r = channels.byName.get(n)
      if (!r) return
      const fields: Record<string, unknown> = {}
      if (r.order !== i + 1) fields.order = i + 1
      if (n === name && (r.group || '') !== group) fields.group = group || null
      if (Object.keys(fields).length) ops.push({ op: 'put', rid: r.rid, fields })
    })
    if (ops.length) void meta(ops)
  }
  const moveGroup = (rid: string, before: string) => {
    const list = channels.sections.flatMap(s => s.group && s.group.rid !== rid ? [s.group] : [])
    const moved = channels.sections.find(s => s.group?.rid === rid)?.group
    if (!moved || rid === before) return
    const at = list.findIndex(g => g.rid === before)
    list.splice(at < 0 ? list.length : at, 0, moved)
    const ops: PageDataOp[] = list.flatMap((g, i) => g.order === i + 1 ? [] : [{ op: 'put' as const, rid: g.rid, fields: { order: i + 1 } }])
    if (ops.length) void meta(ops)
  }
  const onDrop = (e: DragEvent, group: string, before?: { channel?: string; group?: string }) => {
    if (!drag) return
    e.preventDefault(); e.stopPropagation()
    if (drag.kind === 'channel') moveChannel(drag.name, group, before?.channel)
    else if (before?.group) moveGroup(drag.name, before.group)
    endDrag()
  }
  // Who sees the channel (leads): people, roles, like a TOOL page (ADR 0078, 0085).
  // A group's access goes to its channels without their own (Discord "synced", P5); a channel
  // of a restricted group open to everyone stores {} (its own access: everyone).
  const saveAccess = (edit: NonNullable<typeof accessEdit>) => {
    const clean = edit.value ? cleanAccess(edit.value) : undefined
    const access = edit.inherit ? null : clean ? JSON.stringify(clean) : edit.kind === 'channel' && groupAccess(edit.name) ? '{}' : null
    void meta(edit.rid ? [{ op: 'put', rid: edit.rid, fields: { access } }] : [{ op: 'put', fields: { kind: 'channel', name: edit.name, access } }])
    setAccessEdit(null)
  }
  const groupAccess = (key: string) => {
    const g = channels.byName.get(key)?.group
    const rec = g ? records.find(r => r.rid === g && r.kind === 'group' && !r.archived) : undefined
    return accessOf(rec)
  }
  const editAccess = (key: string) => {
    const r = channels.byName.get(key)
    setChannel(key); setThread(null)
    setAccessEdit({ value: accessOf(r) ?? groupAccess(key), kind: 'channel', rid: r?.rid, name: key, inherit: !!groupAccess(key) && !r?.access })
  }
  if (!project) return <div className="tp-note" style={{ padding: 12 }}>{tr('Ouvre un projet : le chat est celui de son equipe.', 'Open a project: the chat is its team’s.')}</div>
  if (preview) return <div className="tp-note" style={{ padding: 12 }}>{tr('Apercu : le chat d’equipe du projet s’affiche ici.', 'Preview: the project team chat shows here.')}</div>

  const root = thread ? messages.find(m => m.id === thread) : undefined
  const locked = readOnly(chanRec) && !lead
  const forum = chanRec?.type === 'forum'
  const threads = roots.filter(m => (replies.get(m.id)?.length ?? 0) > 0)
    .map(m => ({ m, n: replies.get(m.id)!.length, last: replies.get(m.id)!.slice(-1)[0] }))
    .sort((a, b) => `${b.last.date} ${b.last.time}`.localeCompare(`${a.last.date} ${a.last.time}`))
  const goTo = (id: string) => {
    const msg = messages.find(m => m.id === id)
    if (msg?.reply_to) setThread(msg.reply_to)
    setFlash(id)
    setPanel(false)
  }
  const height = w.height ?? 560
  return (
    <div style={{ border: '1px solid var(--rule)', borderRadius: 8, background: 'var(--paper)', display: 'flex', height, overflow: 'hidden', position: 'relative' }}>
      {/* channels */}
      <div style={{ width: 170, flex: 'none', borderRight: '1px solid var(--rule)', display: 'flex', flexDirection: 'column', background: 'var(--paper-2)' }}>
        <div className="cap" style={{ padding: '8px 10px 4px' }}>{w.label || tr('Canaux', 'Channels')}</div>
        <div style={{ flex: 1, overflow: 'auto' }}>
          {channels.sections.map(({ group, names }) => {
            const gid = group?.rid ?? ''
            const shut = !!group && collapsed.has(gid)
            const shown = shut ? names.filter(n => n === current || unread[n] > 0) : names
            return (
              <div key={gid || '_'}>
                {group && (
                  <div draggable={lead} onDragStart={e => startDrag(e, 'group', gid)} onDragEnd={endDrag}
                       onDragOver={e => dragOver(e, `g:${gid}`, true)}
                       onDrop={e => onDrop(e, gid, { group: gid })}
                       onClick={() => toggleGroup(gid)}
                       onContextMenu={e => { e.preventDefault(); setMenu({ name: '', group, x: e.clientX, y: e.clientY }) }}
                       className="cap" style={{ display: 'flex', alignItems: 'center', gap: 2, padding: '8px 6px 2px', cursor: lead ? 'grab' : 'pointer', userSelect: 'none',
                                                ...(drag?.kind === 'group' ? dropLine(`g:${gid}`) : drag && over === `g:${gid}` ? { background: 'var(--accent-soft)' } : {}) }}>
                    {shut ? <ChevronRight size={11} /> : <ChevronDown size={11} />}
                    <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{group.name}</span>
                    {accessOf(group) && <Lock size={9} style={{ opacity: 0.5 }} />}
                    {mutes.groups.includes(gid) && <BellOff size={9} style={{ opacity: 0.5 }} />}
                    {lead && <button type="button" title={tr('Canal dans ce groupe', 'Channel in this group')} style={iconBtn}
                                     onClick={e => { e.stopPropagation(); setNewChannel({ name: '', type: 'text', group: gid }) }}><Plus size={11} /></button>}
                  </div>
                )}
                {groupEdit?.rid === gid && gid && (
                  <input autoFocus defaultValue={groupEdit.name} style={{ ...input, margin: '2px 6px', width: 'calc(100% - 12px)' }}
                         onKeyDown={e => { if (e.key === 'Enter') saveGroup({ rid: gid, name: e.currentTarget.value }); if (e.key === 'Escape') setGroupEdit(null) }}
                         onBlur={() => setGroupEdit(null)} />
                )}
                {shown.map(n => {
                  const rec = channels.byName.get(n)
                  const voice = rec?.type === 'voice'
                  const quiet = muted(n)
                  return (<div key={n}>
                    <div onClick={() => { setChannel(n); setThread(null) }}
                         draggable={lead && n !== GENERAL} onDragStart={e => startDrag(e, 'channel', n)} onDragEnd={endDrag}
                         onDragOver={e => dragOver(e, n, drag?.kind === 'channel')}
                         onDrop={e => onDrop(e, gid, n === GENERAL ? { channel: names[1] } : { channel: n })}
                         onContextMenu={e => { e.preventDefault(); setMenu({ name: n, x: e.clientX, y: e.clientY }) }}
                         style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '4px 10px', cursor: lead && n !== GENERAL ? 'grab' : 'pointer', fontSize: 12.5,
                                  background: n === current ? 'var(--paper)' : undefined, fontWeight: n === current || unread[n] ? 600 : 400,
                                  opacity: drag?.kind === 'channel' && drag.name === n ? 0.4 : quiet && n !== current ? 0.55 : 1,
                                  ...(n === GENERAL ? (drag && over === n ? { boxShadow: 'inset 0 -2px 0 var(--accent)' } : {}) : dropLine(n)) }}>
                      <ChanIcon rec={rec} />
                      <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis' }}>{shownName(n)}</span>
                      {(voice || rec?.type === 'forum' || rec?.type === 'announcement') && accessOf(rec) && <Lock size={10} style={{ opacity: 0.5 }} />}
                      {quiet && <BellOff size={10} style={{ opacity: 0.5 }} />}
                      {voice && !!rec?.user_limit && <span className="tag" style={{ fontSize: 10 }}>{rec.user_limit}</span>}
                      {n !== current && unread[n] > 0 && <span className="tag" style={{ fontSize: 10 }}>{unread[n]}</span>}
                      {lead && n !== GENERAL && n === current && (
                        <button type="button" title={tr('Archiver le canal', 'Archive the channel')} onClick={e => { e.stopPropagation(); setAskArchive({ label: `#${shownName(n)}`, run: () => { void meta([{ op: 'put', rid: rec!.rid, fields: { archived: true } }]); setChannel(GENERAL) } }) }}
                                style={iconBtn}><Archive size={11} /></button>
                      )}
                    </div>
                    {voice && rec?.voice_status && <div className="tp-note" title={rec.voice_status}
                      style={{ padding: '0 10px 3px 26px', fontSize: 11, color: 'var(--ink-4)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{rec.voice_status}</div>}
                  </div>)
                })}
                {drag?.kind === 'channel' && (
                  // end of the section: a channel dropped here goes last in this group
                  <div onDragOver={e => dragOver(e, `end:${gid}:last`, true)} onDrop={e => onDrop(e, gid)}
                       style={{ height: 8, margin: '0 6px', ...dropLine(`end:${gid}:last`) }} />
                )}
                {newChannel && newChannel.group === gid && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 2, margin: '2px 6px' }}>
                    <button type="button" style={iconBtn} title={tr(`${TYPE_LABEL[newChannel.type][0]} (clic : type suivant)`, `${TYPE_LABEL[newChannel.type][1]} (click: next type)`)}
                            onMouseDown={e => e.preventDefault()}
                            onClick={() => setNewChannel({ ...newChannel, type: TYPES[(TYPES.indexOf(newChannel.type) + 1) % TYPES.length] })}>
                      <ChanIcon rec={{ type: newChannel.type } as TeamRecord} /></button>
                    <input autoFocus value={newChannel.name} placeholder={tr('nom-du-canal', 'channel-name')} onChange={e => setNewChannel({ ...newChannel, name: e.target.value })}
                           onKeyDown={e => { if (e.key === 'Enter') createChannel(newChannel); if (e.key === 'Escape') setNewChannel(null) }}
                           onBlur={() => setNewChannel(null)} style={{ ...input, flex: 1 }} />
                  </div>
                )}
              </div>
            )
          })}
          {groupEdit && !groupEdit.rid && (
            <input autoFocus placeholder={tr('Nom du groupe', 'Group name')} style={{ ...input, margin: '6px 6px 0', width: 'calc(100% - 12px)' }}
                   onKeyDown={e => { if (e.key === 'Enter') saveGroup({ name: e.currentTarget.value }); if (e.key === 'Escape') setGroupEdit(null) }}
                   onBlur={() => setGroupEdit(null)} />
          )}
        </div>
        {lead && (
          <div style={{ display: 'flex', gap: 4, margin: 6 }}>
            <button type="button" className="btn ghost sm" onClick={() => setNewChannel({ name: '', type: 'text', group: '' })}><Plus size={12} /> {tr('Canal', 'Channel')}</button>
            <button type="button" className="btn ghost sm" title={tr('Groupe de canaux (categorie)', 'Channel group (category)')}
                    onClick={() => setGroupEdit({ name: '' })}><FolderPlus size={12} /> {tr('Groupe', 'Group')}</button>
          </div>
        )}
      </div>

      {/* channel */}
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}
           onDragOver={e => { if (e.dataTransfer.types.includes('Files')) e.preventDefault() }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 10px', borderBottom: '1px solid var(--rule)' }}>
          <b style={{ fontSize: 13, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <ChanIcon rec={chanRec} size={13} /> {shownName(current)}</b>
          {readOnly(chanRec) && <span className="tag" style={{ fontSize: 10 }} title={tr('Seuls les leads et superviseurs ecrivent ici', 'Only leads and supervisors post here')}>
            {tr('lecture seule', 'read only')}</span>}
          {(accessOf(chanRec) ?? groupAccess(current)) && <span className="tag" style={{ fontSize: 10 }} title={accessLabel((accessOf(chanRec) ?? groupAccess(current))!)}>
            <Lock size={9} /> {accessOf(chanRec) ? tr('restreint', 'restricted') : tr('restreint (groupe)', 'restricted (group)')}</span>}
          <span style={{ flex: 1 }} />
          {(pinned.length > 0 || threads.length > 0) && (
            <button type="button" className="btn ghost sm" onClick={() => setPanel(v => !v)} style={{ background: panel ? 'var(--paper-2)' : undefined }}
                    title={tr('Messages epingles et fils actifs', 'Pinned messages and active threads')}>
              <Pin size={12} /> {pinned.length} <MessageSquareReply size={12} /> {threads.length}</button>
          )}
        </div>
        {(chanRec?.topic || (lead && !fieldEdit)) && chanRec?.type !== 'voice' && (
          <div className="tp-note" onClick={() => { if (lead) editField(current, 'topic') }}
               title={lead ? tr('Clic : modifier le sujet', 'Click: edit the topic') : undefined}
               style={{ padding: '3px 10px', borderBottom: '1px solid var(--rule)', color: chanRec?.topic ? 'var(--ink-3)' : 'var(--ink-4)',
                        cursor: lead ? 'text' : undefined, whiteSpace: 'pre-wrap', maxHeight: 54, overflow: 'auto' }}>
            {chanRec?.topic || tr('Ajouter un sujet', 'Add a topic')}</div>
        )}
        {fieldEdit && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 10px', borderBottom: '1px solid var(--rule)', background: 'var(--paper-2)' }}>
            <span className="cap">{{ title: tr('Nom', 'Name'), topic: tr('Sujet', 'Topic'), voice_status: tr('Statut du vocal', 'Voice status'), user_limit: tr('Limite de personnes (0 = aucune)', 'People limit (0 = none)') }[fieldEdit.field]}</span>
            <input autoFocus value={fieldEdit.value} onChange={e => setFieldEdit({ ...fieldEdit, value: e.target.value })}
                   type={fieldEdit.field === 'user_limit' ? 'number' : 'text'} min={0} max={99}
                   maxLength={fieldEdit.field === 'topic' ? 1000 : fieldEdit.field === 'voice_status' ? 120 : 32}
                   onKeyDown={e => { if (e.key === 'Enter') saveField(); if (e.key === 'Escape') setFieldEdit(null) }} style={{ ...input, flex: 1 }} />
            <button type="button" className="btn sm" onClick={saveField}>{tr('Enregistrer', 'Save')}</button>
            <button type="button" className="btn ghost sm" onClick={() => setFieldEdit(null)}><X size={12} /></button>
          </div>
        )}
        {accessEdit && (
          <div style={{ padding: '6px 10px', borderBottom: '1px solid var(--rule)', background: 'var(--paper-2)' }}>
            <div className="cap" style={{ marginBottom: 4 }}>{accessEdit.kind === 'group'
              ? tr(`Qui voit le groupe ${accessEdit.name} (ses canaux sans acces propre suivent)`, `Who sees the group ${accessEdit.name} (its channels without their own follow)`)
              : tr(`Qui voit #${shownName(accessEdit.name)}`, `Who sees #${shownName(accessEdit.name)}`)}</div>
            {accessEdit.kind === 'channel' && groupAccess(accessEdit.name) && (
              <label className="cap" style={{ display: 'inline-flex', alignItems: 'center', gap: 4, marginBottom: 4 }}>
                <input type="checkbox" checked={!!accessEdit.inherit}
                       onChange={e => setAccessEdit({ ...accessEdit, inherit: e.target.checked, value: e.target.checked ? groupAccess(accessEdit.name) : accessEdit.value })} />
                {tr('Comme son groupe (synchronise)', 'Same as its group (synced)')}</label>
            )}
            {!accessEdit.inherit && <AccessPicker value={accessEdit.value} onChange={value => setAccessEdit({ ...accessEdit, value })} project={project} />}
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 4 }}>
              <span className="tp-note" style={{ flex: 1, color: 'var(--ink-4)' }}>
                {tr('Les leads et superviseurs voient tous les canaux. Visible dans FLUX seulement : le fichier du chat reste lisible sur le partage.',
                    'Leads and supervisors see every channel. FLUX visibility only: the chat file stays readable on the share.')}</span>
              <button type="button" className="btn sm" onClick={() => saveAccess(accessEdit)}>{tr('Enregistrer', 'Save')}</button>
              <button type="button" className="btn ghost sm" onClick={() => setAccessEdit(null)}><X size={12} /></button>
            </div>
          </div>
        )}
        {panel && (
          <div style={{ padding: '4px 10px', borderBottom: '1px solid var(--rule)', background: 'var(--paper-2)', maxHeight: 180, overflow: 'auto' }}>
            {pinned.length > 0 && <div className="cap" style={{ margin: '2px 0' }}>{tr('Epingles', 'Pinned')}</div>}
            {pinned.map(m => (
              <div key={m.id} onClick={() => goTo(m.id)} style={{ fontSize: 12, display: 'flex', gap: 6, alignItems: 'center', cursor: 'pointer', padding: '1px 0' }}>
                <Pin size={11} style={{ flex: 'none', color: 'var(--accent)' }} /><b>{m.user}</b>
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{m.message}</span>
              </div>
            ))}
            {threads.length > 0 && <div className="cap" style={{ margin: '4px 0 2px' }}>{tr('Fils actifs', 'Active threads')}</div>}
            {threads.map(({ m, n, last }) => (
              <div key={m.id} onClick={() => { setThread(m.id); setPanel(false) }} style={{ fontSize: 12, display: 'flex', gap: 6, alignItems: 'center', cursor: 'pointer', padding: '1px 0' }}>
                <MessageSquareReply size={11} style={{ flex: 'none', color: 'var(--accent)' }} />
                <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{postTitle(m)}</span>
                <span style={{ color: 'var(--ink-4)', fontSize: 11 }}>{n} · {last.date} {last.time}</span>
              </div>
            ))}
          </div>
        )}
        <div ref={listRef} onScroll={e => { const el = e.currentTarget; atBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40 }}
             style={{ flex: 1, overflow: 'auto', padding: '6px 4px' }}>
          {error && <div className="tp-note" style={{ color: 'var(--err)', padding: 8 }}>{error}</div>}
          {!roots.length && !error && <div className="tp-note" style={{ color: 'var(--ink-4)', padding: 12 }}>
            {forum ? tr('Aucun post. La premiere ligne d’un message est le titre du post.', 'No post yet. The first line of a message is the post title.')
                   : tr('Aucun message dans ce canal.', 'No message in this channel.')}</div>}
          {forum ? [...roots].reverse().map(m => (
            <div key={m.id} id={`team-msg-${m.id}`} onClick={() => setThread(m.id)}
                 style={{ margin: '4px 6px', padding: '6px 10px', border: '1px solid var(--rule)', borderRadius: 6, cursor: 'pointer',
                          background: thread === m.id || flash === m.id ? 'var(--paper-2)' : 'var(--paper)' }}>
              <b style={{ fontSize: 13 }}>{postTitle(m)}</b>
              <div style={{ display: 'flex', gap: 8, fontSize: 11, color: 'var(--ink-4)', marginTop: 2 }}>
                <span>{m.user}</span><span>{m.date} {m.time}</span><span style={{ flex: 1 }} />
                <span>{replies.get(m.id)?.length ?? 0} {tr('reponse(s)', 'reply(ies)')}</span>
              </div>
            </div>
          )) : roots.map(m => (
            <Message key={m.id} m={m} users={userSet} reacts={reactions.get(m.id)} replies={replies.get(m.id)?.length ?? 0} pinned={pins.has(m.id)}
                     lead={lead} project={project} filesDir={filesDir} onReact={react} onReply={() => setThread(m.id)} onPin={() => togglePin(m.id)}
                     me={me} onChanged={load} flash={flash === m.id} onCopyLink={() => copyLink(current, m.id)} />
          ))}
        </div>
        {locked
          ? <div className="tp-note" style={{ borderTop: '1px solid var(--rule)', padding: 10, color: 'var(--ink-4)' }}>
              {tr('Lecture seule : seuls les leads et superviseurs ecrivent ici. Tu peux reagir aux messages.', 'Read only: only leads and supervisors post here. You can react to messages.')}</div>
          : <Composer users={users} project={project}
                      placeholder={forum ? tr(`Nouveau post dans #${shownName(current)} : titre sur la premiere ligne (Maj+Entree)`, `New post in #${shownName(current)}: title on the first line (Shift+Enter)`)
                                         : tr(`Message dans #${shownName(current)} (@nom previent l’artiste)`, `Message in #${shownName(current)} (@name notifies)`)}
                      commands={commands} onCommand={text => runCommand(text)}
                      onSend={(message, attachments) => send({ message, attachments })} />}
      </div>

      {menu && (
        <div onMouseDown={e => e.stopPropagation()}
             style={{ position: 'fixed', left: menu.x, top: menu.y, zIndex: 80, minWidth: 180, padding: 4, background: 'var(--paper)',
                      border: '1px solid var(--rule-2)', borderRadius: 6, boxShadow: '0 2px 8px oklch(0% 0 0 / 0.2)', display: 'flex', flexDirection: 'column' }}>
          {menu.group ? <>
            <div className="cap" style={{ padding: '3px 8px' }}>{menu.group.name}</div>
            <MenuItem close={() => setMenu(null)} icon={<CheckCheck size={12} />} label={tr('Marquer comme lu', 'Mark as read')}
                      run={() => markRead(channels.sections.find(x => x.group?.rid === menu.group!.rid)?.names ?? [])} />
            <MenuItem close={() => setMenu(null)} icon={mutes.groups.includes(menu.group.rid) ? <Bell size={12} /> : <BellOff size={12} />}
                      label={mutes.groups.includes(menu.group.rid) ? tr('Reactiver les notifications', 'Unmute') : tr('Mettre en sourdine', 'Mute')}
                      run={() => toggleMute({ group: menu.group!.rid })} />
            {lead && <>
              <MenuItem close={() => setMenu(null)} icon={<Hash size={12} />} label={tr('Nouveau canal', 'New channel')} run={() => setNewChannel({ name: '', type: 'text', group: menu.group!.rid })} />
              <MenuItem close={() => setMenu(null)} icon={<Volume2 size={12} />} label={tr('Nouveau vocal', 'New voice channel')} run={() => setNewChannel({ name: '', type: 'voice', group: menu.group!.rid })} />
              <MenuItem close={() => setMenu(null)} icon={<Pencil size={12} />} label={tr('Renommer...', 'Rename...')} run={() => setGroupEdit({ rid: menu.group!.rid, name: menu.group!.name ?? '' })} />
              <MenuItem close={() => setMenu(null)} icon={<Eye size={12} />} label={tr('Qui voit ce groupe...', 'Who sees this group...')}
                        run={() => setAccessEdit({ value: accessOf(menu.group), kind: 'group', rid: menu.group!.rid, name: menu.group!.name ?? '' })} />
              <MenuItem close={() => setMenu(null)} icon={<Archive size={12} />} label={tr('Archiver le groupe', 'Archive the group')} title={tr('Ses canaux restent, sans groupe', 'Its channels stay, without a group')}
                        run={() => { const g = menu.group!; setAskArchive({ label: tr(`le groupe ${g.name}`, `the group ${g.name}`), note: tr('Ses canaux restent, sans groupe.', 'Its channels stay, without a group.'), run: () => void meta([{ op: 'put', rid: g.rid, fields: { archived: true } }]) }) }} />
            </>}
          </> : (() => {
            const name = menu.name
            const r = channels.byName.get(name)
            const general = name === GENERAL
            return <>
              <div className="cap" style={{ padding: '3px 8px' }}># {shownName(name)}</div>
              <MenuItem close={() => setMenu(null)} icon={<CheckCheck size={12} />} label={tr('Marquer comme lu', 'Mark as read')} run={() => markRead([name])} />
              <MenuItem close={() => setMenu(null)} icon={mutes.channels.includes(name) ? <Bell size={12} /> : <BellOff size={12} />}
                        label={mutes.channels.includes(name) ? tr('Reactiver les notifications', 'Unmute') : tr('Mettre en sourdine', 'Mute')}
                        title={tr('Plus de telephone ni de non-lus, sauf une @mention de toi', 'No phone nor unread count, except an @mention of you')}
                        run={() => toggleMute({ channel: name })} />
              <MenuItem close={() => setMenu(null)} icon={<Link2 size={12} />} label={tr('Copier le lien', 'Copy the link')} run={() => copyLink(name)} />
              {lead && <>
                <div style={{ borderTop: '1px solid var(--rule)', margin: '3px 0' }} />
                {!general && <MenuItem close={() => setMenu(null)} icon={<Pencil size={12} />} label={tr('Renommer...', 'Rename...')} run={() => editField(name, 'title')} />}
                {r?.type !== 'voice' && <MenuItem close={() => setMenu(null)} icon={<Pencil size={12} />} label={tr('Sujet...', 'Topic...')} run={() => editField(name, 'topic')} />}
                {!general && r?.type !== 'voice' && r?.type !== 'announcement' && (
                  <MenuItem close={() => setMenu(null)} icon={<Megaphone size={12} />} label={r?.read_only ? tr('Tout le monde peut ecrire', 'Everyone can post') : tr('Lecture seule (leads ecrivent)', 'Read only (leads post)')}
                            run={() => void meta([{ op: 'put', rid: r!.rid, fields: { read_only: r?.read_only ? null : true } }])} />
                )}
                {r?.type === 'voice' && <>
                  <MenuItem close={() => setMenu(null)} icon={<Users size={12} />} label={tr('Limite de personnes...', 'People limit...')} run={() => editField(name, 'user_limit')} />
                  <MenuItem close={() => setMenu(null)} icon={<Pencil size={12} />} label={tr('Statut du vocal...', 'Voice status...')} run={() => editField(name, 'voice_status')} />
                </>}
                {!general && (
                  <div style={{ display: 'flex', gap: 2, padding: '2px 4px' }}>
                    {TYPES.map(t => (
                      <button key={t} type="button" className="btn ghost sm" title={tr(TYPE_LABEL[t][0], TYPE_LABEL[t][1])}
                              style={{ background: (r?.type ?? 'text') === t ? 'var(--paper-2)' : undefined }}
                              onClick={() => { if ((r?.type ?? 'text') !== t) void meta([{ op: 'put', rid: r!.rid, fields: { type: t === 'text' ? null : t } }]); setMenu(null) }}>
                        <ChanIcon rec={{ type: t } as TeamRecord} /></button>
                    ))}
                  </div>
                )}
                {!general && <MenuItem close={() => setMenu(null)} icon={<Copy size={12} />} label={tr('Dupliquer', 'Duplicate')} title={tr('Meme type, groupe, acces, sujet ; sans les messages', 'Same type, group, access, topic; no messages')} run={() => duplicate(name)} />}
                {!general && <MenuItem close={() => setMenu(null)} icon={<Eye size={12} />} label={tr('Qui voit ce canal...', 'Who sees this channel...')} run={() => editAccess(name)} />}
                {!general && <MenuItem close={() => setMenu(null)} icon={<Archive size={12} />} label={tr('Archiver', 'Archive')}
                          run={() => setAskArchive({ label: `#${shownName(name)}`, note: tr('Les messages restent. Il revient depuis Projets > Archives du projet ; un nouveau canal du meme nom part vierge.', 'Messages stay. It comes back from Projects > Archived; a new channel with the same name starts empty.'), run: () => { void meta([{ op: 'put', rid: r!.rid, fields: { archived: true } }]); if (current === name) setChannel(GENERAL) } })} />}
              </>}
            </>
          })()}
        </div>
      )}

      {askArchive && (
        <div onMouseDown={() => setAskArchive(null)}
             style={{ position: 'absolute', inset: 0, zIndex: 90, background: 'oklch(0% 0 0 / 0.35)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div onMouseDown={e => e.stopPropagation()}
               style={{ width: 320, padding: 14, background: 'var(--paper)', border: '1px solid var(--rule-2)', borderRadius: 8, boxShadow: '0 4px 16px oklch(0% 0 0 / 0.25)' }}>
            <b style={{ fontSize: 13 }}>{tr(`Archiver ${askArchive.label} ?`, `Archive ${askArchive.label}?`)}</b>
            <div className="tp-note" style={{ color: 'var(--ink-3)', margin: '6px 0 12px' }}>
              {askArchive.note ?? tr('Les messages restent. Il revient depuis Projets > Archives du projet ; un nouveau canal du meme nom part vierge.', 'Messages stay. It comes back from Projects > Archived; a new channel with the same name starts empty.')}</div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 6 }}>
              <button type="button" className="btn ghost sm" autoFocus onClick={() => setAskArchive(null)}>{tr('Annuler', 'Cancel')}</button>
              <button type="button" className="btn sm" onClick={() => { askArchive.run(); setAskArchive(null) }}><Archive size={12} /> {tr('Archiver', 'Archive')}</button>
            </div>
          </div>
        </div>
      )}

      {/* thread */}
      {root && (
        <div style={{ width: 300, flex: 'none', borderLeft: '1px solid var(--rule)', display: 'flex', flexDirection: 'column' }}>
          <div style={{ display: 'flex', alignItems: 'center', padding: '6px 10px', borderBottom: '1px solid var(--rule)' }}>
            <b style={{ fontSize: 12.5, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{forum ? postTitle(root) : tr('Fil', 'Thread')}</b><span style={{ flex: 1 }} />
            <button type="button" className="btn ghost sm" onClick={() => setThread(null)}><X size={12} /></button>
          </div>
          <div style={{ flex: 1, overflow: 'auto', padding: '6px 4px' }}>
            <Message m={root} users={userSet} reacts={reactions.get(root.id)} replies={0} pinned={pins.has(root.id)} lead={lead}
                     project={project} filesDir={filesDir} onReact={react} onPin={() => togglePin(root.id)} me={me} onChanged={load} />
            <div style={{ borderTop: '1px solid var(--rule)', margin: '4px 8px' }} />
            {(replies.get(root.id) ?? []).map(r => (
              <Message key={r.id} m={r} users={userSet} reacts={reactions.get(r.id)} replies={0} pinned={false} lead={false}
                       project={project} filesDir={filesDir} onReact={react} me={me} moderator={lead} onChanged={load}
                       flash={flash === r.id} onCopyLink={() => copyLink(current, r.id)} />
            ))}
          </div>
          {locked
            ? <div className="tp-note" style={{ borderTop: '1px solid var(--rule)', padding: 10, color: 'var(--ink-4)' }}>{tr('Lecture seule', 'Read only')}</div>
            : <Composer users={users} project={project} placeholder={tr('Repondre dans le fil', 'Reply in the thread')}
                        commands={commands} onCommand={text => runCommand(text, root.id)}
                        onSend={(message, attachments) => send({ message, attachments, reply_to: root.id })} />}
        </div>
      )}
    </div>
  )
}

// Edit / delete (ADR 0084): the author edits and deletes, a lead deletes any message.
// "(modifie)" marks an edited message.
function Message({ m, users, reacts, replies, pinned, lead, project, filesDir, onReact, onReply, onPin, me, moderator, onChanged, flash, onCopyLink }: {
  m: TeamMessage; users: Set<string>; reacts?: Map<TeamEmoji, { n: number; mine?: TeamRecord; who: string[] }>
  replies: number; pinned: boolean; lead: boolean; project: string; filesDir: string
  onReact: (msg: string, e: TeamEmoji) => void; onReply?: () => void; onPin?: () => void
  me?: string; moderator?: boolean; onChanged?: () => void
  flash?: boolean; onCopyLink?: () => void   // opened from a chat link: scrolled to and highlighted
}) {
  const { tr } = useTr()
  const [hover, setHover] = useState(false)
  const [edit, setEdit] = useState<string | null>(null)
  const [askDelete, setAskDelete] = useState(false)
  const mine = !!me && m.user.toUpperCase() === me.toUpperCase()
  const canDelete = mine || lead || !!moderator
  const saveEdit = () => {
    if (edit === null) return
    const text = edit.trim()
    if (!text || text === m.message) { setEdit(null); return }
    teamApi.editMessage(project, m.id, text).then(() => { setEdit(null); onChanged?.() }).catch(fail)
  }
  const remove = () => { setAskDelete(false); teamApi.deleteMessage(project, m.id).then(() => onChanged?.()).catch(fail) }
  const open = (a: TeamAttachment) => { if (filesDir && window.electronAPI?.openPath) void window.electronAPI.openPath(`${filesDir}/${a.file}`); else window.open(teamApi.fileUrl(project, a.file), '_blank') }
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => { if (flash) ref.current?.scrollIntoView({ block: 'center', behavior: 'smooth' }) }, [flash])
  return (
    <div ref={ref} id={`team-msg-${m.id}`} onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
         style={{ position: 'relative', padding: '5px 8px', borderRadius: 6, background: hover || flash ? 'var(--paper-2)' : undefined,
                  boxShadow: flash ? 'inset 3px 0 0 var(--accent)' : undefined }}>
      <div style={{ display: 'flex', gap: 6, alignItems: 'baseline', fontSize: 12 }}>
        <b>{m.user}</b>
        {m.via && <span style={{ color: 'var(--ink-4)', fontSize: 11 }}>{tr(`pour ${m.via}`, `for ${m.via}`)}</span>}<span style={{ color: 'var(--ink-4)', fontSize: 11 }}>{m.date} {m.time}</span>
        {m.edited && <span style={{ color: 'var(--ink-4)', fontSize: 11 }} title={m.edited}>{tr('(modifie)', '(edited)')}</span>}
        {pinned && <Pin size={10} style={{ color: 'var(--accent)' }} />}
      </div>
      {edit !== null
        ? <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <textarea value={edit} autoFocus rows={Math.min(6, edit.split('\n').length + 1)} onChange={e => setEdit(e.target.value)}
                      onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); saveEdit() } if (e.key === 'Escape') setEdit(null) }}
                      style={{ fontSize: 13, padding: 6, border: '1px solid var(--rule-2)', borderRadius: 5, background: 'var(--bg-deep)', color: 'var(--ink)', resize: 'vertical' }} />
            <span className="tp-note" style={{ color: 'var(--ink-4)' }}>{tr('Entree : enregistrer, Echap : annuler', 'Enter: save, Esc: cancel')}</span>
          </div>
        : <div style={{ fontSize: 13, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}><Text text={m.message} users={users} /></div>}
      {askDelete && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, marginTop: 3 }}>
          {tr('Supprimer ce message ?', 'Delete this message?')}
          <button type="button" className="btn sm" onClick={remove}>{tr('Supprimer', 'Delete')}</button>
          <button type="button" className="btn ghost sm" onClick={() => setAskDelete(false)}>{tr('Annuler', 'Cancel')}</button>
        </div>
      )}
      {!!m.attachments?.length && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 4 }}>
          {m.attachments.map(a => a.image
            ? <img key={a.file} src={teamApi.fileUrl(project, a.file)} alt={a.name} title={a.name} onClick={() => open(a)} loading="lazy"
                   style={{ maxWidth: 220, maxHeight: 160, borderRadius: 6, border: '1px solid var(--rule)', cursor: 'pointer' }} />
            : VIDEO_RE.test(a.file)
            ? <span key={a.file} style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                {/* Seeking relies on HTTP Range: the backend FileResponse (Starlette) answers it. */}
                <video src={teamApi.fileUrl(project, a.file)} controls preload="metadata" title={a.name}
                       style={{ maxWidth: 320, maxHeight: 240, borderRadius: 6, border: '1px solid var(--rule)', background: '#000' }} />
                <button type="button" className="btn ghost sm" onClick={() => open(a)}><Paperclip size={11} /> {a.name} ({sizeTxt(a.size)})</button>
              </span>
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
          {onCopyLink && <button type="button" title={tr('Copier le lien du message', 'Copy the message link')} onClick={onCopyLink} style={iconBtn}><Link2 size={12} /></button>}
          {mine && edit === null && <button type="button" title={tr('Modifier', 'Edit')} onClick={() => setEdit(m.message)} style={iconBtn}><Pencil size={12} /></button>}
          {canDelete && <button type="button" title={tr('Supprimer', 'Delete')} onClick={() => setAskDelete(true)} style={iconBtn}><Trash2 size={12} /></button>}
        </div>
      )}
    </div>
  )
}

function MenuItem({ icon, label, title, run, close }: { icon: React.ReactNode; label: string; title?: string; run: () => void; close: () => void }) {
  return <button type="button" className="btn ghost sm" style={{ justifyContent: 'flex-start' }} title={title}
                 onClick={() => { run(); close() }}>{icon} {label}</button>
}

function Composer({ users, project, placeholder, commands, onCommand, onSend }: {
  users: string[]; project: string; placeholder: string; commands: TeamCommand[]
  onCommand: (text: string) => Promise<void>; onSend: (message: string, attachments: TeamAttachment[]) => Promise<void>
}) {
  const { tr } = useTr()
  const [text, setText] = useState('')
  const [files, setFiles] = useState<TeamAttachment[]>([])
  const [busy, setBusy] = useState(false)
  const [asking, setAsking] = useState<string | null>(null)   // a command with confirm, waiting for Lancer
  const at = /@([A-Za-z0-9_.-]*)$/.exec(text)
  // A name already typed in full is not suggested again (Enter then sends).
  const suggest = at && !users.some(u => u.toUpperCase() === at[1].toUpperCase())
    ? users.filter(u => u.toUpperCase().startsWith(at[1].toUpperCase())).slice(0, 6) : []
  // `/` at the start: the commands of the channel (one line per name, several flows may answer it).
  const names = useMemo(() => [...new Map(commands.map(c => [c.name, c])).values()], [commands])
  const slash = /^\/([A-Za-z0-9_-]*)$/.exec(text)
  const cmdSuggest = slash && !names.some(c => c.name === slash[1].toLowerCase())
    ? names.filter(c => c.name.startsWith(slash[1].toLowerCase())).slice(0, 8) : []
  const typed = COMMAND_RE.exec(text)
  const typedCmd = typed ? names.find(c => c.name === typed[1].toLowerCase()) : undefined
  const runCmd = async (line: string) => {
    setBusy(true)
    try { await onCommand(line); setText(''); setAsking(null) } catch (err) { fail(err) } finally { setBusy(false) }
  }
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
    if (typed) {
      if (!typedCmd) { toast.error(tr(`Commande /${typed[1]} inconnue dans ce canal (un espace devant envoie le texte tel quel).`, `Unknown command /${typed[1]} in this channel (a leading space sends the text as is).`)); return }
      if (files.length) { toast.error(tr('Une commande ne prend pas de fichier joint.', 'A command takes no attached file.')); return }
      if (typedCmd.confirm) { setAsking(msg); return }
      await runCmd(msg)
      return
    }
    setBusy(true)
    try { await onSend(msg || files.map(f => f.name).join(', '), files); setText(''); setFiles([]) } catch (err) { fail(err) } finally { setBusy(false) }
  }
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      if (suggest.length && at) { setText(text.slice(0, at.index) + `@${suggest[0]} `); return }
      if (cmdSuggest.length) { setText(`/${cmdSuggest[0].name} `); return }
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
                                 @{u}</div>)}
        </div>
      )}
      {cmdSuggest.length > 0 && (
        <div style={{ position: 'absolute', bottom: '100%', left: 8, maxWidth: 420, background: 'var(--paper)', border: '1px solid var(--rule)', borderRadius: 6, boxShadow: '0 2px 8px oklch(0% 0 0 / 0.15)', zIndex: 3 }}>
          {cmdSuggest.map(c => <div key={c.name} onMouseDown={e => { e.preventDefault(); setText(`/${c.name} `) }}
                                    style={{ display: 'flex', alignItems: 'baseline', gap: 8, padding: '4px 10px', fontSize: 12, cursor: 'pointer' }}>
                                    <b>/{c.name}</b><span style={{ color: 'var(--ink-3)' }}>{c.help}</span></div>)}
        </div>
      )}
      {typedCmd && !asking && (
        <div style={{ fontSize: 11, color: 'var(--ink-3)', marginBottom: 4 }}>
          <b>/{typedCmd.name}</b> {typedCmd.help} <span style={{ color: 'var(--ink-4)' }}>
            {tr(`(flow ${typedCmd.label}, lance sur ce poste)`, `(flow ${typedCmd.label}, runs on this workstation)`)}</span>
        </div>
      )}
      {asking && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, marginBottom: 6 }}>
          <span style={{ flex: 1, wordBreak: 'break-all' }}>{tr(`Lancer ${asking} ?`, `Run ${asking}?`)}</span>
          <button type="button" className="btn sm" disabled={busy} onClick={() => { void runCmd(asking) }}>{tr('Lancer', 'Run')}</button>
          <button type="button" className="btn ghost sm" onClick={() => setAsking(null)}>{tr('Annuler', 'Cancel')}</button>
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
        <textarea value={text} onChange={e => { setText(e.target.value); setAsking(null) }} onKeyDown={onKey} rows={2} placeholder={placeholder}
                  style={{ ...input, flex: 1, height: 'auto', resize: 'none', padding: 6, fontFamily: 'inherit' }} />
        <button type="button" className="btn sm" disabled={busy || (!text.trim() && !files.length)} onClick={() => { void submit() }}><Send size={13} /></button>
      </div>
    </div>
  )
}

const input: React.CSSProperties = { height: 26, padding: '0 8px', border: '1px solid var(--rule-2)', background: 'var(--bg-deep)', borderRadius: 5, fontSize: 12, color: 'var(--ink)', minWidth: 0 }
const iconBtn: React.CSSProperties = { border: 'none', background: 'transparent', padding: '1px 3px', cursor: 'pointer', color: 'inherit', display: 'inline-flex', alignItems: 'center', fontSize: 13 }
const chip: React.CSSProperties = { fontSize: 11, lineHeight: '16px', padding: '0 6px', borderRadius: 8, cursor: 'pointer', color: 'var(--ink)', background: 'var(--paper)' }
