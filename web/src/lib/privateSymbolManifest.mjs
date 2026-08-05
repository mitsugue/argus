const ASSETS_KEY = 'argus.assets.v1';
const TOKEN_KEY = 'argus.ownerSyncToken.v1';
const SCHEMA = 'argus-private-client-symbol-manifest-v1';
const REFRESH_MS = 10 * 60 * 1000;

export function normalizePrivateSymbol(market, symbol) {
  const m = String(market || '').trim().toUpperCase();
  const s = String(symbol || '').trim().toUpperCase();
  if (m === 'JP' && (/^[0-9]{4}$/.test(s) || /^[0-9]{3}[A-Z]$/.test(s))) return `JP.${s}`;
  if (m === 'US' && /^[A-Z]{1,5}(?:[.\-][A-Z]{1,2})?$/.test(s)) return `US.${s}`;
  return null;
}

function revisionFor(symbols) {
  // Revision metadata is derived from symbol IDs only. It is not a portfolio
  // value and is never exposed by the public count-only diagnostics endpoint.
  let hash = 0x811c9dc5;
  for (const ch of symbols.join('\n')) {
    hash ^= ch.charCodeAt(0);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash.toString(16).padStart(8, '0');
}

export function buildPrivateSymbolManifest(assets, asOf = new Date().toISOString()) {
  if (!Array.isArray(assets)) return null;
  const symbols = [];
  for (const asset of assets) {
    if (!asset || typeof asset !== 'object') continue;
    // A locally held asset remains registered even when hidden from the UI.
    // The boolean/quantity itself is never copied into the manifest.
    if (asset.enabled === false && !(Number(asset.quantity) > 0)) continue;
    const code = normalizePrivateSymbol(asset.market, asset.symbol);
    if (code && !symbols.includes(code)) symbols.push(code);
  }
  symbols.sort();
  if (!symbols.length) return null; // empty/unknown is not complete evidence
  return { schemaVersion: SCHEMA, revision: revisionFor(symbols), asOf, symbols };
}

export async function syncPrivateSymbolManifest() {
  if (typeof window === 'undefined') return { status: 'unavailable' };
  const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;
  let token = '';
  let assets = null;
  try {
    token = localStorage.getItem(TOKEN_KEY) || '';
    assets = JSON.parse(localStorage.getItem(ASSETS_KEY) || 'null');
  } catch {
    return { status: 'local_store_unavailable' };
  }
  const manifest = buildPrivateSymbolManifest(assets);
  if (!backend || !token.trim() || !manifest) return { status: 'not_ready' };
  try {
    const response = await fetch(
      backend.replace(/\/$/, '') + '/api/argus/calibration/private-symbol-manifest',
      {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ownerToken: token.trim(), manifest }),
      },
    );
    return response.ok ? { status: 'verified', revision: manifest.revision }
      : { status: 'rejected', httpStatus: response.status };
  } catch {
    return { status: 'offline_last_verified_preserved' };
  }
}

let started = false;
export function startPrivateSymbolManifestSync() {
  if (started || typeof window === 'undefined') return;
  started = true;
  const run = () => { syncPrivateSymbolManifest().catch(() => {}); };
  window.setTimeout(run, 2_000);
  window.setInterval(run, REFRESH_MS);
  window.addEventListener('argus:data-synced', run);
  window.addEventListener('storage', (event) => {
    if (event.key === ASSETS_KEY || event.key === TOKEN_KEY) run();
  });
}
