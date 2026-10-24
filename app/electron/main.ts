// main.ts — Electron main process: fenêtre native + sidecar Python.

import { app, BrowserWindow, dialog, ipcMain, nativeImage, Notification, screen, session, shell } from 'electron'
import path from 'path'
import fs from 'fs'
import http from 'http'
import {
  startPythonSidecar, stopPythonSidecar, restartBackend, getApiToken, invalidateApiToken,
  getBackendStatus, onBackendStatus, type BackendStatus,
} from './python_bridge'
import { promptUpdateAtLaunch } from './updater'
import { displayVersion } from './version'
import { spawn } from 'child_process'

// The terminal that launched FLUX can go away (window closed, concurrently stopped)
// while FLUX keeps running: every console.log (backend output forwarded by
// python_bridge) then fails with EPIPE, an uncaught error popup on each backend line.
// A dead console is not an error: drop the write, keep FLUX running.
for (const stream of [process.stdout, process.stderr]) {
  stream?.on('error', (err: NodeJS.ErrnoException) => {
    if (err.code !== 'EPIPE' && err.code !== 'ERR_STREAM_DESTROYED') throw err
  })
}

let win: BrowserWindow | null = null
let splash: BrowserWindow | null = null

// FLUX window/taskbar icon. In dev it lives next to the sources; packaged builds
// also get the exe icon from electron-builder, but setting the window icon makes
// the taskbar reliably show ours. Loaded as a nativeImage (more robust than a
// raw path for the taskbar) — falls back to the .png if the .ico is unreadable.
const _ICON_ICO = path.join(__dirname, '..', 'scripts', 'icon.ico')
const _ICON_PNG = path.join(__dirname, '..', 'scripts', 'icon.png')
let ICON = nativeImage.createFromPath(_ICON_ICO)
if (ICON.isEmpty()) ICON = nativeImage.createFromPath(_ICON_PNG)

// Official FLUX mark for the splash — the app icon PNG, embedded as a data URI so
// the splash's data: HTML can show it without a file:// reference. Used as-is.
const ATOM_SVG = (() => {
  try {
    const buf = fs.readFileSync(_ICON_PNG)
    return `<img width="64" height="64" style="object-fit:contain" src="data:image/png;base64,${buf.toString('base64')}" />`
  } catch {
    return '' // splash still shows the wordmark if the icon can't be read
  }
})()

// ── Splash screen ─────────────────────────────────────────────────────────────
// Shown the instant Electron is ready, covering the gap until the main window has
// loaded (Vite in dev / backend cold-start). Flat Flux identity — no glow.
function splashHtml(): string {
  return `<!doctype html><html><head><meta charset="utf-8"><style>
  :root{--bg:#161514;--ink:#cac8c5;--ink3:#8a8784;
        --accent:oklch(66% 0.10 52);--accent-hi:oklch(75% 0.115 52);
        --accent-soft:color-mix(in oklch, oklch(66% 0.10 52) 14%, transparent);
        --border:color-mix(in oklch, oklch(66% 0.10 52) 50%, transparent);}
  *{margin:0;box-sizing:border-box;-webkit-user-select:none}
  html,body{height:100%}
  body{background:var(--bg);border:1px solid #2a2826;border-radius:12px;
       font-family:'Consolas','SF Mono',ui-monospace,monospace;
       display:flex;flex-direction:column;align-items:center;justify-content:center;gap:16px;overflow:hidden}
  .mark{display:flex;align-items:center;justify-content:center}
  .word{display:flex;align-items:baseline;gap:9px}
  .flux{color:var(--ink);font-weight:600;font-size:18px;letter-spacing:.16em}
  .sub{color:var(--ink3);font-size:12px;letter-spacing:.02em}
  .bar{width:180px;height:2px;background:#2a2826;border-radius:2px;overflow:hidden;margin-top:2px}
  .bar>i{display:block;height:100%;width:40%;border-radius:2px;background:var(--accent);
         animation:slide 1.1s ease-in-out infinite}
  @keyframes slide{0%{transform:translateX(-120%)}100%{transform:translateX(320%)}}
  </style></head><body>
  <div class="mark">${ATOM_SVG}</div>
  <div class="word"><span class="flux">FLUX</span><span class="sub">Pipeline Tool</span></div>
  <div class="bar"><i></i></div>
  </body></html>`
}

