import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      manifest: {
        name: 'Mabia AI',
        short_name: 'Mabia',
        description: 'CHPS emergency response, voice outreach and nutrition coordination',
        theme_color: '#0b3b60',
        background_color: '#ffffff',
        display: 'standalone',
        start_url: '/',
        icons: [
          { src: 'icon.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'any maskable' }
        ]
      },
      workbox: {
        // The app shell is cached so a worker can open it with no signal at
        // all. Data is served from IndexedDB, never from a stale API cache --
        // a cached worklist that looks current is worse than none.
        globPatterns: ['**/*.{js,css,html,svg,woff2}'],
        navigateFallback: 'index.html',
        runtimeCaching: []
      }
    })
  ],
  server: { port: 5173, proxy: { '/api': 'http://127.0.0.1:8000', '/audio': 'http://127.0.0.1:8000' } }
})
