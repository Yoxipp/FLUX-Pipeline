// PageErrorBoundary.tsx — a page that crashes shows its error instead of greying out
// the whole window (2026-09-25: picking Painter in the Publisher left FLUX grey and
// stuck). The sidebar and title bar stay usable; changing page resets the boundary.

import { Component, type ErrorInfo, type ReactNode } from 'react'
import { useLocation } from 'react-router-dom'

interface Props { children: ReactNode; resetKey: string }
interface State { error: Error | null }

class Boundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('[FLUX] page crash', error, info.componentStack)
  }

  componentDidUpdate(prev: Props): void {
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null })
  }

  render(): ReactNode {
    const { error } = this.state
    if (!error) return this.props.children
    return (
      <div style={{ padding: 28, display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 720 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--err)' }}>Cette page a rencontré une erreur</div>
        <div style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-2)', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
          {error.message}
        </div>
        <div style={{ fontSize: 11, color: 'var(--ink-3)' }}>
          Le reste de FLUX fonctionne : change de page dans la barre de gauche, ou réessaie.
        </div>
        <div>
          <button
            onClick={() => this.setState({ error: null })}
            style={{
              padding: '6px 14px', borderRadius: 6, border: '1px solid var(--rule-2)',
              background: 'var(--paper-2)', color: 'var(--ink)', fontSize: 11, cursor: 'pointer',
            }}
          >
            Réessayer
          </button>
        </div>
      </div>
    )
  }
}

export function PageErrorBoundary({ children }: { children: ReactNode }) {
  const location = useLocation()
  return <Boundary resetKey={location.pathname}>{children}</Boundary>
}