function createSplash(): void {
  splash = new BrowserWindow({
    width: 380, height: 240,
    frame: false, transparent: true, resizable: false, movable: false,
    alwaysOnTop: true, skipTaskbar: true, show: false,
    backgroundColor: '#00000000', icon: ICON,
  })
  splash.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(splashHtml()))
  splash.once('ready-to-show', () => splash?.show())
  // Failsafe: never let the splash linger if the main window fails to load.
  setTimeout(closeSplash, 20_000)
}

function closeSplash(): void {
  if (splash && !splash.isDestroyed()) splash.close()
  splash = null
}

async function createWindow(): Promise<void> {
  win = new BrowserWindow({
    width:           1400,
    height:          900,
    minWidth:        1000,
    minHeight:       700,
    backgroundColor: '#0f0f0f',
    show:            false,     // shown once loaded, so the splash hands over cleanly
    icon:            ICON,
    frame:           false,    // frameless — TitleBar React gère les contrôles
    webPreferences: {
      preload:          path.join(__dirname, 'preload.js'),
      contextIsolation: true,   // OBLIGATOIRE
      nodeIntegration:  false,  // OBLIGATOIRE
    },
  })

  if (!ICON.isEmpty()) win.setIcon(ICON)   // belt-and-suspenders for the taskbar

  // Reveal the window independently of the load promise: 'ready-to-show' fires
  // once the renderer can paint, and a fallback timer guarantees we never stay
  // hidden even if the dev server is slow/unreachable. Idempotent.
  const reveal = () => {
    if (!win) return
    if (!win.isVisible()) {
      win.show()
      win.focus()
    }
    closeSplash()
  }
  win.once('ready-to-show', reveal)
  setTimeout(reveal, 12_000)

  // Load the renderer. In dev the Vite server may not be up yet, so retry the
  // URL until it answers instead of blocking startup on a fixed port wait.
  if (!app.isPackaged) {
    const url = 'http://localhost:5173'
    const deadline = Date.now() + 30_000
    const tryLoad = () => {
      win?.loadURL(url).catch(() => {
        if (Date.now() < deadline && win && !win.isDestroyed()) {
          setTimeout(tryLoad, 300)
        }
      })
    }
    tryLoad()
    // Detached: docked DevTools break -webkit-app-region drag on a frameless window (Windows).
    win.webContents.openDevTools({ mode: 'detach' })
  } else {
    win.loadFile(path.join(__dirname, '../dist/index.html')).catch((err) =>
      console.error('[Electron] loadFile failed:', err))
  }

  // Ctrl+Shift+I ouvre les DevTools même en production (debug packagé)
  win.webContents.on('before-input-event', (_event, input) => {
    if (input.control && input.shift && input.key.toLowerCase() === 'i') {
      win?.webContents.openDevTools()
    }
  })

  // Closing the main window closes the detached ones too (U4): no orphan window.
  win.on('closed', () => {
    for (const w of BrowserWindow.getAllWindows()) if (!w.isDestroyed()) w.close()
    win = null
  })
}

// ── Detached windows (U4, ADR 0027) ───────────────────────────────────────────
// A sidebar page dragged out of the main window opens as its own window (same
// preload, same session: the S1 token header applies). The main window keeps its
// page. The renderer shows a sidebar-less shell when the URL carries ?detached=1.
const DETACHABLE_ROUTES = new Set([
  '/', '/publisher', '/projects', '/usd', '/shelf', '/templates', '/production', '/activity', '/disk',
  // Opened from Parametres avances: Flows editor, and the old YAML action editor until P8.
  '/action-graph', '/action-graph-legacy',
  // Tractor farm page, opened from the launcher like a software (single window).
  '/render',
  // TOOL pages (Flows P7): the tab, with ?page=<id> as a deep link.
  '/tool',
])

