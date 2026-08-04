import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3008,
    proxy: {
      '/chat': 'http://localhost:8001',
      '/health': 'http://localhost:8001',
      '/api': 'http://localhost:8001',
      '/debug': 'http://localhost:8001',
    },
  },
})
