/// <reference types="vite/client" />
/// <reference types="vite-plugin-pwa/client" />

declare const __APP_VERSION__: string;
declare const __FRONTEND_BUILD_SHA__: string;

interface ImportMetaEnv {
  /** Base URL of the A.R.G.U.S. Python backend (Render). */
  readonly VITE_ARGUS_BACKEND_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
