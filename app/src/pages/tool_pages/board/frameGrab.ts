// frameGrab.ts — one still of a shot media for the shotboard (ADR 0083). A video is opened
// off screen, sought to `at` (0 = first frame, 1 = last) and drawn into a small ImageBitmap,
// then let go: a board of a hundred shots never keeps a hundred players open. The media is
// read where Production already serves it (GET /production/<p>/ref/file, Range, CORS), never
// copied into the board. Small LRU cache; a few grabs at a time.

const WIDTH = 480          // stills are made this wide at most
const MAX_CACHED = 150     // ~0.5 MB each at 480 x 270
const PARALLEL = 2
const TIMEOUT_MS = 20_000

export type MediaKind = 'video' | 'image'

const cache = new Map<string, ImageBitmap>()
const pending = new Map<string, Promise<ImageBitmap | null>>()
const queue: Array<() => Promise<void>> = []
let running = 0

const keyOf = (url: string, kind: MediaKind, at: number) => kind === 'image' ? url : `${url}#${at.toFixed(3)}`

/** The still if it is already made (export, first paint), else null. */
export function peekFrame(url: string, kind: MediaKind, at: number): ImageBitmap | null {
  const k = keyOf(url, kind, at)
  const b = cache.get(k)
  if (b) { cache.delete(k); cache.set(k, b) }
  return b ?? null
}

function keep(k: string, b: ImageBitmap) {
  cache.set(k, b)
  while (cache.size > MAX_CACHED) {
    const [oldKey, old] = cache.entries().next().value as [string, ImageBitmap]
    cache.delete(oldKey)
    old.close()
  }
}

function pump() {
  while (running < PARALLEL && queue.length) {
    running++
    const job = queue.shift()!
    void job().finally(() => { running--; pump() })
  }
}

/** The still of *url* at *at* (0..1 of the duration; ignored for an image), or null when the
 *  file cannot be read here (missing, codec Chromium does not decode, timeout). */
export function grabFrame(url: string, kind: MediaKind, at: number): Promise<ImageBitmap | null> {
  const k = keyOf(url, kind, at)
  const hit = peekFrame(url, kind, at)
  if (hit) return Promise.resolve(hit)
  const known = pending.get(k)
  if (known) return known
  const p = new Promise<ImageBitmap | null>(ok => {
    queue.push(() => (kind === 'image' ? stillOfImage(url) : stillOfVideo(url, at)).then(b => {
      pending.delete(k)
      if (b) keep(k, b)
      ok(b)
    }))
    pump()
  })
  pending.set(k, p)
  return p
}

function scaled(w: number, h: number) {
  const k = Math.min(1, WIDTH / Math.max(1, w))
  return { resizeWidth: Math.max(1, Math.round(w * k)), resizeHeight: Math.max(1, Math.round(h * k)), resizeQuality: 'medium' as const }
}

function stillOfImage(url: string): Promise<ImageBitmap | null> {
  return new Promise(ok => {
    const img = new Image()
    img.crossOrigin = 'anonymous'      // the backend answers CORS: the export canvas stays readable
    img.onload = () => createImageBitmap(img, scaled(img.naturalWidth, img.naturalHeight)).then(ok, () => ok(null))
    img.onerror = () => ok(null)
    img.src = url
  })
}

function stillOfVideo(url: string, at: number): Promise<ImageBitmap | null> {
  return new Promise(ok => {
    const v = document.createElement('video')
    let done = false
    const finish = (b: ImageBitmap | null) => {
      if (done) return
      done = true
      clearTimeout(timer)
      v.removeAttribute('src')
      v.load()                         // releases the decoder
      ok(b)
    }
    const timer = setTimeout(() => finish(null), TIMEOUT_MS)
    v.crossOrigin = 'anonymous'
    v.muted = true
    v.playsInline = true
    v.preload = 'auto'
    v.onerror = () => finish(null)
    // 0 exactly may never fire `seeked` (already there): a hair after it.
    const target = (d: number) => Number.isFinite(d) && d > 0 ? Math.min(Math.max(at * d, 0.001), Math.max(0.001, d - 0.04)) : 0.001
    let probing = false
    v.onloadedmetadata = () => {
      // A webm written without its duration (Infinity): a seek far away makes the player find it.
      if (v.duration === Infinity && at > 0) { probing = true; v.currentTime = 1e101; return }
      v.currentTime = target(v.duration)
    }
    v.onseeked = () => {
      if (probing) { probing = false; v.currentTime = target(v.duration); return }
      createImageBitmap(v, scaled(v.videoWidth || WIDTH, v.videoHeight || Math.round(WIDTH * 9 / 16))).then(finish, () => finish(null))
    }
    v.src = url
  })
}
