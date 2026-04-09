import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'
import { fileURLToPath } from 'url'

const projectRoot = fileURLToPath(new URL('.', import.meta.url))

const normalizeBasePath = (value) => {
  const raw = (value || '/sage/').trim()
  if (!raw || raw === '/') return '/'
  return `/${raw.replace(/^\/+|\/+$/g, '')}/`
}

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, projectRoot, '')
  const backendApiBaseUrl = (env.VITE_SAGE_API_BASE_URL || 'http://127.0.0.1:8080').trim()

  return {
    base: normalizeBasePath(env.VITE_SAGE_WEB_BASE_PATH),
    plugins: [vue()],
    resolve: {
      alias: {
        '@': resolve(projectRoot, 'src')
      }
    },
    server: {
      proxy: {
        '/dev-api': {
          target: backendApiBaseUrl,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/dev-api/, '')
        }
      }
    },
    test: {
      globals: true,
      environment: 'jsdom'
    },
    build: {
      sourcemap: false,
      rollupOptions: {
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
