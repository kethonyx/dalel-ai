import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_')
  const secretEnv = loadEnv(mode, process.cwd(), 'API_')
  const backendOrigin = env.VITE_BACKEND_ORIGIN || 'http://127.0.0.1:8000'
  const apiKey = secretEnv.API_KEY || process.env.API_KEY

  const protectedApiProxy = {
    target: backendOrigin,
    changeOrigin: true,
    configure(proxy) {
      if (apiKey) proxy.on('proxyReq', (request) => request.setHeader('X-API-Key', apiKey))
    },
  }

  return {
    plugins: [react()],
    server: {
      proxy: {
        '/health': { target: backendOrigin, changeOrigin: true },
        '/ui': { target: backendOrigin, changeOrigin: true },
        '/api/v1': protectedApiProxy,
      },
    },
    // боевой показ: собранный фронт через vite preview (прокси те же, ключ подставляет сервер),
    // наружу — туннелем pinggy (scripts/front.sh)
    preview: {
      allowedHosts: ['.pinggy.link', '.pinggy-free.link', '.pinggy.net'],
    },
  }
})
