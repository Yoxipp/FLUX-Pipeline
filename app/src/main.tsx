import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
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
