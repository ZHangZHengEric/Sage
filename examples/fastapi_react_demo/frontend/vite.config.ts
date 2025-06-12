import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 8080,
    proxy: {
      '/api': 'http://backend:8000',
      '/ws': {
        target: 'ws://backend:8000',
        ws: true,
      }
    }
  },
  build: {
    outDir: '../backend/static',
    emptyOutDir: true,
  }
})