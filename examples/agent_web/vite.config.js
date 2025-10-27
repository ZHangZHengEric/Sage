import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  // 加载环境变量
  const env = loadEnv(mode, process.cwd(), '')
  
  return {
  plugins: [react()],
  server: {
    port: process.env.SAGE_DEV_WEB_SERVICE_PORT || env.SAGE_DEV_WEB_SERVICE_PORT || 23233,
    host: true,
    allowedHosts: [process.env.AGENT_WEB_HOST || env.AGENT_WEB_HOST || 'agentdev.rcrai.com'],
    proxy: {
      '/api': {
        target: process.env.VITE_API_TARGET || env.VITE_API_TARGET || 'http://localhost:23232',
        changeOrigin: true,
        secure: false,
        ws: false,
        timeout: 300000, // 增加到5分钟
        proxyTimeout: 300000, // 代理超时时间
        followRedirects: true,
        headers: {
          'Connection': 'keep-alive', // 启用Keep-Alive连接
          'Keep-Alive': 'timeout=300, max=1000',
          'Cache-Control': 'no-cache'
        },
        configure: (proxy, _options) => {
          proxy.on('error', (err, req, res) => {
            const timestamp = new Date().toISOString();
            console.error(`[${timestamp}] Proxy Error for ${req.method} ${req.url}:`, err);
            console.error(`[${timestamp}] Error details:`, {
              code: err.code,
              message: err.message,
              stack: err.stack
            });
            
            if (!res.headersSent) {
              res.writeHead(502, {
                'Content-Type': 'application/json',
              });
              res.end(JSON.stringify({
                error: 'Bad Gateway',
                message: 'Proxy connection failed',
                details: err.message,
                timestamp: timestamp
              }));
            }
          });
          
          proxy.on('proxyReq', (proxyReq, req, _res) => {
            const timestamp = new Date().toISOString();
            console.log(`[${timestamp}] Sending Request to the Target:`, req.method, req.url);
            
            // 对于 auto-generate 接口，设置更长的超时时间
            if (req.url.includes('/api/agent/auto-generate')) {
              console.log(`[${timestamp}] Auto-generate request detected, setting extended timeout`);
              proxyReq.setTimeout(300000); // 5分钟超时
            } else {
              proxyReq.setTimeout(180000); // 默认3分钟超时
            }
          });
          
          // 简化的响应监听 - 只记录日志，不干扰数据流
          proxy.on('proxyRes', (proxyRes, req, res) => {
            const timestamp = new Date().toISOString();
            console.log(`[${timestamp}] Received Response from the Target:`, proxyRes.statusCode, req.url);
            console.log(`[${timestamp}] Response content-length:`, proxyRes.headers['content-length'] || 'unknown');
            
            // 只在出错时记录详细信息
            if (proxyRes.statusCode >= 400) {
              console.log(`[${timestamp}] Error Response headers:`, JSON.stringify(proxyRes.headers, null, 2));
            }
          });
          
          proxy.on('proxyReqTimeout', (req, res) => {
            const timestamp = new Date().toISOString();
            console.log(`[${timestamp}] Proxy request timeout for:`, req.url);
            if (!res.headersSent) {
              res.writeHead(504, {
                'Content-Type': 'application/json',
              });
              res.end(JSON.stringify({ 
                error: 'Gateway Timeout', 
                message: 'Request timeout',
                timestamp: timestamp
              }));
            }
          });
        },
      }
    }
  },
  build: {
    outDir: 'dist',
    sourcemap: true
  },
  define: {
    // 定义全局常量，替代环境变量
    __API_BASE_URL__: JSON.stringify('http://localhost:23232')
  },
  esbuild: {
    loader: 'jsx',
    include: /src\/.*\.[jt]sx?$/,
    exclude: []
  },
  optimizeDeps: {
    esbuildOptions: {
      loader: {
        '.js': 'jsx'
      }
    }
  }
}})