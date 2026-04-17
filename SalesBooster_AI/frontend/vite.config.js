import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  // Must match where SalesBooster Django listens (default: python manage.py runserver → port 8000).
  const apiProxyTarget = env.API_PROXY_TARGET || 'http://127.0.0.1:8000'
  // Allow deploying under subpaths like /spam/ instead of only domain root.
  const basePath = env.VITE_BASE_PATH || '/'

  return {
    base: basePath,
    plugins: [react()],
    server: {
      proxy: {
        '/api': {
          target: apiProxyTarget,
          changeOrigin: true,
          timeout: 180_000,
          proxyTimeout: 180_000,
          configure: (proxy) => {
            proxy.on('error', (err) => {
              console.warn(
                `[vite /api proxy] ${err.message}\n` +
                  `  → Start backend: cd django_backend && python manage.py runserver\n` +
                  `  → Or set API_PROXY_TARGET in frontend/.env.development to your Django URL (e.g. http://127.0.0.1:8001)\n` +
                  `  → Test: open ${apiProxyTarget}/api/health in a browser (expect {"ok":true,...})`
              )
            })
          },
        },
      },
    },
  }
})
