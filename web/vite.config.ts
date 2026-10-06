/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The built interface is shipped inside the Python package, which serves it.
export default defineConfig({
  plugins: [react()],
  build: { outDir: '../src/lilly/web', emptyOutDir: true, sourcemap: false },
  server: { proxy: { '/api': 'http://127.0.0.1:8787', '/login': 'http://127.0.0.1:8787' } },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    exclude: ['e2e/**'],
  },
})
