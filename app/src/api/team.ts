// team.ts - Team page (ADR 0077): the project team chat with channels, threads and files,
// channels / reactions / pins (per author journals), presence (one file per artist).
// Messages go through /activity/chat (the same chat as the home page).

import { BASE_URL, apiCall } from './client'
import type { PageDataOp, PageRecord } from '../pages/flow_editor/types'

export interface TeamAttachment { name: string; file: string; size: number; image: boolean }
export interface TeamMessage {
  id: string; user: string; message: string; date: string; time: string
  channel?: string; reply_to?: string; attachments?: TeamAttachment[]
}
export type TeamEmoji = 'like' | 'love' | 'laugh' | 'question' | 'check'
export interface TeamRecord extends PageRecord {
  kind?: 'channel' | 'reaction' | 'pin'
  name?: string; topic?: string; call_link?: string; archived?: boolean
  target?: string; emoji?: TeamEmoji
}
export type TeamMetaRead =
  | { etag: string; unchanged: true; lead: boolean; files_dir: string }
  | { etag: string; unchanged: false; records: TeamRecord[]; lead: boolean; files_dir: string }
export type PresenceStatus = 'available' | 'away' | 'meeting' | 'dnd'
export interface Presence { user: string; status: PresenceStatus | 'offline'; text: string; at: string; online: boolean }

const p = (project: string) => encodeURIComponent(project)

export const teamApi = {
  messages: (project: string, limit = 500) =>
    apiCall<{ messages: TeamMessage[]; users: string[] }>('GET', `/activity/chat?project=${p(project)}&limit=${limit}`),
  send: (project: string, body: { message: string; channel?: string; reply_to?: string; attachments?: TeamAttachment[]; notify_all?: boolean }) =>
    apiCall<{ success: boolean }>('POST', '/activity/chat', { project, ...body }),
  meta: (project: string, etag?: string) =>
    apiCall<TeamMetaRead>('GET', `/team/${p(project)}/meta${etag ? `?etag=${encodeURIComponent(etag)}` : ''}`),
  writeMeta: (project: string, ops: PageDataOp[]) =>
    apiCall<{ rids: string[]; etag: string }>('POST', `/team/${p(project)}/meta`, { ops }),
  // The backend copies the local file (bytes never go through the API, ADR 0005).
  attach: (project: string, path: string) => apiCall<TeamAttachment>('POST', `/team/${p(project)}/files`, { path }),
  fileUrl: (project: string, file: string) => `${BASE_URL}/team/${p(project)}/files/${encodeURIComponent(file)}`,
  presence: () => apiCall<{ people: Presence[] }>('GET', '/team/presence'),
  setPresence: (status: PresenceStatus, text = '') => apiCall<{ status: string }>('POST', '/team/presence', { status, text }),
}

// -- presence of this artist (kept on this machine, re-sent every minute by the app shell) --
const KEY = 'flux.presence'
export function myPresence(): { status: PresenceStatus; text: string } {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) || '{}')
    return { status: ['available', 'away', 'meeting', 'dnd'].includes(v.status) ? v.status : 'available', text: String(v.text || '') }
  } catch { return { status: 'available', text: '' } }
}
export function setMyPresence(status: PresenceStatus, text = '') {
  try { localStorage.setItem(KEY, JSON.stringify({ status, text })) } catch { /* private mode */ }
  window.dispatchEvent(new Event('flux:presence'))
  return teamApi.setPresence(status, text).catch(() => undefined)
}
