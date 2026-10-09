import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// ADR 0050: Inter embedded (OFL), bundled by Vite as woff2 assets, no network.
import '@fontsource-variable/inter'
import './styles/globals.css'
import { App } from './App'
import { LanguageProvider } from './i18n'
import { ProjectProvider } from './ProjectContext'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <LanguageProvider>
      <ProjectProvider>
        <App />
      </ProjectProvider>
    </LanguageProvider>
  </StrictMode>,
)
