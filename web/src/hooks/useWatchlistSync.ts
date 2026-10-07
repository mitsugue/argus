import { useEffect, useState } from 'react';
import { watchlistSyncState, subscribeWatchlistSync, startWatchlistAutoSync } from '../lib/watchlistAutoSync';
import { OWNER_AUTH_REQUIRED } from '../lib/ownerSession';
import { startAccountWatchlistSync } from '../lib/accountWatchlistSync';
export function useWatchlistSync() {
  const [status, setStatus] = useState(watchlistSyncState);
  useEffect(() => subscribeWatchlistSync(() => setStatus(watchlistSyncState())), []);
  return status;
}
export function WatchlistSyncLifecycle() {
  useEffect(() => (OWNER_AUTH_REQUIRED ? startAccountWatchlistSync : startWatchlistAutoSync)(
    import.meta.env.VITE_ARGUS_BACKEND_URL || ''), []);
  return null;
}
