import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '127.0.0.1',
    port: 5174,
    proxy: {
      '/api': 'https://api.sage-v2.withyi.life',
      '/health': 'https://health.sage-v2.withyi.life',
    },
  },
})