// Routes that only ever get one window: a second request focuses the existing one.
const SINGLE_WINDOW_ROUTES = new Set(['/render', '/action-graph', '/action-graph-legacy'])
const singleWindows = new Map<string, BrowserWindow>()

// Routes that need room (node editors): bigger window and minimum size.
const LARGE_ROUTES = new Set(['/action-graph', '/action-graph-legacy'])

// `route` may carry a query for a deep link (/action-graph?flow=publish): only its
// path is checked against the lists, the whole route goes into the hash.
function createDetachedWindow(route: string): void {
  const routePath = route.split('?')[0]
  if (!DETACHABLE_ROUTES.has(routePath)) return
  const single = SINGLE_WINDOW_ROUTES.has(routePath)
  if (single) {
    const existing = singleWindows.get(routePath)
    if (existing && !existing.isDestroyed()) {
      if (existing.isMinimized()) existing.restore()
      if (route !== routePath) {
        existing.webContents.executeJavaScript(`window.location.hash = ${JSON.stringify(route)}`)
          .catch((err) => console.error('[Electron] detached deep link failed:', err))
      }
      existing.show()
      existing.focus()
      return
    }
  }
  const large = LARGE_ROUTES.has(routePath)
  const cursor = screen.getCursorScreenPoint()
  const child = new BrowserWindow({
    width:           large ? 1440 : 1100,
    height:          large ? 900 : 760,
    minWidth:        large ? 960 : 640,
    minHeight:       large ? 600 : 480,
    x:               Math.max(0, cursor.x - 120),
    y:               Math.max(0, cursor.y - 16),
    backgroundColor: '#0f0f0f',
    icon:            ICON,
    frame:           false,
    title:           routePath === '/render' ? 'Tractor' : 'FLUX',
    webPreferences: {
      preload:          path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration:  false,
    },
  })
  if (single) {
    singleWindows.set(routePath, child)
    child.on('closed', () => { if (singleWindows.get(routePath) === child) singleWindows.delete(routePath) })
  }
  if (!app.isPackaged) {
    child.loadURL(`http://localhost:5173/?detached=1#${route}`).catch((err) =>
      console.error('[Electron] detached loadURL failed:', err))
  } else {
    child.loadFile(path.join(__dirname, '../dist/index.html'), { query: { detached: '1' }, hash: route })
      .catch((err) => console.error('[Electron] detached loadFile failed:', err))
  }
  child.webContents.on('before-input-event', (_event, input) => {
    if (input.control && input.shift && input.key.toLowerCase() === 'i') child.webContents.openDevTools()
  })
}

ipcMain.on('window:detach', (_event, route: string) => createDetachedWindow(String(route || '')))

// ── IPC handlers ──────────────────────────────────────────────────────────────

ipcMain.handle('dialog:openFolder', async () => {
  if (!win) return null
  const result = await dialog.showOpenDialog(win, {
    properties: ['openDirectory'],
  })
  return result.canceled ? null : result.filePaths[0]
})

ipcMain.handle('dialog:openFile', async (_event, filters?: { name: string; extensions: string[] }[]) => {
  if (!win) return null
  const result = await dialog.showOpenDialog(win, {
    properties: ['openFile'],
    filters: filters ?? [{ name: 'Executables', extensions: ['exe', 'app', ''] }],
  })
  return result.canceled ? null : result.filePaths[0]
})

ipcMain.handle('dialog:openFiles', async (_event, filters?: { name: string; extensions: string[] }[]) => {
  if (!win) return []
  const result = await dialog.showOpenDialog(win, {
    properties: ['openFile', 'multiSelections'],
    filters: filters ?? [{ name: 'Tous les fichiers', extensions: ['*'] }],
  })
  return result.canceled ? [] : result.filePaths
})

