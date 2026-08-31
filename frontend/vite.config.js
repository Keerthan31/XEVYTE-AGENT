import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api/auth/login': {
        target: 'http://localhost:8084',
        changeOrigin: true,
        headers: {
          'Origin': 'http://scaloz.localhost:3004'
        }
      },
      '/api/agent': {
        target: 'http://localhost:8000',
        changeOrigin: true
      },
      '/downloads': {
        target: 'http://localhost:8000',
        changeOrigin: true
      },
      '/api/customers': {
        target: 'http://localhost:8082',
        changeOrigin: true
      },
      '/api/contracts': {
        target: 'http://localhost:8082',
        changeOrigin: true
      }
    }
  },
})
