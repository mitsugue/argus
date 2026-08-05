export interface PrivateSymbolManifest {
  schemaVersion: 'argus-private-client-symbol-manifest-v1';
  revision: string;
  asOf: string;
  symbols: string[];
}
export function normalizePrivateSymbol(market: unknown, symbol: unknown): string | null;
export function buildPrivateSymbolManifest(
  assets: unknown, asOf?: string,
): PrivateSymbolManifest | null;
export function syncPrivateSymbolManifest(): Promise<Record<string, unknown>>;
export function startPrivateSymbolManifestSync(): void;
