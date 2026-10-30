// notify.ts - phone notifications (ADR 0062): Discord webhook per project, ntfy topic per person.
// Secrets come back masked ("****" + 4 chars); sending the mask back keeps the stored value.

import { apiCall } from './client'

export type NotifyChannel = 'none' | 'discord' | 'ntfy'

export interface NotifyPrefs {
  channel: NotifyChannel
  discord_id: string
  ntfy_topic: string
  ntfy_url: string           // server + topic, for the QR code (owner only)
}

export interface NotifyMe {
  user: string
  prefs: NotifyPrefs
  project_has_webhook: boolean
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
}

export interface NotifyProject {
  settings: NotifyProjectSettings
  without_channel: string[]
  can_edit: boolean
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
}
