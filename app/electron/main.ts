// main.ts — Electron main process: fenêtre native + sidecar Python.

import { app, BrowserWindow, dialog, ipcMain, nativeImage, Notification, shell } from 'electron'
import path from 'path'
import fs from 'fs'
import {
  startPythonSidecar, stopPythonSidecar, restartBackend,
  getBackendStatus, onBackendStatus, type BackendStatus,
} from './python_bridge'

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
    win.webContents.openDevTools()
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
}

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

ipcMain.handle('app:getVersion', () => app.getVersion())

ipcMain.handle('notification:show', (_event, { title, body }: { title: string; body: string }) => {
  // silent:false → Windows plays the default notification sound; icon = app mark.
  new Notification({ title, body, icon: ICON, silent: false }).show()
})

ipcMain.handle('shell:openPath', (_event, filePath: string) => {
  shell.openPath(filePath)
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

ipcMain.on('window:minimize', () => win?.minimize())
ipcMain.on('window:maximize', () => (win?.isMaximized() ? win.unmaximize() : win?.maximize()))
ipcMain.on('window:close',    () => win?.close())

// ── App lifecycle ─────────────────────────────────────────────────────────────

app.whenReady().then(async () => {
  // Windows: group under the FLUX identity so the taskbar shows our icon.
  if (process.platform === 'win32') app.setAppUserModelId('com.flux.pipeline')

  // Splash first — visible immediately, covers the Vite/backend startup gap.
  createSplash()

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

app.on('window-all-closed', async () => {
  await stopPythonSidecar()
  app.quit()
})

// Belt-and-suspenders: also kill the backend on any quit path (menu, taskbar,
// signal) so no zombie backend survives on port 8765.
app.on('before-quit', () => {
  void stopPythonSidecar()
})

app.on('activate', async () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    await createWindow()
  }
})
