// previewSourceStore.ts — the preview source (Auto, Tout, SB, animatique, ...) shared by the
// Timeline (ProductionShot) and the Production table thumbnails (retake B5, ADR 0047 amendment).
// One localStorage key + a window event so every mounted view follows the last choice.

import { useCallback, useEffect, useState } from 'react'
import { isOrigin, type PreviewOrigin, type PreviewSource } from './previewEdit'

export const LS_PREVIEW_SOURCE = 'flux.production.timeline.previewSource'
const EVENT = 'flux:preview-source-change'

export function readPreviewSource(): PreviewSource {
  try { return localStorage.getItem(LS_PREVIEW_SOURCE) || 'auto' } catch { return 'auto' }
}

export function writePreviewSource(source: PreviewSource): void {
  try { localStorage.setItem(LS_PREVIEW_SOURCE, source) } catch { /* storage blocked */ }
  window.dispatchEvent(new CustomEvent<PreviewSource>(EVENT, { detail: source }))
}

// A /ref zone changed (deposit, delete, restore): Timeline views refetch their previews at once.
export const REF_CHANGE_EVENT = 'flux:ref-change'
export function notifyRefChange(): void {
  window.dispatchEvent(new CustomEvent(REF_CHANGE_EVENT))
}

// Global origin (Auto = ref if present else publish, Ref, Publish): same mechanism.
export const LS_PREVIEW_ORIGIN = 'flux.production.timeline.previewOrigin'
const ORIGIN_EVENT = 'flux:preview-origin-change'

export function readPreviewOrigin(): PreviewOrigin {
  try {
    const v = localStorage.getItem(LS_PREVIEW_ORIGIN)
    return isOrigin(v) ? v : 'auto'
  } catch { return 'auto' }
}

export function writePreviewOrigin(origin: PreviewOrigin): void {
  try { localStorage.setItem(LS_PREVIEW_ORIGIN, origin) } catch { /* storage blocked */ }
  window.dispatchEvent(new CustomEvent<PreviewOrigin>(ORIGIN_EVENT, { detail: origin }))
}

export function usePreviewOrigin(): [PreviewOrigin, (origin: PreviewOrigin) => void] {
  const [origin, setOrigin] = useState<PreviewOrigin>(readPreviewOrigin)
  useEffect(() => {
    const onChange = (e: Event) => setOrigin((e as CustomEvent<PreviewOrigin>).detail ?? readPreviewOrigin())
    window.addEventListener(ORIGIN_EVENT, onChange)
    return () => window.removeEventListener(ORIGIN_EVENT, onChange)
  }, [])
  const update = useCallback((next: PreviewOrigin) => { setOrigin(next); writePreviewOrigin(next) }, [])
  return [origin, update]
}

export function usePreviewSource(): [PreviewSource, (source: PreviewSource) => void] {
  const [source, setSource] = useState<PreviewSource>(readPreviewSource)
  useEffect(() => {
    const onChange = (e: Event) => setSource((e as CustomEvent<PreviewSource>).detail ?? readPreviewSource())
    window.addEventListener(EVENT, onChange)
    return () => window.removeEventListener(EVENT, onChange)
  }, [])
  const update = useCallback((next: PreviewSource) => { setSource(next); writePreviewSource(next) }, [])
  return [source, update]
}
