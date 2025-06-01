import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 8080,
    proxy: {
      '/api': 'http://localhost:8001',
      '/ws': {
        target: 'ws://localhost:8001',
        ws: true,
      }
    }
  },
  build: {
    outDir: '../backend/static',
    emptyOutDir: true,
  }
}) 