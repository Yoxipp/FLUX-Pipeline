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
}

export interface NotifyBot {
  configured: boolean
  name?: string
  host?: string              // PC that holds the token (never the token itself)
  hosted_here?: boolean
  online?: boolean
  invite_url?: string
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
  removeBot: (project: string) => apiCall<{ bot: NotifyBot }>('DELETE', `/notify/project/${enc(project)}/bot`),
}