// Pick a FOLDER and return every file inside it (recursively). Used by the
// Publisher's local source to import a whole texture folder at once. When
// `extensions` is given (lowercase, no dot), only those file types are returned.
ipcMain.handle('dialog:openFolderFiles', async (_event, extensions?: string[]) => {
  if (!win) return []
  const result = await dialog.showOpenDialog(win, { properties: ['openDirectory'] })
  if (result.canceled || !result.filePaths[0]) return []
  const root = result.filePaths[0]
  const allow = extensions && extensions.length ? new Set(extensions.map(e => e.toLowerCase())) : null
  const out: string[] = []
  const MAX = 5000  // guard against selecting a giant tree by accident
  const walk = (dir: string) => {
    if (out.length >= MAX) return
    let entries: fs.Dirent[]
    try { entries = fs.readdirSync(dir, { withFileTypes: true }) } catch { return }
    for (const e of entries) {
      if (out.length >= MAX) return
      const full = path.join(dir, e.name)
      if (e.isDirectory()) { walk(full); continue }
      if (!e.isFile()) continue
      if (allow) {
        const ext = path.extname(e.name).slice(1).toLowerCase()
        if (!allow.has(ext)) continue
      }
      out.push(full)
    }
  }
  walk(root)
  return out.sort()
})

ipcMain.handle('dialog:saveFile', async (_event, opts?: { defaultName?: string; filters?: { name: string; extensions: string[] }[] }) => {
  if (!win) return null
  const result = await dialog.showSaveDialog(win, {
    defaultPath: opts?.defaultName,
    filters: opts?.filters ?? [{ name: 'All files', extensions: ['*'] }],
  })
  return result.canceled ? null : (result.filePath ?? null)
})

// Display version x.x.xxx from package.json fluxVersion (version.ts), not the semver.
ipcMain.handle('app:getVersion', () => displayVersion())

ipcMain.handle('notification:show', (_event, { title, body }: { title: string; body: string }) => {
  // silent:false → Windows plays the default notification sound; icon = app mark.
  new Notification({ title, body, icon: ICON, silent: false }).show()
})

ipcMain.handle('shell:openPath', (_event, filePath: string) => {
  shell.openPath(filePath)
})

// Settings > "Desinstaller FLUX": start the NSIS uninstaller that sits next to FLUX.exe
// ("Uninstall FLUX.exe") and quit so it can delete the app. The uninstaller itself
// removes what FLUX added to the DCCs (scripts/installer.nsh, customUnInstall), so the
// button and a double-click on the exe do exactly the same thing.
ipcMain.handle('app:uninstall', async (): Promise<{ ok: boolean; reason?: string }> => {
  if (!app.isPackaged) return { ok: false, reason: 'dev' }
  const uninstaller = path.join(path.dirname(process.execPath), 'Uninstall FLUX.exe')
  if (!fs.existsSync(uninstaller)) return { ok: false, reason: `introuvable : ${uninstaller}` }
  try {
    const child = spawn(uninstaller, [], { detached: true, stdio: 'ignore' })
    await new Promise<void>((resolve, reject) => {
      child.once('error', reject)
      child.once('spawn', () => resolve())
    })
    child.unref()
  } catch (err) {
    return { ok: false, reason: String(err) }
  }
  // Let the renderer get the answer, then quit (before-quit stops the backend).
  setTimeout(() => app.quit(), 300)
  return { ok: true }
})

// ── Backend status / recovery ─────────────────────────────────────────────────
// The renderer subscribes to 'flux:backend-status' pushes and can pull the
// current value on mount, so its reconnect banner is always in sync even if a
// status change fired before the window finished loading.
ipcMain.handle('backend:getStatus', () => getBackendStatus())
ipcMain.handle('backend:restart', async () => restartBackend())

function broadcastBackendStatus(status: BackendStatus, detail?: string): void {
  for (const w of BrowserWindow.getAllWindows()) {
    if (!w.isDestroyed()) w.webContents.send('flux:backend-status', { status, detail })
  }
}

// ── Window controls (frameless) ───────────────────────────────────────────────

// Each control acts on the window that sent it (main or detached, U4).
const senderWindow = (e: Electron.IpcMainEvent) => BrowserWindow.fromWebContents(e.sender)
ipcMain.on('window:minimize', (e) => senderWindow(e)?.minimize())
ipcMain.on('window:maximize', (e) => {
  const w = senderWindow(e)
  if (w) (w.isMaximized() ? w.unmaximize() : w.maximize())
})
ipcMain.on('window:close',    (e) => senderWindow(e)?.close())
// Pin: keep the window above every other app until toggled off.
ipcMain.handle('window:togglePin', (e) => {
  const w = BrowserWindow.fromWebContents(e.sender)
  if (!w) return false
  const pinned = !w.isAlwaysOnTop()
  w.setAlwaysOnTop(pinned, 'floating')
  return pinned
})

