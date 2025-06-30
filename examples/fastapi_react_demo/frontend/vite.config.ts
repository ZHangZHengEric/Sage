import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 8080,
    proxy: {
      '/api': 'http://sage_backend:8000',
      '/ws': {
        target: 'ws://sage_backend:8000',
        ws: true,
      },
      '/proxy-file': {
        target: 'http://sage_backend:8000',
        changeOrigin: true,
      },
    }
  },
  build: {
    outDir: '../backend/static',
    emptyOutDir: true,
  }
})