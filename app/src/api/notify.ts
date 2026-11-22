// notify.ts - Discord notifications (ADR 0062, 0073, 0091): bot DMs for linked accounts, the
// project webhook as fallback while the bot is offline. The webhook comes back masked
// ("****" + 4 chars); sending the mask back keeps the stored value.

import { apiCall } from './client'

export type NotifyChannel = 'none' | 'discord'
/** Event types a person can turn off (ADR 0091), as backend events.EVENT_TYPES. */
export type NotifyType = 'mention' | 'task' | 'retake' | 'calendar' | 'publish'

export interface NotifyPrefs {
  channel: NotifyChannel
  discord_id: string
  discord_linked_at: string  // set by a /link code (ADR 0073), '' when typed by hand
  discord_name: string       // Discord display name given with the /link code, '' when unknown
  muted: NotifyType[]        // types this person does not receive
}

export interface NotifyMe {
  user: string
  prefs: NotifyPrefs
  project_has_webhook: boolean
  project_has_bot: boolean
  discord_linked: boolean
  has_channel: boolean
}

export interface NotifyProjectSettings {
  discord_webhook: string    // masked
  has_webhook: boolean
  digest_minutes: number
  include_project: boolean
  include_text: boolean      // chat message / calendar title in the text (ADR 0072)
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
  setMe: (patch: { channel?: NotifyChannel; discord_id?: string; muted?: NotifyType[] }, project?: string | null) =>
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