// ── App lifecycle ─────────────────────────────────────────────────────────────

app.whenReady().then(async () => {
  // Windows: group under the FLUX identity so the taskbar shows our icon.
  if (process.platform === 'win32') app.setAppUserModelId('com.flux.pipeline')

  // Newer installer in <FLUX_ROOT>/FLUX_UPDATE: offer the update before anything
  // starts (the splash is always-on-top and would hide the prompt). Accepted: the
  // installer is running, quit without starting the backend.
  if (await promptUpdateAtLaunch(ICON)) {
    app.quit()
    return
  }

  // Splash first — visible immediately, covers the Vite/backend startup gap.
  createSplash()

  // Security S1: stamp the backend's per-launch token on every renderer request to
  // it (fetch, img/video src, WebSocket). Added here, below the renderer, so it
  // never triggers a CORS preflight. A 403 drops the cached token so the next
  // request refetches it (backend restarted with a new token).
  const backendFilter = { urls: [
    'http://127.0.0.1:8765/*', 'ws://127.0.0.1:8765/*',
    'http://localhost:8765/*', 'ws://localhost:8765/*',
  ] }
  session.defaultSession.webRequest.onBeforeSendHeaders(backendFilter, (details, callback) => {
    getApiToken().then((token) => {
      if (token) details.requestHeaders['X-Flux-Token'] = token
      callback({ requestHeaders: details.requestHeaders })
    })
  })
  session.defaultSession.webRequest.onHeadersReceived(backendFilter, (details, callback) => {
    if (details.statusCode === 403) invalidateApiToken()
    callback({})
  })

  // Forward backend status to the renderer's reconnect banner. Registered before
  // the sidecar starts so no transition is missed; the callback also fires once
  // with the current status immediately.
  onBackendStatus((status, detail) => broadcastBackendStatus(status, detail))

  // Backend en arrière-plan : ne bloque PAS l'ouverture de la fenêtre (le cold
  // start ~5s rendait l'app lente à ouvrir). Il se connecte quand il est prêt.
  // startPythonSidecar ne rejette plus : si l'antivirus bloque l'exe, il passe en
  // statut 'down' et une boucle de recovery le relance en arrière-plan dès que
  // l'AV le libère — l'utilisateur voit une bannière et n'a plus à relancer FLUX.
  startPythonSidecar().catch((err) => {
    console.error('[Electron] Unexpected sidecar start error:', err)
  })

  // Create the window immediately (hidden); it retries the Vite URL on its own
  // and reveals itself once painted, so nothing here can block it opening.
  await createWindow()
})

// Best-effort: release ZBrush from its freeze loop before the backend is hard-
// killed, so closing FLUX never leaves ZBrush frozen (the backend is taskkilled on
// quit, so its own shutdown hook may not run). Short timeout, always resolves.
function releaseZBrush(): Promise<void> {
  return new Promise((resolve) => {
    try {
      const req = http.request(
        { host: '127.0.0.1', port: 8765, path: '/dcc/zbrush/cancel', method: 'POST', timeout: 1500 },
        (res) => { res.resume(); res.on('end', () => resolve()) },
      )
      req.on('error', () => resolve())
      req.on('timeout', () => { req.destroy(); resolve() })
      req.end()
    } catch { resolve() }
  })
}

app.on('window-all-closed', async () => {
  await releaseZBrush()   // free ZBrush before the backend goes away
  await stopPythonSidecar()
  app.quit()
})

// Belt-and-suspenders: also kill the backend on any quit path (menu, taskbar,
// signal) so no zombie backend survives on port 8765.
app.on('before-quit', () => {
  void releaseZBrush()
  void stopPythonSidecar()
})

app.on('activate', async () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    await createWindow()
  }
})
