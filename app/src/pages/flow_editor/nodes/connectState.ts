// connectState.ts — what the ports need while a link is dragged (03_EDITEUR §5): whether
// the graph is editable, and for a port, the verdict of a link from the dragged port to it
// (null = no drag, or the dragged port itself). Provided by NetworkPane.
// grabLinked: a press on a linked input picks its link up (true = handled, the port must not
// start a new link).

import { createContext, useContext } from 'react'
import type { Connection, PortEnd } from '../portTypes'

export interface ConnectState {
  editable: boolean
  verdict:  (end: PortEnd) => Connection | null
  grabLinked: (end: PortEnd, clientX: number, clientY: number) => boolean
}

export const ConnectCtx = createContext<ConnectState>({ editable: false, verdict: () => null, grabLinked: () => false })
export const useConnectState = () => useContext(ConnectCtx)
