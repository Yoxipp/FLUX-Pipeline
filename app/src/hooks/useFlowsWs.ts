// useFlowsWs.ts — live run messages of the Flows (WS /flows/ws, 01 §10), on the model
// of useDccStatus.ts: reconnect after 3 s, no polling. The WS pushes changes only; after
// a reconnection the caller rereads GET /flows/runs/{id} (onReconnect).

import { useEffect, useRef, useState } from 'react'
import type { FlowsWsMessage } from '../pages/flow_editor/types'

const WS_URL = 'ws://127.0.0.1:8765/flows/ws'
const RECONNECT_DELAY_MS = 3000

export function useFlowsWs(onMessage: (msg: FlowsWsMessage) => void, onReconnect?: () => void): boolean {
  const [connected, setConnected] = useState(false)
  // Latest callbacks without reopening the socket on every render.
  const handlers = useRef({ onMessage, onReconnect })
  handlers.current = { onMessage, onReconnect }

  useEffect(() => {
    let ws: WebSocket | null = null
    let timer: ReturnType<typeof setTimeout> | null = null
    let destroyed = false
    let opened = false

    function connect() {
      if (destroyed) return
      ws = new WebSocket(WS_URL)

      ws.onopen = () => {
        setConnected(true)
        if (opened) handlers.current.onReconnect?.()
        opened = true
      }

      ws.onmessage = (event) => {
        try {
          handlers.current.onMessage(JSON.parse(event.data) as FlowsWsMessage)
        } catch { /* malformed message: ignored */ }
      }

      ws.onclose = () => {
        setConnected(false)
        if (!destroyed) timer = setTimeout(connect, RECONNECT_DELAY_MS)
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

  return connected
}
