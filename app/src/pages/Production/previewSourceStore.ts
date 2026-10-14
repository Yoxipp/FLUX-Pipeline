// previewSourceStore.ts — the preview source (Auto, Tout, SB, animatique, ...) shared by the
// Timeline (ProductionShot) and the Production table thumbnails (retake B5, ADR 0047 amendment).
// One localStorage key + a window event so every mounted view follows the last choice.

import { useCallback, useEffect, useState } from 'react'
import type { PreviewSource } from './previewEdit'

export const LS_PREVIEW_SOURCE = 'flux.production.timeline.previewSource'
const EVENT = 'flux:preview-source-change'

export function readPreviewSource(): PreviewSource {
  try { return localStorage.getItem(LS_PREVIEW_SOURCE) || 'auto' } catch { return 'auto' }
}

export function writePreviewSource(source: PreviewSource): void {
  try { localStorage.setItem(LS_PREVIEW_SOURCE, source) } catch { /* storage blocked */ }
  window.dispatchEvent(new CustomEvent<PreviewSource>(EVENT, { detail: source }))
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
