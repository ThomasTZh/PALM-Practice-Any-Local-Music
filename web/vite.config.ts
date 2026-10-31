import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The API server runs separately (see scripts/studio.py dev); the UI proxies
// /api to it so the browser has a single origin.
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: false,
      },
    },
  },
  build: {
    outDir: 'dist',
  },
})
