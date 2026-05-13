// useDccStatus.ts — WebSocket hook pour le statut DCC temps réel.

import { useEffect, useState } from 'react'
import type { DccStatusMap } from '../types'

const WS_URL = 'ws://127.0.0.1:8765/dcc/ws/status'
const RECONNECT_DELAY_MS = 3000

export function useDccStatus(): DccStatusMap {
  const [status, setStatus] = useState<DccStatusMap>({})

  useEffect(() => {
    let ws: WebSocket | null = null
    let timer: ReturnType<typeof setTimeout> | null = null
    let destroyed = false

    function connect() {
      if (destroyed) return
      ws = new WebSocket(WS_URL)

      ws.onmessage = (event) => {
        try {
          setStatus(JSON.parse(event.data) as DccStatusMap)
        } catch {}
      }

      ws.onclose = () => {
        if (!destroyed) {
          timer = setTimeout(connect, RECONNECT_DELAY_MS)
        }
      }

      ws.onerror = () => ws?.close()
    }

    connect()

    return () => {
      destroyed = true
      if (timer) clearTimeout(timer)
      ws?.close()
    }
  }, [])

  return status
}
