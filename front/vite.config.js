import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_')
  const backendOrigin = env.VITE_BACKEND_ORIGIN || 'http://127.0.0.1:8000'

  return {
    plugins: [react()],
    server: {
      proxy: {
        '/health': { target: backendOrigin, changeOrigin: true },
        '/ui': { target: backendOrigin, changeOrigin: true },
        '/api/v1': { target: backendOrigin, changeOrigin: true },
      },
    },
  }
})
