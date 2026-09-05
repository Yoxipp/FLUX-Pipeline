export {}

declare global {
  interface Window {
    electronAPI?: {
      openFolder: () => Promise<string | null>
      openFile: (filters?: { name: string; extensions: string[] }[]) => Promise<string | null>
      saveFile: (defaultName?: string, filters?: { name: string; extensions: string[] }[]) => Promise<string | null>
      getAppVersion: () => Promise<string>
      showNotification: (title: string, body: string) => Promise<void>
      openPath: (filePath: string) => Promise<void>
      windowMinimize: () => void
      windowMaximize: () => void
      windowClose: () => void
    }
  }
}
