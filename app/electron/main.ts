// main.ts — Electron main process: fenêtre native + sidecar Python.

import { app, BrowserWindow, dialog, ipcMain, Notification, shell } from 'electron'
import path from 'path'
import { startPythonSidecar, stopPythonSidecar } from './python_bridge'

let win: BrowserWindow | null = null
let splash: BrowserWindow | null = null

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
  .mark{width:56px;height:56px;border-radius:14px;background:var(--accent-soft);
        border:1px solid var(--border);color:var(--accent-hi);
        display:flex;align-items:center;justify-content:center;font-weight:700;font-size:26px}
  .word{display:flex;align-items:baseline;gap:9px}
  .flux{color:var(--ink);font-weight:600;font-size:18px;letter-spacing:.16em}
  .sub{color:var(--ink3);font-size:12px;letter-spacing:.02em}
  .bar{width:180px;height:2px;background:#2a2826;border-radius:2px;overflow:hidden;margin-top:2px}
  .bar>i{display:block;height:100%;width:40%;border-radius:2px;background:var(--accent);
         animation:slide 1.1s ease-in-out infinite}
  @keyframes slide{0%{transform:translateX(-120%)}100%{transform:translateX(320%)}}
  </style></head><body>
  <div class="mark">F</div>
  <div class="word"><span class="flux">FLUX</span><span class="sub">Pipeline Tool</span></div>
  <div class="bar"><i></i></div>
  </body></html>`
}

function createSplash(): void {
  splash = new BrowserWindow({
    width: 380, height: 240,
    frame: false, transparent: true, resizable: false, movable: false,
    alwaysOnTop: true, skipTaskbar: true, show: false,
    backgroundColor: '#00000000',
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
    frame:           false,    // frameless — TitleBar React gère les contrôles
    webPreferences: {
      preload:          path.join(__dirname, 'preload.js'),
      contextIsolation: true,   // OBLIGATOIRE
      nodeIntegration:  false,  // OBLIGATOIRE
    },
  })

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

ipcMain.handle('app:getVersion', () => app.getVersion())

ipcMain.handle('notification:show', (_event, { title, body }: { title: string; body: string }) => {
  new Notification({ title, body }).show()
})

ipcMain.handle('shell:openPath', (_event, filePath: string) => {
  shell.openPath(filePath)
})

// ── Window controls (frameless) ───────────────────────────────────────────────

ipcMain.on('window:minimize', () => win?.minimize())
ipcMain.on('window:maximize', () => (win?.isMaximized() ? win.unmaximize() : win?.maximize()))
ipcMain.on('window:close',    () => win?.close())

// ── App lifecycle ─────────────────────────────────────────────────────────────

app.whenReady().then(async () => {
  // Splash first — visible immediately, covers the Vite/backend startup gap.
  createSplash()

  // Backend en arrière-plan : ne bloque PAS l'ouverture de la fenêtre (le cold
  // start ~5s rendait l'app lente à ouvrir). Il se connecte quand il est prêt.
  startPythonSidecar().catch((err) =>
    console.error('[Electron] Failed to start Python sidecar:', err))

  // Create the window immediately (hidden); it retries the Vite URL on its own
  // and reveals itself once painted, so nothing here can block it opening.
  await createWindow()
})

app.on('window-all-closed', async () => {
  await stopPythonSidecar()
  app.quit()
})

app.on('activate', async () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    await createWindow()
  }
})
