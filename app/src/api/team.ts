// team.ts - chat TOOL widget (ADR 0077, 0091): the project team chat with channels, threads
// and files, channels / reactions / pins (per author journals).
// Messages go through /activity/chat.

import { BASE_URL, apiCall } from './client'
import type { PageDataOp, PageRecord } from '../pages/flow_editor/types'

export interface TeamAttachment { name: string; file: string; size: number; image: boolean }
export interface TeamMessage {
  id: string; user: string; message: string; date: string; time: string
  channel?: string; reply_to?: string; attachments?: TeamAttachment[]
  via?: string   // a FLUX answer to a chat command: the artist who typed it (ADR 0081)
  edited?: string   // date time of the last edit (ADR 0084)
}
export type TeamEmoji = 'like' | 'love' | 'laugh' | 'question' | 'check'
export interface TeamRecord extends PageRecord {
  kind?: 'channel' | 'group' | 'reaction' | 'pin'
  name?: string; topic?: string; archived?: boolean
  title?: string | null   // channel: name shown when the key has a suffix (lighting-2 shows lighting)
  access?: string | null   // who sees the channel: JSON {users, roles}, empty = everyone
  type?: TeamChannelType | null    // channel type (ADR 0084)
  read_only?: boolean | null       // channel: only leads / supervisors post (P5)
  user_limit?: number | null       // voice channel: people at most, 0 = no limit
  voice_status?: string | null     // voice channel: what is going on, one line
  group?: string | null            // channel: rid of its group (a Discord category)
  order?: number | null            // channel / group: position, lower first
  target?: string; emoji?: TeamEmoji
}
export type TeamChannelType = 'text' | 'voice' | 'forum' | 'announcement'
export interface TeamMutes { channels: string[]; groups: string[] }
export type TeamMetaRead =
  | { etag: string; unchanged: true; lead: boolean; files_dir: string }
  | { etag: string; unchanged: false; records: TeamRecord[]; lead: boolean; files_dir: string }

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
  editMessage: (project: string, id: string, message: string) =>
    apiCall<{ success: boolean }>('PATCH', `/activity/chat/${encodeURIComponent(id)}`, { project, message }),
  deleteMessage: (project: string, id: string) =>
    apiCall<{ success: boolean }>('DELETE', `/activity/chat/${encodeURIComponent(id)}?project=${p(project)}`),
  // Muted channels / groups of this artist (P5): kept in USER/<artist>/team_mutes.json.
  mutes: (project: string) => apiCall<TeamMutes>('GET', `/team/${p(project)}/mutes`),
  setMutes: (project: string, mutes: TeamMutes) => apiCall<TeamMutes>('PUT', `/team/${p(project)}/mutes`, mutes),
}
