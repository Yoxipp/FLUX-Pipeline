// closeGuard.ts — guards asked before a detached window closes (03_EDITEUR §6, A15). A page
// registers an async guard (the Flows editor: quit = Ctrl+S, with the destructive node
// slider); TitleBar runs them before windowClose(). A guard answers false to keep the
// window open (the user cancelled, or the save failed). Closing the main window closes
// the others without guard (main.ts): the editor keeps a localStorage draft for that case.

export type CloseGuard = () => Promise<boolean>

const guards = new Set<CloseGuard>()

export function registerCloseGuard(guard: CloseGuard): () => void {
  guards.add(guard)
  return () => { guards.delete(guard) }
}

// True when every guard lets the window close (a throwing guard keeps it open).
export async function runCloseGuards(): Promise<boolean> {
  for (const guard of [...guards]) {
    try {
      if (!(await guard())) return false
    } catch {
      return false
    }
  }
  return true
}
