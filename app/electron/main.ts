// main.ts — Electron main process: fenêtre native + sidecar Python.

import { app, BrowserWindow, dialog, ipcMain, Notification, shell } from 'electron'
import path from 'path'
import { startPythonSidecar, stopPythonSidecar, waitForPort } from './python_bridge'

let win: BrowserWindow | null = null

async function createWindow(): Promise<void> {
  win = new BrowserWindow({
    width:           1400,
    height:          900,
    minWidth:        1000,
    minHeight:       700,
    backgroundColor: '#0f0f0f',
    frame:           false,    // frameless — TitleBar React gère les contrôles
    webPreferences: {
      preload:          path.join(__dirname, 'preload.js'),
      contextIsolation: true,   // OBLIGATOIRE
      nodeIntegration:  false,  // OBLIGATOIRE
    },
  })

  if (!app.isPackaged) {
    await win.loadURL('http://localhost:5173')
    win.webContents.openDevTools()
  } else {
    await win.loadFile(path.join(__dirname, '../dist/index.html'))
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
  try {
    await startPythonSidecar()
  } catch (err) {
    console.error('[Electron] Failed to start Python sidecar:', err)
  }

  // En dev : attendre que Vite soit prêt avant d'ouvrir la fenêtre
  if (!app.isPackaged) {
    try {
      await waitForPort(5173, 30_000)
    } catch {
      console.warn('[Electron] Vite not ready after 30s, opening anyway')
    }
  }

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
