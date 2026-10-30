// security.ts — guards shared by every FLUX window (security R2, audit AUDIT_P1_2026-10-24 s4).
// No page but the app's own may navigate a FLUX window, open a window, or receive the
// backend token. External https links go to the system browser instead.

import { app, shell } from 'electron'
import path from 'path'
import { fileURLToPath } from 'url'
import { BACKEND_ORIGINS, DEV_ORIGIN, buildCsp } from './csp'

// The document main.ts loads in a packaged build (loadFile), resolved the same way.
const PROD_INDEX = path.resolve(__dirname, '../dist/index.html')

const sameFile = (a: string, b: string) =>
  process.platform === 'win32' ? a.toLowerCase() === b.toLowerCase() : a === b

/** True for the app's own document: the Vite dev origin (dev) or dist/index.html (packaged).
 *  Hash and query are ignored, so detached windows (?detached=1#/route) match too. */
export function isAppUrl(rawUrl: string): boolean {
  let url: URL
  try { url = new URL(rawUrl) } catch { return false }
  if (!app.isPackaged) return url.origin === DEV_ORIGIN
  if (url.protocol !== 'file:') return false
  try { return sameFile(path.resolve(fileURLToPath(url)), PROD_INDEX) } catch { return false }
}

function isBackendUrl(rawUrl: string): boolean {
  try { return BACKEND_ORIGINS.includes(new URL(rawUrl).origin) } catch { return false }
}

/** Hand an https link to the system browser. Anything else (file:, javascript:, http:,
 *  custom protocols, links with credentials) is dropped: never openExternal blindly. */
function openExternalIfHttps(rawUrl: string): void {
  let url: URL
  try { url = new URL(rawUrl) } catch { return }
  if (url.protocol !== 'https:' || url.username || url.password) return
  shell.openExternal(url.toString()).catch((err) => console.error('[Electron] openExternal failed:', err))
}

/** Guards for EVERY webContents (main, detached, splash) via `web-contents-created`, so a
 *  window added later is covered without touching its creation code. */
export function installWebContentsGuards(): void {
  app.on('web-contents-created', (_event, contents) => {
    // Main frame only: the Settings > Doc iframe (sidecar page) navigates on its own and
    // is bounded by the CSP frame-src instead.
    contents.on('will-navigate', (details) => {
      if (!details.isMainFrame || isAppUrl(details.url) || details.url.startsWith('devtools://')) return
      details.preventDefault()
      openExternalIfHttps(details.url)
    })
    // A redirect away from the app is blocked, never opened externally.
    contents.on('will-redirect', (details) => {
      if (!details.isMainFrame || isAppUrl(details.url) || details.url.startsWith('devtools://')) return
      details.preventDefault()
    })
    // The renderer never needs window.open: detached windows come from the 'window:detach'
    // IPC (createDetachedWindow in main.ts), which builds its BrowserWindow in the main process.
    contents.setWindowOpenHandler(({ url }) => {
      openExternalIfHttps(url)
      return { action: 'deny' }
    })
    contents.on('will-attach-webview', (event) => event.preventDefault())
  })
}

/** Should this backend request carry X-Flux-Token? Only when the window shows the app and
 *  the frame that issued the request is the app, a page of the sidecar embedded in it
 *  (Settings > Doc), or not committed yet. Foreign frames, foreign windows and requests
 *  without a webContents get nothing. */
export function mayReceiveToken(details: Electron.OnBeforeSendHeadersListenerDetails): boolean {
  const wc = details.webContents
  if (!wc || wc.isDestroyed() || !isAppUrl(wc.getURL())) return false
  let frameUrl = ''
  try { frameUrl = details.frame?.url ?? '' } catch { /* frame already gone */ }
  if (!frameUrl || frameUrl === 'about:blank') return true
  return isAppUrl(frameUrl) || isBackendUrl(frameUrl)
}

/** Dev only: Vite sends no CSP, so the app document response gets one here. A packaged
 *  build carries it as a <meta> (vite.config.ts) because webRequest does not reach file://.
 *  Returns the headers to use, or undefined when this response is not the dev app document. */
export function withDevCsp(details: Electron.OnHeadersReceivedListenerDetails): Record<string, string[]> | undefined {
  if (app.isPackaged || details.resourceType !== 'mainFrame' || !isAppUrl(details.url)) return undefined
  const headers: Record<string, string[]> = {}
  for (const [name, value] of Object.entries(details.responseHeaders ?? {})) {
    if (name.toLowerCase() !== 'content-security-policy') headers[name] = value
  }
  headers['Content-Security-Policy'] = [buildCsp(true)]
  return headers
}
