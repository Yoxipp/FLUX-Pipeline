// preload.ts — bridge sécurisé Electron ↔ React (contextIsolation).
// Seul endroit où Node.js et le renderer se parlent.

import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('electronAPI', {
  openFolder: (): Promise<string | null> =>
    ipcRenderer.invoke('dialog:openFolder'),

  openFile: (filters?: { name: string; extensions: string[] }[]): Promise<string | null> =>
    ipcRenderer.invoke('dialog:openFile', filters),

  saveFile: (defaultName?: string, filters?: { name: string; extensions: string[] }[]): Promise<string | null> =>
    ipcRenderer.invoke('dialog:saveFile', { defaultName, filters }),

  getAppVersion: (): Promise<string> =>
    ipcRenderer.invoke('app:getVersion'),

  showNotification: (title: string, body: string): Promise<void> =>
    ipcRenderer.invoke('notification:show', { title, body }),

  openPath: (filePath: string): Promise<void> =>
    ipcRenderer.invoke('shell:openPath', filePath),

  windowMinimize: (): void => ipcRenderer.send('window:minimize'),
  windowMaximize: (): void => ipcRenderer.send('window:maximize'),
  windowClose:    (): void => ipcRenderer.send('window:close'),

  // Backend health/recovery. The renderer shows a reconnect banner from these.
  getBackendStatus: (): Promise<string> => ipcRenderer.invoke('backend:getStatus'),
  restartBackend:   (): Promise<string> => ipcRenderer.invoke('backend:restart'),
  onBackendStatus: (cb: (payload: { status: string; detail?: string }) => void): (() => void) => {
    const handler = (_e: unknown, payload: { status: string; detail?: string }) => cb(payload)
    ipcRenderer.on('flux:backend-status', handler)
    return () => ipcRenderer.removeListener('flux:backend-status', handler)
  },
})
