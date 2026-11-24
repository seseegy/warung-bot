import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// base './' agar hasil build bisa disajikan dari path apa pun
// (FastAPI StaticFiles di / maupun reverse proxy di subpath).
export default defineConfig({
  plugins: [react()],
  base: './',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: false,
  },
  server: {
    port: 5173,
    proxy: {
      // Dev saja: /api diteruskan ke API FastAPI lokal.
      '/api': 'http://127.0.0.1:8000',
    },
  },
});
