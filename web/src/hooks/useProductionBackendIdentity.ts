import { useEffect, useState } from 'react';
import {
  parseProductionBackendIdentity,
  type BackendRuntimeIdentity,
} from '../domain/runtimeVersionTruth';

export const PRODUCTION_BACKEND_MANIFEST_URL =
  'https://raw.githubusercontent.com/mitsugue/argus/production-release/production/argus-backend.json';
const IDENTITY_POLL_MS = 5 * 60_000;

export function useProductionBackendIdentity(): BackendRuntimeIdentity | null {
  const [identity, setIdentity] = useState<BackendRuntimeIdentity | null>(null);

  useEffect(() => {
    let alive = true;

    async function load() {
      try {
        const url = `${PRODUCTION_BACKEND_MANIFEST_URL}?cb=${Date.now()}`;
        const response = await fetch(url, { cache: 'no-store' });
        if (!response.ok) throw new Error('production_backend_identity_unavailable');
        const parsed = parseProductionBackendIdentity(await response.json());
        if (alive) setIdentity(parsed);
      } catch {
        if (alive) setIdentity(null);
      }
    }

    void load();
    const timer = window.setInterval(() => { void load(); }, IDENTITY_POLL_MS);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, []);

  return identity;
}
