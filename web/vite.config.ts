/// <reference types="node" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { VitePWA } from 'vite-plugin-pwa';
import { readFileSync } from 'node:fs';

// GitHub Pages serves the site under /<repo-name>/ — supply this via env at build time.
// Locally and on other deploy targets (Vercel etc.) set DEPLOY_BASE='/' or leave unset.
const base = process.env.DEPLOY_BASE ?? '/';

const packageJsonUrl = new URL('./package.json', import.meta.url);
const productVersionUrl = new URL('../product-version.json', import.meta.url);
const readVersion = (): string =>
  (JSON.parse(readFileSync(packageJsonUrl, 'utf-8')) as { version: string }).version;
const readProductVersion = (): string => {
  const value = JSON.parse(readFileSync(productVersionUrl, 'utf-8')) as Record<string, unknown>;
  if (Object.keys(value).sort().join(',') !== 'productVersion,schemaVersion'
      || value.schemaVersion !== 'argus-product-version-v1'
      || typeof value.productVersion !== 'string'
      || !/^v[1-9]\d*(?:\.\d+)*$/.test(value.productVersion)) {
    throw new Error('invalid canonical product-version.json');
  }
  return value.productVersion;
};
const frontendBuildSha = process.env.VITE_ARGUS_BUILD_SHA ?? 'local';
const bundleVersion = readVersion();
const bundleProductVersion = readProductVersion();

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
      children: [
        `globalThis.__ARGUS_VERSION__=${JSON.stringify(bundleVersion)};`,
        `globalThis.__ARGUS_PRODUCT_VERSION__=${JSON.stringify(bundleProductVersion)};`,
        `globalThis.__ARGUS_BUILD_SHA__=${JSON.stringify(frontendBuildSha)};`,
        `(function(){try{var wanted=${JSON.stringify(`${bundleVersion}|${bundleProductVersion}|${frontendBuildSha}`)};var stored=localStorage.getItem('argus.bundle.identity');var guard='argus_identity_purge_'+wanted;if(stored!==wanted&&!sessionStorage.getItem(guard)){sessionStorage.setItem(guard,'1');document.documentElement.style.visibility='hidden';Promise.all([(navigator.serviceWorker&&navigator.serviceWorker.getRegistrations?navigator.serviceWorker.getRegistrations().then(function(rs){return Promise.all(rs.map(function(r){return r.unregister()}))}):Promise.resolve()),(globalThis.caches?caches.keys().then(function(ks){return Promise.all(ks.map(function(k){return caches.delete(k)}))}):Promise.resolve())]).finally(function(){location.reload()});}}catch(_){}})();`,
      ].join(''),
    }];
  },
};

export default defineConfig({
  base,
  define: {
    // These values identify the executing bundle. They must be compiled into
    // the JavaScript: a stale bundle must never inherit the new index globals
    // and falsely claim that it is current.
    __APP_VERSION__: JSON.stringify(bundleVersion),
    __PRODUCT_VERSION__: JSON.stringify(bundleProductVersion),
    __FRONTEND_BUILD_SHA__: JSON.stringify(frontendBuildSha),
  },
  plugins: [
    argusVersionInjector,
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      // Provide the virtual:pwa-register module in dev too, so `vite dev` (preview)
      // doesn't fail to resolve it. Zero production impact (build already emits it).
      devOptions: { enabled: true },
      includeAssets: ['favicon.svg'],
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
        cleanupOutdatedCaches: true,
        clientsClaim: true,
        skipWaiting: true,
        navigateFallback: `${base}index.html`,
        maximumFileSizeToCacheInBytes: 8 * 1024 * 1024,
        runtimeCaching: [
          {
            urlPattern: /^https:\/\/fonts\.(?:googleapis|gstatic)\.com\/.*/i,
            handler: 'CacheFirst',
            options: { cacheName: 'fonts-cache', expiration: { maxEntries: 20 } },
          },
          {
            // Verified market views have their own schema/hash checked
            // IndexedDB repository. Cache Storage must not bypass that
            // validation or manufacture a 200 in front of the ETag boundary.
            urlPattern: /^https:\/\/argus-backend-[a-z0-9]+\.onrender\.com\/api\/argus\/chart-intelligence(?:\?.*)?$/i,
            handler: 'NetworkOnly',
          },
          {
            // ARGUS backend GETs — StaleWhileRevalidate (v10.190). On launch the SW
            // serves the LAST cached snapshot INSTANTLY (so the screen is populated
            // even while the free-plan dyno cold-starts / the fetches are in flight),
            // then revalidates in the background. Directly targets the "画面が整うのに
            // 時間がかかる" complaint without any extra API spend. All /api/argus/*
            // responses already carry asOf/status, so a brief stale paint is honest.
            urlPattern: /^https:\/\/argus-backend-[a-z0-9]+\.onrender\.com\/api\/argus\/.*/i,
            handler: 'StaleWhileRevalidate',
            options: {
              cacheName: 'argus-api',
              expiration: { maxEntries: 80, maxAgeSeconds: 60 * 60 * 12 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
        ],
      },
    }),
  ],
  resolve: {
    dedupe: ['react', 'react-dom'],
  },
  server: {
    host: '127.0.0.1',
    port: process.env.PORT ? Number(process.env.PORT) : 5173,
    strictPort: !!process.env.PORT,
  },
});
