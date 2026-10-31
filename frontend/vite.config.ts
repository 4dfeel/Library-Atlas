import { fileURLToPath, URL } from 'node:url';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { cp } from 'node:fs/promises';
import { resolve } from 'node:path';
import { defineConfig, type Plugin } from 'vite';

// Dev and preview pages reach the local service through this proxy, so the browser only
// ever sees one origin. The service must list these origins in ATLAS_DEV_ORIGINS.
const apiProxy = { '/api': `http://127.0.0.1:${process.env.ATLAS_PORT ?? 8765}` };

// A PDF's fonts and Japanese character maps come from this build, never from a remote address.
function pdfAssets(): Plugin {
  const source = fileURLToPath(new URL('./node_modules/pdfjs-dist', import.meta.url));
  let outDir = 'dist';
  return {
    name: 'atlas-pdf-assets',
    apply: 'build',
    configResolved(config) {
      outDir = config.build.outDir;
    },
    async closeBundle() {
      for (const folder of ['cmaps', 'standard_fonts'])
        await cp(resolve(source, folder), resolve(outDir, 'pdfjs', folder), { recursive: true });
    },
  };
}

export default defineConfig({
  plugins: [react(), tailwindcss(), pdfAssets()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: { host: '127.0.0.1', port: 5173, strictPort: true, proxy: apiProxy },
  preview: { host: '127.0.0.1', port: 4173, strictPort: true, proxy: apiProxy },
  build: { target: 'es2022', sourcemap: false },
});
