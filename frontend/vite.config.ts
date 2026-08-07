import path from 'path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': path.resolve(import.meta.dirname, './src') },
  },
  server: {
    host: true, // 0.0.0.0 — acessível do iPhone na mesma rede Wi-Fi/Ethernet
    proxy: { '/api': 'http://localhost:8765' },
  },
})
