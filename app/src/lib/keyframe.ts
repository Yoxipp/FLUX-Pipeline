// keyframe.ts — open pipeline videos in Keyframe Pro (retake 09).
//
// The backend (features/review/keyframe.py) picks the way in: the external API
// of a licensed Keyframe Pro (whole edit in one timeline + the other videos of
// the folder), else the command line (first video only, demo mode included).
// Here: one call, the toasts, and the last fallback when Keyframe is absent
// (the system player through Electron).

import { toast } from 'sonner'
import { api, type KeyframeOpenResult } from '../api/client'

export interface KeyframeItem {
  rel_path?: string     // project-relative file
  path?: string         // or absolute, inside the project
  label?: string        // shown as the source name in Keyframe
}

export async function openInKeyframe(project: string, items: KeyframeItem[], opts: {
  title?: string
  siblings?: boolean
  fallbackPath?: string   // absolute file for the system player when Keyframe is absent
} = {}): Promise<KeyframeOpenResult | null> {
  if (!project || items.length === 0) { toast.error('Aucune vidéo à ouvrir'); return null }
  const pending = toast.loading('Ouverture dans Keyframe Pro…')
  try {
    const res = await api.keyframeOpen(project, items, opts.title ?? 'FLUX', opts.siblings ?? true)
    const skipped = res.skipped.length
      ? ` · ${res.skipped.length} ignorée${res.skipped.length > 1 ? 's' : ''} (${[...new Set(res.skipped.map(s => s.reason))].join(', ')})`
      : ''
    if (res.mode === 'api') {
      const sib = res.siblings ? ` + ${res.siblings} du même dossier` : ''
      toast.success(`Keyframe Pro : ${res.opened.length} vidéo${res.opened.length > 1 ? 's' : ''}${sib}${skipped}`, { duration: 5000 })
    } else if (res.mode === 'cli') {
      toast.warning(`Keyframe ouvert en ligne de commande. ${res.message}${skipped}`, { duration: 9000 })
    } else if (res.code === 'not_installed' && opts.fallbackPath && window.electronAPI?.openPath) {
      await window.electronAPI.openPath(opts.fallbackPath)
      toast.warning(`${res.message} : ouvert dans le lecteur du système`, { duration: 7000 })
    } else {
      toast.error(`${res.message}${skipped}`, { duration: 8000 })
    }
    return res
  } catch (e) {
    toast.error(`Keyframe Pro : ${e instanceof Error ? e.message : 'erreur d’ouverture'}`)
    return null
  } finally {
    toast.dismiss(pending)
  }
}
