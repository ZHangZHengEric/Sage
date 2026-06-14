import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'
import { fileURLToPath } from 'url'

const projectRoot = fileURLToPath(new URL('.', import.meta.url))

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const backendApiBaseUrl = 'http://127.0.0.1:30050'

  return {
    base: mode === 'production' ? '/sage/' : '/',
    plugins: [
      vue(),
      {
        name: 'sage-log-api-proxy',
        configureServer() {
          // eslint-disable-next-line no-console
          console.log(`[vite] server/web: /prod-api -> ${backendApiBaseUrl}`)
        }
      }
    ],
    resolve: {
      alias: {
        '@': resolve(projectRoot, 'src')
      }
    },
    server: {
      proxy: {
        '/prod-api': {
          target: backendApiBaseUrl,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/prod-api/, '')
        }
      }
    },
    test: {
      globals: true,
      environment: 'jsdom'
    },
    build: {
      sourcemap: false,
      reportCompressedSize: false,
      rollupOptions: {
        output: {
          manualChunks(id) {
            if (id.includes('/node_modules/highlight.js/')) {
              return 'vendor-highlight'
            }
          }
        },
        onwarn(warning, warn) {
          if (warning.code === 'MODULE_LEVEL_DIRECTIVE') {
            return
          }
          warn(warning)
        }
      }
    },
  }
})
