/// <reference types="node" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { VitePWA } from 'vite-plugin-pwa';
import { readFileSync } from 'node:fs';

// GitHub Pages serves the site under /<repo-name>/ — supply this via env at build time.
// Locally and on other deploy targets (Vercel etc.) set DEPLOY_BASE='/' or leave unset.
const base = process.env.DEPLOY_BASE ?? '/';

const packageJsonUrl = new URL('./package.json', import.meta.url);
const readVersion = (): string =>
  (JSON.parse(readFileSync(packageJsonUrl, 'utf-8')) as { version: string }).version;

// `__APP_VERSION__` resolves to a runtime global that this plugin injects fresh
// into index.html on EVERY load (dev-serve per reload, and once at build time).
// So a dev-server *reload* shows the latest version without a restart — the
// plain build-time `define` alone would freeze it until the server restarts.
// esbuild `define` only accepts a JSON value or a bare entity name, so the value
// is the entity name `globalThis.__ARGUS_VERSION__` (the injected global), not an
// expression.
const argusVersionInjector = {
  name: 'argus-version-injector',
  transformIndexHtml() {
    return [{
      tag: 'script',
      injectTo: 'head-prepend' as const,
      children: `globalThis.__ARGUS_VERSION__=${JSON.stringify(readVersion())};`,
    }];
  },
};

export default defineConfig({
  base,
  define: {
    __APP_VERSION__: 'globalThis.__ARGUS_VERSION__',
  },
  plugins: [
    argusVersionInjector,
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.svg', 'countries.geojson'],
      manifest: {
        name: 'A.R.G.U.S.',
        short_name: 'ARGUS',
        description: 'Autonomous Risk and Global Uncertainty Scanner',
        theme_color: '#0B1118',
        background_color: '#0B1118',
        display: 'fullscreen',
        orientation: 'portrait',
        // Manifest icon src is resolved relative to the manifest URL, so
        // bare filenames work under any base path.
        start_url: base,
        scope: base,
        icons: [
          {
            src: 'icon-192.svg',
            sizes: '192x192',
            type: 'image/svg+xml',
            purpose: 'any maskable',
          },
          {
            src: 'icon-512.svg',
            sizes: '512x512',
            type: 'image/svg+xml',
            purpose: 'any maskable',
          },
        ],
      },
      workbox: {
        navigateFallback: `${base}index.html`,
        maximumFileSizeToCacheInBytes: 8 * 1024 * 1024,
        runtimeCaching: [
          {
            urlPattern: /^https:\/\/fonts\.(?:googleapis|gstatic)\.com\/.*/i,
            handler: 'CacheFirst',
            options: { cacheName: 'fonts-cache', expiration: { maxEntries: 20 } },
          },
        ],
      },
    }),
  ],
  resolve: {
    dedupe: ['three', 'react', 'react-dom'],
  },
  optimizeDeps: {
    include: ['three'],
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          three: ['three'],
          globe: ['react-globe.gl'],
          motion: ['framer-motion'],
          rnd: ['react-rnd'],
        },
      },
    },
  },
  server: {
    host: '127.0.0.1',
    port: process.env.PORT ? Number(process.env.PORT) : 5173,
    strictPort: !!process.env.PORT,
  },
});
