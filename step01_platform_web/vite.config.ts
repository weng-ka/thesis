import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // GitHub Pages 需要設 base（資源路徑會掛在 /<repo>/ 下）
  base: process.env.BASE_PATH || '/',
  server: {
    proxy: {
      // Dev-only proxy to bypass CORS and Google query restrictions.
      // Usage:
      //   GAS_EXEC_BASE="https://script.google.com/macros/s/<ID>/exec" npm run dev
      // Then in UI, set exec base to "/gas".
      '/gas': {
        target: process.env.GAS_EXEC_BASE,
        changeOrigin: true,
        secure: true,
        rewrite: (path) => path.replace(/^\/gas/, ''),
      },
    },
  },
})
