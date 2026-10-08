// activityNotify.ts - activity event categories and which ones notify the artist (ADR 0043).
// Pure module, shared by the Activity page (filters) and the app shell (toasts).

import type { WorkPrefs } from './workProfiles'

export type ActivityType = 'publish' | 'import' | 'update' | 'error' | 'mention' | 'comment'

export function actionToType(action: string): ActivityType {
  const a = action.toLowerCase()
  if (a.includes('comment'))                                          return 'comment'
  if (a.includes('publish') || a.includes('export'))                  return 'publish'
  if (a.includes('import'))                                           return 'import'
  if (a.includes('error') || a.includes('fail'))                      return 'error'
  if (a.includes('update') || a.includes('install') || a.includes('connect')) return 'update'
  return 'publish'
}

export type NotifyReason = 'followed' | 'publish' | 'comment' | 'error'

/** Why the backend says an event concerns the artist (GET /activity/notifications). */
export const REASON_LABEL: Record<'followed_shot' | 'favorite' | 'assigned', string> = {
  followed_shot: 'shot suivi',
  favorite:      'tâche favorite',
  assigned:      'tâche assignée',
}

/**
 * Why an activity event pops a notification, or null. `followed` = the backend gave the
 * event a personal reason (followed shot, favorite or assigned task, any author);
 * project-wide categories only count other artists' events of the active project, so
 * nothing leaks across projects.
 */
export function notificationReason(
  event: { user: string; action: string; project?: string },
  ctx: { prefs: Pick<WorkPrefs, 'notifyFollowed' | 'notifyPublish' | 'notifyComment' | 'notifyError'>; followed: boolean; username: string; project: string },
): NotifyReason | null {
  if (ctx.followed && ctx.prefs.notifyFollowed) return 'followed'
  if (!event.project || event.project !== ctx.project) return null
  if (event.user.toUpperCase() === ctx.username.toUpperCase()) return null
  const type = actionToType(event.action)
  if (type === 'publish' && ctx.prefs.notifyPublish) return 'publish'
  if (type === 'comment' && ctx.prefs.notifyComment) return 'comment'
  if (type === 'error' && ctx.prefs.notifyError) return 'error'
  return null
}
