import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'
import fs from 'fs'
import os from 'os'

// Read SAGE_PORT from .sage_env file
function getSagePort() {
  try {
    const envPath = resolve(os.homedir(), '.sage/.sage_env')
    const content = fs.readFileSync(envPath, 'utf-8')
    const match = content.match(/SAGE_PORT=(\d+)/)
    if (match) return parseInt(match[1])
  } catch (e) {
    // ignore
  }
  return process.env.SAGE_PORT || 8080
}

const SAGE_PORT = getSagePort()

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src')
    }
  },
  server: {
    port: 1420,
    strictPort: true,
    proxy: {
      '/dev-api': {
        target: `http://127.0.0.1:${SAGE_PORT}`,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/dev-api/, '')
      },
      '/api': {
        target: `http://127.0.0.1:${SAGE_PORT}`,
        changeOrigin: true
      }
    }
  },
  test: {
    globals: true,
    environment: 'jsdom'
  },
  build: {
    minify: 'esbuild',
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor': ['vue', 'vue-router', 'pinia'],
          'ui-libs': ['lucide-vue-next', 'clsx', 'tailwind-merge']
        }
      },
      onwarn(warning, warn) {
        if (warning.code === 'MODULE_LEVEL_DIRECTIVE') {
          return
        }
        warn(warning)
      }
    },
    sourcemap: false
  }
})
