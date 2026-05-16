import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      // Inside docker compose the backend service is reachable at host `backend`.
      // For local `npm run dev` without docker, override via VITE_API_HOST.
      '/api': `http://${process.env.VITE_API_HOST ?? 'backend'}:8000`,
      '/ws': { target: `ws://${process.env.VITE_API_HOST ?? 'backend'}:8000`, ws: true },
    },
  },
})
