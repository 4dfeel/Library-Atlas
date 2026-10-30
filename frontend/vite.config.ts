import { fileURLToPath, URL } from 'node:url';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

// Dev and preview pages reach the local service through this proxy, so the browser only
// ever sees one origin. The service must list these origins in ATLAS_DEV_ORIGINS.
const apiProxy = { '/api': `http://127.0.0.1:${process.env.ATLAS_PORT ?? 8765}` };

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: { host: '127.0.0.1', port: 5173, strictPort: true, proxy: apiProxy },
  preview: { host: '127.0.0.1', port: 4173, strictPort: true, proxy: apiProxy },
  build: { target: 'es2022', sourcemap: false },
});
