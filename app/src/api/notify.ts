// notify.ts - phone notifications (ADR 0062): Discord webhook per project, ntfy topic per person.
// Secrets come back masked ("****" + 4 chars); sending the mask back keeps the stored value.

import { apiCall } from './client'

export type NotifyChannel = 'none' | 'discord' | 'ntfy'

export interface NotifyPrefs {
  channel: NotifyChannel
  discord_id: string
  ntfy_topic: string
  ntfy_url: string           // server + topic, for the QR code (owner only)
  discord_linked_at: string  // set by a /link code (ADR 0073), '' when typed by hand
}

export interface NotifyMe {
  user: string
  prefs: NotifyPrefs
  project_has_webhook: boolean
  project_has_bot: boolean
  discord_linked: boolean
  has_channel: boolean
  ntfy_sent_today: number
  ntfy_limit: number
  warn: boolean
}

export interface NotifyProjectSettings {
  discord_webhook: string    // masked
  has_webhook: boolean
  ntfy_server: string
  digest_minutes: number
  include_project: boolean
  include_text: boolean      // chat message / calendar title in the text (ADR 0072)
  discord_sync: boolean      // live Team <-> Discord server bridge (ADR 0084)
  discord_guild: string      // the project's Discord server id, '' = the only server the bot is on
}

export interface NotifyBridge {
  at: string                 // last pass of the bridge on the host
  error: string
  guild: string              // server in use
  guilds: string[]           // servers the bot is on
}

export interface NotifyBot {
  configured: boolean
  name?: string
  host?: string              // PC answering now, else the first that registered it (never the token itself)
  hosted_here?: boolean      // the token is on this PC (host or ready to take over, ADR 0082)
  online?: boolean
  is_host?: boolean          // this FLUX holds the project lock right now
  this_pc?: string
  candidates?: string[]      // other PCs ready to take over
  invite_url?: string
  background?: boolean       // this PC keeps its bots online when FLUX is closed (ADR 0076)
  runs_in?: '' | 'app' | 'headless'
  bridge?: NotifyBridge
}

export interface NotifyProject {
  settings: NotifyProjectSettings
  without_channel: string[]
  can_edit: boolean
  bot: NotifyBot
}

const enc = encodeURIComponent
const q = (project: string | null | undefined) => (project ? `?project=${enc(project)}` : '')

export const notifyApi = {
  me: (project?: string | null) => apiCall<NotifyMe>('GET', `/notify/me${q(project)}`),
  setMe: (patch: { channel?: NotifyChannel; discord_id?: string; regenerate_topic?: boolean }, project?: string | null) =>
    apiCall<{ prefs: NotifyPrefs; has_channel: boolean }>('PUT', `/notify/me${q(project)}`, patch),
  test: (project?: string | null) =>
    apiCall<{ ok: boolean; status?: number; reason?: string; channel?: NotifyChannel }>('POST', `/notify/me/test${q(project)}`),
  project: (project: string) => apiCall<NotifyProject>('GET', `/notify/project/${enc(project)}`),
  setProject: (project: string, patch: Partial<Omit<NotifyProjectSettings, 'has_webhook'>>) =>
    apiCall<{ settings: NotifyProjectSettings }>('PUT', `/notify/project/${enc(project)}`, patch),
  linkDiscord: (code: string, project: string) =>
    apiCall<{ prefs: NotifyPrefs; has_channel: boolean }>('POST', `/notify/me/discord_link${q(project)}`, { code }),
  setBot: (project: string, token: string) =>
    apiCall<{ bot: NotifyBot }>('PUT', `/notify/project/${enc(project)}/bot`, { token }),
  removeBot: (project: string, thisPcOnly = false) =>
    apiCall<{ bot: NotifyBot }>('DELETE', `/notify/project/${enc(project)}/bot${thisPcOnly ? '?this_pc_only=true' : ''}`),
  setBotBackground: (project: string, enabled: boolean) =>
    apiCall<{ bot: NotifyBot }>('PUT', `/notify/project/${enc(project)}/bot/background`, { enabled }),
}
