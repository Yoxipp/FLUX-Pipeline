export {}

declare global {
  interface Window {
    electronAPI?: {
      openFolder: () => Promise<string | null>
      openFile: (filters?: { name: string; extensions: string[] }[]) => Promise<string | null>
      openFiles: (filters?: { name: string; extensions: string[] }[]) => Promise<string[]>
      openFolderFiles: (extensions?: string[]) => Promise<string[]>
      saveFile: (defaultName?: string, filters?: { name: string; extensions: string[] }[]) => Promise<string | null>
      getAppVersion: () => Promise<string>
      showNotification: (title: string, body: string) => Promise<void>
      openPath: (filePath: string) => Promise<void>
      windowMinimize: () => void
      windowMaximize: () => void
      windowClose: () => void
      detachPage?: (route: string) => void
      getBackendStatus?: () => Promise<string>
      restartBackend?: () => Promise<string>
      onBackendStatus?: (cb: (payload: { status: BackendStatus; detail?: string }) => void) => (() => void)
    }
  }

  type BackendStatus = 'starting' | 'ready' | 'retrying' | 'down'
}
