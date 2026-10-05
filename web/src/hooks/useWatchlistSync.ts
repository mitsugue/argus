import { useEffect, useState } from 'react';
import { watchlistSyncState, subscribeWatchlistSync, startWatchlistAutoSync } from '../lib/watchlistAutoSync';
export function useWatchlistSync() {
  const [status, setStatus] = useState(watchlistSyncState);
  useEffect(() => subscribeWatchlistSync(() => setStatus(watchlistSyncState())), []);
  return status;
}
export function WatchlistSyncLifecycle() {
  useEffect(() => startWatchlistAutoSync(import.meta.env.VITE_ARGUS_BACKEND_URL || ''), []);
  return null;
}
