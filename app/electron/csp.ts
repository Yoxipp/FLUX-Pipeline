// csp.ts — Content-Security-Policy of the FLUX renderer (security R2).
// One source for the two delivery paths: the dev HTTP header added in main.ts / security.ts
// and the production <meta> injected by vite.config.ts (webRequest does not reach file://).
// Pure module: no electron import, so vite.config.ts can load it too.

export const DEV_ORIGIN = 'http://localhost:5173'

const BACKEND_HTTP = 'http://127.0.0.1:8765'
const BACKEND_WS = 'ws://127.0.0.1:8765'
// Origins of the sidecar, as the renderer or an embedded page may name it.
export const BACKEND_ORIGINS = [BACKEND_HTTP, 'http://localhost:8765']

export function buildCsp(dev: boolean): string {
  const directives: Record<string, string[]> = {
    // Everything not listed below is limited to the app's own files.
    'default-src': ["'self'"],
    // Bundled JS only. Dev adds 'unsafe-inline' for the inline React Fast Refresh
    // preamble that @vitejs/plugin-react writes into index.html.
    'script-src': dev ? ["'self'", "'unsafe-inline'"] : ["'self'"],
    // Components (sonner, react-flow, Radix) inject <style> tags and Vite does too in dev.
    'style-src': ["'self'", "'unsafe-inline'"],
    // Thumbnails and refs are <img src> on the sidecar (api.refFileUrl); small bundled
    // assets are inlined by Vite as data: URIs.
    'img-src': ["'self'", 'data:', 'blob:', BACKEND_HTTP],
    // <video src> on the sidecar (Range-enabled /production/.../ref/file).
    'media-src': ["'self'", 'blob:', BACKEND_HTTP],
    // Inter is bundled (woff2 assets, ADR 0050).
    'font-src': ["'self'", 'data:'],
    // fetch / WebSocket to the sidecar (client.ts, useDccStatus, useFlowsWs), Vite HMR in dev.
    'connect-src': ["'self'", BACKEND_HTTP, BACKEND_WS, ...(dev ? ['ws://localhost:5173'] : [])],
    // Settings > Doc embeds GET /system/manual from the sidecar, nothing else is framed.
    'frame-src': [BACKEND_HTTP],
    'object-src': ["'none'"],
    'base-uri': ["'self'"],
    'form-action': ["'self'"],
  }
  return Object.entries(directives).map(([name, sources]) => `${name} ${sources.join(' ')}`).join('; ')
}
