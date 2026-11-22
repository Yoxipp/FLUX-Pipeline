// preload.ts — bridge sécurisé Electron ↔ React (contextIsolation).
// Seul endroit où Node.js et le renderer se parlent.

import { contextBridge, ipcRenderer, webUtils } from 'electron'

contextBridge.exposeInMainWorld('electronAPI', {
  // Board (ADR 0074): clipboard image saved as a temp PNG (null: no image), and the local
  // path of a file dropped from the explorer ('' for a file that has none).
  saveClipboardImage: (): Promise<string | null> =>
    ipcRenderer.invoke('clipboard:saveImage'),
  pathForFile: (file: File): string => webUtils.getPathForFile(file),
  // Board export (ADR 0075): save dialog, then the bytes are written by the main process.
  saveBytes: (defaultName: string, filters: { name: string; extensions: string[] }[], data: Uint8Array): Promise<string | null> =>
    ipcRenderer.invoke('file:saveBytes', { defaultName, filters, data }),

  openFolder: (): Promise<string | null> =>
    ipcRenderer.invoke('dialog:openFolder'),

  openFile: (filters?: { name: string; extensions: string[] }[]): Promise<string | null> =>
    ipcRenderer.invoke('dialog:openFile', filters),

  // Multi-select variant: returns every chosen path (empty array on cancel).
  openFiles: (filters?: { name: string; extensions: string[] }[]): Promise<string[]> =>
    ipcRenderer.invoke('dialog:openFiles', filters),

  // Pick a folder, return every file inside it recursively (optionally filtered
  // to the given lowercase extensions, no dot).
  openFolderFiles: (extensions?: string[]): Promise<string[]> =>
    ipcRenderer.invoke('dialog:openFolderFiles', extensions),

  saveFile: (defaultName?: string, filters?: { name: string; extensions: string[] }[]): Promise<string | null> =>
    ipcRenderer.invoke('dialog:saveFile', { defaultName, filters }),

  getAppVersion: (): Promise<string> =>
    ipcRenderer.invoke('app:getVersion'),

  showNotification: (title: string, body: string): Promise<void> =>
    ipcRenderer.invoke('notification:show', { title, body }),

  // Launches "Uninstall FLUX.exe" and quits FLUX (Settings > Desinstaller FLUX).
  uninstallFlux: (): Promise<{ ok: boolean; reason?: string }> => ipcRenderer.invoke('app:uninstall'),
  // https links only, opened in the system browser.
  openExternal: (url: string): Promise<boolean> =>
    ipcRenderer.invoke('shell:openExternal', url),

  openPath: (filePath: string): Promise<void> =>
    ipcRenderer.invoke('shell:openPath', filePath),

  windowMinimize: (): void => ipcRenderer.send('window:minimize'),
  windowMaximize: (): void => ipcRenderer.send('window:maximize'),
  windowClose:    (): void => ipcRenderer.send('window:close'),
  // Toggle always-on-top for this window, resolves to the new pinned state.
  windowTogglePin: (): Promise<boolean> => ipcRenderer.invoke('window:togglePin'),
  // Open a page in its own window at the cursor (U4, sidebar drag out).
  detachPage:     (route: string): void => ipcRenderer.send('window:detach', route),

  // Backend health/recovery. The renderer shows a reconnect banner from these.
  getBackendStatus: (): Promise<string> => ipcRenderer.invoke('backend:getStatus'),
  restartBackend:   (): Promise<string> => ipcRenderer.invoke('backend:restart'),
  onBackendStatus: (cb: (payload: { status: string; detail?: string }) => void): (() => void) => {
    const handler = (_e: unknown, payload: { status: string; detail?: string }) => cb(payload)
    ipcRenderer.on('flux:backend-status', handler)
    return () => ipcRenderer.removeListener('flux:backend-status', handler)
  },
})
