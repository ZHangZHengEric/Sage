import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import http from 'node:http'
import fs from 'fs'
import os from 'os'
import { resolve } from 'path'
import { fileURLToPath } from 'url'
import { createProxyMiddleware } from 'http-proxy-middleware'

const __dirname = fileURLToPath(new URL('.', import.meta.url))

const sageEnvPath = () => resolve(os.homedir(), '.sage/.sage_env')

/** 与 app/desktop/tauri/src/main.rs choose_desktop_backend_port 中 preferred_ports 顺序一致，必须先于 .sage_env 里过期的 8080 尝试 */
const PREFERRED_FROM_RUST = [18080, 18081, 18082, 8080, 8000, 18090]

function readSagePortFromFile() {
  try {
    const content = fs.readFileSync(sageEnvPath(), 'utf-8')
    const match = content.match(/^\s*SAGE_PORT\s*=\s*(\d+)/m)
    if (match) {
      const p = parseInt(match[1], 10)
      if (!Number.isNaN(p) && p > 0) return p
    }
  } catch {
    // ignore
  }
  return null
}

function probeHealth(port) {
  return new Promise((resolveProbe) => {
    const req = http.get(
      `http://127.0.0.1:${port}/api/health`,
      { timeout: 250 },
      (res) => {
        res.resume()
        resolveProbe(res.statusCode === 200)
      }
    )
    req.on('error', () => resolveProbe(false))
    req.on('timeout', () => {
      try {
        req.destroy()
      } catch {
        // ignore
      }
      resolveProbe(false)
    })
  })
}

/** 与 Rust 同序探测实际监听端口，避免 .sage_env 残留 SAGE_PORT=8080 时仍连 8080 而 Tauri 已在 18080。结果短缓存。 */
let targetCache = { url: 'http://127.0.0.1:18080', t: 0 }
const TARGET_CACHE_MS = 4000

async function resolveBackendTarget() {
  const now = Date.now()
  if (now - targetCache.t < TARGET_CACHE_MS) {
    return targetCache.url
  }

  const seen = new Set()
  const candidates = []
  const push = (p) => {
    if (p == null || Number.isNaN(p) || p <= 0) return
    if (!seen.has(p)) {
      seen.add(p)
      candidates.push(p)
    }
  }

  for (const p of PREFERRED_FROM_RUST) {
    push(p)
  }
  push(readSagePortFromFile())
  if (process.env.SAGE_PORT) {
    push(parseInt(process.env.SAGE_PORT, 10))
  }

  for (const port of candidates) {
    if (await probeHealth(port)) {
      const url = `http://127.0.0.1:${port}`
      targetCache = { url, t: now }
      // eslint-disable-next-line no-console
      console.log(`[vite] desktop: API proxy -> ${url} (/api/health ok)`)
      return url
    }
  }

  const fallback = 'http://127.0.0.1:18080'
  targetCache = { url: fallback, t: now }
  // eslint-disable-next-line no-console
  console.warn('[vite] desktop: no /api/health on tried ports; proxy -> ' + fallback)
  return fallback
}

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    vue(),
    {
      name: 'sage-desktop-api-proxy',
      configureServer(server) {
        const proxy = createProxyMiddleware({
          pathFilter: (pathname) => pathname.startsWith('/dev-api') || pathname.startsWith('/api/'),
          pathRewrite: (path) => {
            if (path.startsWith('/dev-api')) {
              return path.replace(/^\/dev-api/, '') || '/'
            }
            return path
          },
          changeOrigin: true,
          target: 'http://127.0.0.1:18080',
          router: () => resolveBackendTarget()
        })
        server.middlewares.use(proxy)
      }
    }
  ],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src')
    }
  },
  server: {
    port: 1420,
    strictPort: true
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
          vendor: ['vue', 'vue-router', 'pinia'],
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
