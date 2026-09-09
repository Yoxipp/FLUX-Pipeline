// useBackendStatus.ts — live backend health from the Electron shell.
//
// The main process runs the FastAPI sidecar and, when an antivirus blocks it at
// launch, keeps retrying in the background. It pushes status transitions over
// IPC ('flux:backend-status'); this hook mirrors them so the UI can show a clear
// reconnect state and a manual retry, and recover without an app relaunch.

import { useEffect, useState } from 'react'

export function useBackendStatus() {
  // Outside Electron (pure web/dev), there is no shell to report status — assume
  // the separately-run backend is reachable so no banner is shown.
  const [status, setStatus] = useState<BackendStatus>(
    window.electronAPI?.onBackendStatus ? 'starting' : 'ready',
  )
  const [detail, setDetail] = useState<string | undefined>()

  useEffect(() => {
    const shell = window.electronAPI
    if (!shell?.onBackendStatus) return

    // Pull the current value on mount so a transition that fired before this
    // component subscribed is not missed.
    shell.getBackendStatus?.()
      .then((s) => setStatus((s as BackendStatus) || 'starting'))
      .catch(() => { /* ignore — the push below will correct it */ })

    const unsubscribe = shell.onBackendStatus(({ status, detail }) => {
      setStatus(status)
      setDetail(detail)
      // When the backend comes back, ask data hooks to re-fetch (useSettings and
      // friends listen for this) so the app rehydrates without a reload.
      if (status === 'ready') window.dispatchEvent(new Event('flux:refresh'))
    })
    return unsubscribe
  }, [])

  const restart = () => { void window.electronAPI?.restartBackend?.() }

  return { status, detail, restart }
}
