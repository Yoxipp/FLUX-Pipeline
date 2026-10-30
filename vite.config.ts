import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import { buildCsp } from './app/electron/csp'

// Security R2: CSP of the packaged renderer, as a <meta> because the app loads over
// file:// where webRequest.onHeadersReceived does not apply. Build only: in dev, main.ts
// adds the (looser, HMR-compatible) header, and a meta here would be intersected with it.
const prodCsp = (): Plugin => ({
  name: 'flux-prod-csp',
  apply: 'build',
  transformIndexHtml: () => [{
    tag: 'meta',
    attrs: { 'http-equiv': 'Content-Security-Policy', content: buildCsp(false) },
    injectTo: 'head-prepend',
  }],
})

export default defineConfig({
  plugins: [react(), prodCsp()],
  base: './',
  server: {
    port: 5173,
    strictPort: true,
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './app/src'),
    },
  },
})
